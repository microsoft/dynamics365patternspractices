"""Orchestrate IR → plan → apply/verify across engine steps."""

from __future__ import annotations

import time
from typing import Any, Callable

from .ado_client import AdoClient, AdoError, ReadOnlyAdoClient
from .excel_ir import build_ir
from .models import ApplyResult, DryRunRequest
from .org_url import normalize_ado_org_url
from .output_folder import default_output_dir, resolve_output_dir, settle_output_dir
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
    org_url = normalize_ado_org_url(request.org_url)
    # Writers get no client in a rehearsal; the catalog change report gets a read-only one.
    client = None if dry_run else AdoClient(org_url, pat)
    change_reader: ReadOnlyAdoClient | None = None
    if dry_run and pat.strip():
        try:
            change_reader = ReadOnlyAdoClient(org_url, pat)
        except ValueError:
            change_reader = None

    output_dir = resolve_output_dir(org_url, request.project_name, request.output_root)
    default_folder_name = default_output_dir(org_url, request.project_name, request.output_root).name
    step_results: dict[str, Any] = {}

    def _write_summary(error: str | None, cancelled: bool) -> dict[str, Any] | None:
        """Every run (incl. failed/cancelled) refreshes the summary so files never disagree."""
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
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

    process_exists = request.known_process_exists
    project_exists = request.known_project_exists
    # (target, list the browser sent: None = not loaded, False = loaded without it)
    unlisted: list[tuple[str, bool | None]] = []
    if client:
        # The browser's inventory is optional and can be stale; policy gates use what ADO reports.
        try:
            process_exists = client.get_process_id(request.process_name) is not None
            project_exists = client.get_project_id(request.project_name) is not None
        except AdoError as exc:
            error = f"Could not check the process and project in Azure DevOps before the run: {exc}"
            _emit({"type": "job-error", "message": error, "durationMs": 0})
            return ApplyResult(
                ok=False,
                dry_run=dry_run,
                plan=None,
                step_results={},
                output_dir=str(output_dir),
                error=error,
                events=events,
                duration_ms=0,
                timings=[],
                run_id=run_id,
                outcome=_write_summary(error, False),
            )
        if process_exists and not request.known_process_exists:
            unlisted.append(("process", request.known_process_exists))
        if project_exists and not request.known_project_exists:
            unlisted.append(("project", request.known_project_exists))
    plan = build_dry_run_plan(
        ir,
        update_policy=request.update_policy,
        confirm_process_update=request.confirm_process_update,
        confirm_project_update=request.confirm_project_update,
        known_process_exists=process_exists,
        known_project_exists=project_exists,
        step_filter=step_filter,
    )
    if not plan.ok and unlisted:
        plural = {"process": "processes", "project": "projects"}
        reasons = [
            f"Azure DevOps already has this {target}, but "
            + (
                f"the browser hadn't loaded its list of existing {plural[target]}."
                if known is None
                else f"it wasn't in the browser's list of existing {plural[target]} (the list was out of date)."
            )
            for target, known in unlisted
        ]
        buttons = " / ".join(f"Fetch existing {plural[target]}" for target, _known in unlisted)
        plan.errors.append(
            " ".join(reasons)
            + f" Click {buttons} in the Connection section so the confirm "
            + ("box appears" if len(unlisted) == 1 else "boxes appear")
            + ", or change the existing target policy."
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

    if output_dir.name != default_folder_name:
        _emit(
            {
                "type": "info",
                "message": (
                    f"Results folder '{default_folder_name}' belongs to another project "
                    f"with a similar name; this project's results go to '{output_dir.name}'."
                ),
            }
        )

    process_id: str | None = None

    planned = {step["id"]: step for step in plan.steps}
    selected = step_filter or STEP_ORDER
    catalog_runs = "catalog" in selected and (planned.get("catalog") or {}).get("planned_action") not in {
        None,
        "skip",
    }

    _emit({"type": "apply-started", "message": f"Starting {'dry-run apply' if dry_run else 'apply'}"})
    template_notice = project_name_notice(
        request.project_name,
        template_rows=int((ir.get("project") or {}).get("project_placeholders_replaced") or 0),
        catalog_values=0,
    )
    if template_notice:
        _emit({"type": "info", "message": template_notice})

    try:
        # Before any step, so a full run doesn't set everything up and then stop at Catalog Import.
        output_dir = settle_output_dir(
            output_dir,
            client or change_reader,
            org_url,
            request.project_name,
            root=request.output_root,
            catalog_runs=catalog_runs,
            emit=lambda message: _emit({"type": "info", "message": message}),
        )

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
                    client,
                    ir,
                    dry_run=dry_run,
                    emit=step_emit,
                    process_id=process_id,
                    workers=int(getattr(request, "catalog_parallel_workers", 4) or 4),
                    process_changes=(planned.get("process") or {}).get("planned_action") != "skip",
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
                    include_deprecated_deleted=bool(request.include_deprecated_deleted),
                    parallel_workers=int(
                        getattr(request, "catalog_parallel_workers", 4) or 4
                    ),
                    progress=catalog_progress,
                    should_cancel=cancel_requested,
                    run_id=run_id,
                    area_root=request.root_area_path or request.project_name,
                    change_reader=change_reader,
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
