"""Orchestrate IR → plan → apply/verify across engine steps."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from .ado_client import AdoClient
from .excel_ir import build_ir
from .models import ApplyResult, DryRunRequest, DryRunResponse
from .org_url import normalize_ado_org_url, parse_ado_org_url
from .paths import output_root
from .planner import STEP_ORDER, build_dry_run_plan
from .run_outcome import project_name_notice
from .timing import format_duration_ms, summarize_timings
from .writers import (
    apply_backlog,
    apply_catalog,
    apply_layout,
    apply_process,
    apply_project,
    apply_report,
    apply_teams,
)
from .writers.report import write_run_summary

Emit = Callable[[dict[str, Any]], None]


class RunCancelled(Exception):
    """Raised at a safe checkpoint after the user cancels a job."""


def _safe_part(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    return slug.strip("._-") or "ado"


def default_output_dir(org_url: str, project_name: str, root: str | None = None) -> Path:
    parsed = parse_ado_org_url(org_url)
    org = parsed.org if parsed.ok else "org"
    base = Path(root).expanduser() if (root or "").strip() else output_root()
    return base / _safe_part(f"{org}_{project_name}")


def run_apply(
    request: DryRunRequest,
    *,
    pat: str,
    dry_run: bool,
    emit: Emit | None = None,
    step_filter: list[str] | None = None,
    catalog_limit: int | None = None,
    should_cancel: Callable[[], bool] | None = None,
    run_id: str | None = None,
) -> ApplyResult:
    events: list[dict[str, Any]] = []
    timings: list[dict[str, Any]] = []
    run_started = time.perf_counter()
    run_started_wall = time.time()
    run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
    cancel_requested = should_cancel or (lambda: False)

    def _emit(event: dict[str, Any]) -> None:
        events.append(event)
        if emit:
            emit(event)

    def check_cancel() -> None:
        if cancel_requested():
            raise RunCancelled("Run cancelled by user")

    def step_emit(step_id: str, message: str) -> None:
        _emit({"type": "step-progress", "stepId": step_id, "message": message})
        # Catalog handles cancel itself so in-flight creates are recorded in the id-map.
        if step_id != "catalog":
            check_cancel()

    def catalog_progress(payload: dict[str, Any]) -> None:
        _emit({"type": "catalog-progress", "stepId": "catalog", **payload})

    ir = build_ir(
        request.excel_file,
        catalog_source_dir=request.catalog_source_dir,
        workbook_version=request.workbook_version,
        process_name=request.process_name,
        project_name=request.project_name,
    )
    ir.setdefault("targets", {})["project_description"] = (
        request.project_description or ""
    ).strip()
    plan = build_dry_run_plan(
        ir,
        update_policy=request.update_policy,
        confirm_process_update=request.confirm_process_update,
        confirm_project_update=request.confirm_project_update,
        known_process_exists=request.known_process_exists,
        known_project_exists=request.known_project_exists,
        step_filter=step_filter,
    )
    if not plan.ok:
        return ApplyResult(
            ok=False,
            dry_run=dry_run,
            plan=plan,
            step_results={},
            output_dir=None,
            error="; ".join(plan.errors),
            events=events,
            duration_ms=0,
            timings=[],
        )

    org_url = normalize_ado_org_url(request.org_url)
    output_dir = default_output_dir(org_url, request.project_name, request.output_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Dry-run apply never calls Azure DevOps; client is only created for live apply.
    client = None if dry_run else AdoClient(org_url, pat)
    step_results: dict[str, Any] = {}
    process_id: str | None = None

    planned = {step["id"]: step for step in plan.steps}

    def _write_summary(error: str | None, cancelled: bool) -> dict[str, Any] | None:
        """Every run (incl. failed/cancelled) refreshes the summary so files never disagree."""
        try:
            outcome = write_run_summary(
                ir,
                step_results=step_results,
                output_dir=output_dir,
                org_url=org_url,
                dry_run=dry_run,
                run_id=run_id,
                run_started=run_started_wall,
                error=error,
                cancelled=cancelled,
            )
        except Exception as exc:  # noqa: BLE001 - never mask the run's own result
            _emit({"type": "step-progress", "stepId": "report", "message": f"Could not write summary: {exc}"})
            return None
        _emit(
            {
                "type": "step-progress",
                "stepId": "report",
                "message": f"Summary: {outcome['headline']}",
            }
        )
        return outcome
    selected = step_filter or STEP_ORDER

    _emit({"type": "apply-started", "message": f"Starting {'dry-run apply' if dry_run else 'apply'}"})
    template_notice = project_name_notice(
        request.project_name,
        template_rows=int((ir.get("project") or {}).get("project_placeholders_replaced") or 0),
        catalog_values=0,
    )
    if template_notice:
        _emit({"type": "info", "message": template_notice})

    try:
        # Live process/layout/project requires DevLabs Multivalue extension (UI also preflights).
        setup_steps = {"process", "layout", "project"}
        needs_multivalue = any(
            step_id in setup_steps
            and (planned.get(step_id) or {}).get("planned_action") != "skip"
            for step_id in selected
        )
        if client is not None and needs_multivalue:
            _emit(
                {
                    "type": "preflight",
                    "message": "Checking DevLabs Multivalue control extension…",
                }
            )
            client.require_multivalue_extension()
            _emit(
                {
                    "type": "preflight",
                    "message": "DevLabs Multivalue control extension is installed.",
                }
            )

        for step_id in selected:
            step = planned.get(step_id)
            if not step:
                continue
            check_cancel()
            action = step.get("planned_action")
            if action == "skip":
                step_results[step_id] = {"skipped": True, "duration_ms": 0}
                timings.append({"stepId": step_id, "durationMs": 0, "skipped": True})
                _emit(
                    {
                        "type": "step-skipped",
                        "stepId": step_id,
                        "durationMs": 0,
                        "message": f"Skipped {step_id} by plan/policy",
                    }
                )
                continue

            _emit(
                {
                    "type": "step-started",
                    "stepId": step_id,
                    "message": f"Starting {step_id} ({action})",
                }
            )
            step_started = time.perf_counter()

            if step_id == "process":
                result = apply_process(client, ir, dry_run=dry_run, emit=step_emit)
                process_id = result.get("process_id")
                if not dry_run and client and not process_id:
                    process_id = client.get_process_id(request.process_name)
            elif step_id == "layout":
                result = apply_layout(
                    client, ir, dry_run=dry_run, emit=step_emit, process_id=process_id
                )
            elif step_id == "project":
                result = apply_project(
                    client, ir, dry_run=dry_run, emit=step_emit, process_id=process_id
                )
            elif step_id == "teams":
                root = request.root_area_path or request.project_name
                result = apply_teams(
                    client, ir, dry_run=dry_run, emit=step_emit, root_area_path=root
                )
            elif step_id == "backlog":
                result = apply_backlog(
                    client, ir, dry_run=dry_run, emit=step_emit, process_id=process_id
                )
            elif step_id == "catalog":
                result = apply_catalog(
                    client,
                    ir,
                    dry_run=dry_run,
                    emit=step_emit,
                    output_dir=output_dir,
                    limit=catalog_limit,
                    convert_markdown_to_html=bool(request.convert_markdown_to_html),
                    parallel_workers=int(
                        getattr(request, "catalog_parallel_workers", 4) or 4
                    ),
                    progress=catalog_progress,
                    should_cancel=cancel_requested,
                    run_id=run_id,
                )
            elif step_id == "report":
                result = apply_report(
                    ir,
                    step_results=step_results,
                    output_dir=output_dir,
                    org_url=org_url,
                    emit=step_emit,
                    dry_run=dry_run,
                    run_id=run_id,
                    run_started=run_started_wall,
                )
            else:
                result = {"skipped": True, "reason": f"Unknown step {step_id}"}

            duration_ms = int((time.perf_counter() - step_started) * 1000)
            if isinstance(result, dict):
                result = {**result, "duration_ms": duration_ms}
            step_results[step_id] = result
            timings.append(
                {"stepId": step_id, "durationMs": duration_ms, "skipped": False}
            )
            if step_id == "catalog" and cancel_requested():
                _emit(
                    {
                        "type": "step-cancelled",
                        "stepId": step_id,
                        "durationMs": duration_ms,
                        "message": f"Stopped {step_id} after {format_duration_ms(duration_ms)}",
                        "result": result,
                    }
                )
                raise RunCancelled("Run cancelled by user")
            _emit(
                {
                    "type": "step-completed",
                    "stepId": step_id,
                    "durationMs": duration_ms,
                    "message": f"Finished {step_id} ({format_duration_ms(duration_ms)})",
                    "result": result,
                }
            )

        check_cancel()
        outcome = _write_summary(None, False)

        total_ms = int((time.perf_counter() - run_started) * 1000)
        summary_text = summarize_timings(timings, total_ms=total_ms)
        _emit(
            {
                "type": "run-summary",
                "durationMs": total_ms,
                "timings": timings,
                "message": f"Run timing:\n{summary_text}",
            }
        )

        return ApplyResult(
            ok=True,
            dry_run=dry_run,
            plan=plan,
            step_results=step_results,
            output_dir=str(output_dir),
            error=None,
            events=events,
            duration_ms=total_ms,
            timings=timings,
            run_id=run_id,
            outcome=outcome,
        )
    except Exception as exc:  # noqa: BLE001
        total_ms = int((time.perf_counter() - run_started) * 1000)
        cancelled = isinstance(exc, RunCancelled)
        _emit(
            {
                "type": "job-cancelled" if cancelled else "job-error",
                "message": str(exc),
                "durationMs": total_ms,
            }
        )
        if timings:
            _emit(
                {
                    "type": "run-summary",
                    "durationMs": total_ms,
                    "timings": timings,
                    "message": (
                        f"Run timing ({'cancelled' if cancelled else 'failed'} after "
                        f"{format_duration_ms(total_ms)}):\n"
                        f"{summarize_timings(timings, total_ms=total_ms)}"
                    ),
                }
            )
        return ApplyResult(
            ok=False,
            dry_run=dry_run,
            plan=plan,
            step_results=step_results,
            output_dir=str(output_dir),
            error=str(exc),
            cancelled=cancelled,
            events=events,
            duration_ms=total_ms,
            timings=timings,
            run_id=run_id,
            outcome=_write_summary(None if cancelled else str(exc), cancelled),
        )
