"""In-memory job store for dry-run and apply jobs."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .apply_engine import run_apply
from .excel_ir import build_ir
from .models import (
    ApplyResult,
    DryRunRequest,
    DryRunResponse,
    JobCreateRequest,
    JobStatusResponse,
)
from .catalog_import import load_catalog_drafts, split_retired_drafts
from .catalog_validate import prevalidate_catalog_drafts, prevalidate_summary
from .mapping import build_mapping_from_ir
from .org_url import normalize_ado_org_url
from .output_folder import folder_lock_key
from .planner import build_dry_run_plan
from .run_outcome import catalog_placeholder_count, project_name_notice
from .timing import format_duration_ms

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
# One apply per org/project at a time: two concurrent runs would create duplicate
# work items (both miss each other's ado-id-map.csv rows) and overwrite reports.
_active_apply_keys: dict[str, str] = {}
# Finished jobs kept for polling; older ones (with their event logs) are dropped.
MAX_FINISHED_JOBS = 20


class ApplyInProgressError(RuntimeError):
    """An apply is already running for the same organization and project."""


def _apply_key(request: JobCreateRequest) -> str:
    # Keyed on the results folder name, not the project name: "Finance Team" and
    # "Finance_Team" share a folder name until the first run records its owner.
    try:
        org_url = normalize_ado_org_url(request.org_url)
    except ValueError:
        org_url = (request.org_url or "").strip()
    return folder_lock_key(org_url, request.project_name)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_dry_run(request: DryRunRequest) -> DryRunResponse:
    ir = build_ir(
        request.excel_file,
        catalog_source_dir=request.catalog_source_dir,
        workbook_version=request.workbook_version,
        process_name=request.process_name,
        project_name=request.project_name,
    )
    plan = build_dry_run_plan(
        ir,
        update_policy=request.update_policy,
        confirm_process_update=request.confirm_process_update,
        confirm_project_update=request.confirm_project_update,
        known_process_exists=request.known_process_exists,
        known_project_exists=request.known_project_exists,
        step_filter=request.steps,
    )
    if (not request.steps or "catalog" in request.steps) and ir["counts"].get("catalog_rows"):
        plan.data_checks = catalog_data_checks(
            ir,
            area_root=request.root_area_path or request.project_name,
            include_deprecated_deleted=request.include_deprecated_deleted,
        )
        retired = int(plan.data_checks.get("retiredSkipped") or 0)
        if retired:
            plan.notices.append(
                f"{retired:,} Deprecated / Deleted catalog row(s) (or rows below them) will be skipped — "
                "tick “Import Deprecated / Deleted rows” to include them."
            )
    notice = project_name_notice(
        request.project_name,
        template_rows=int((ir.get("project") or {}).get("project_placeholders_replaced") or 0),
        catalog_values=catalog_placeholder_count(plan.data_checks),
    )
    if notice:
        plan.notices.append(notice)
    return plan


def catalog_data_checks(
    ir: dict[str, Any], *, area_root: str = "", include_deprecated_deleted: bool = False
) -> dict[str, Any]:
    """Offline catalog checks (no Azure DevOps calls); project areas and States need a run."""
    mapping = build_mapping_from_ir(ir)
    drafts = load_catalog_drafts(ir["source"].get("catalog_source_dir"), mapping)
    retired = []
    if not include_deprecated_deleted:
        drafts, retired = split_retired_drafts(drafts)
    result = prevalidate_catalog_drafts(drafts, ir, mapping, sanitize=True, area_root=area_root)
    return {**prevalidate_summary(result, examples=3), "retiredSkipped": len(retired)}


def create_job(request: JobCreateRequest) -> JobStatusResponse:
    if request.mode == "apply" and not (request.pat or "").strip():
        raise ValueError("PAT is required for apply mode.")

    job_id = uuid.uuid4().hex[:12]
    apply_key = _apply_key(request) if request.mode == "apply" else None
    created = _now()
    record = {
        "id": job_id,
        "status": "queued",
        "mode": request.mode,
        "created_at": created,
        "updated_at": created,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "result": None,
        "apply_result": None,
        "error": None,
        "events": [
            {
                "timestamp": created,
                "type": "job-created",
                "message": f"Job created in {request.mode} mode",
            }
        ],
        "request": request,
        "cancel_event": threading.Event(),
        "apply_key": apply_key,
    }
    with _lock:
        if apply_key is not None:
            running = _active_apply_keys.get(apply_key)
            if running is not None:
                raise ApplyInProgressError(
                    "A run is already in progress for this organization and project, or a project "
                    f"whose results folder has the same name (job {running}). "
                    "Wait for it to finish, or cancel it, before starting another — two runs at once "
                    "would create duplicate work items and overwrite each other's reports."
                )
            _active_apply_keys[apply_key] = job_id
        _prune_finished_jobs()
        _jobs[job_id] = record

    if request.mode == "dry-run":
        _execute_job(job_id)
        return get_job(job_id)

    # Apply runs in a background thread so the API can return immediately for polling.
    thread = threading.Thread(target=_execute_job, args=(job_id,), daemon=True)
    thread.start()
    return get_job(job_id)


def _prune_finished_jobs() -> None:
    """Drop the oldest finished jobs beyond MAX_FINISHED_JOBS. Caller holds ``_lock``."""
    finished = [
        job_id for job_id, job in _jobs.items() if job["status"] not in {"queued", "running"}
    ]
    for job_id in finished[: max(0, len(finished) - MAX_FINISHED_JOBS + 1)]:
        del _jobs[job_id]


def _forget_pat(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job and job["request"].pat:
            job["request"] = job["request"].model_copy(update={"pat": None})


def _release_apply_key(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        apply_key = job.get("apply_key") if job else None
        if apply_key is not None and _active_apply_keys.get(apply_key) == job_id:
            del _active_apply_keys[apply_key]


def active_job_count() -> int:
    """Jobs queued or running (reported by /health so launchers don't stop a live run)."""
    with _lock:
        return sum(1 for job in _jobs.values() if job["status"] in {"queued", "running"})


def _append_event(job_id: str, event: dict[str, Any]) -> None:
    with _lock:
        job = _jobs[job_id]
        payload = {"timestamp": _now(), **event}
        job["events"].append(payload)
        job["updated_at"] = payload["timestamp"]


def cancel_job(job_id: str) -> JobStatusResponse:
    """Request cancellation; the apply stops at its next safe checkpoint."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        active = job["status"] in {"queued", "running"}
        already = job["cancel_event"].is_set()
    if active and not already:
        job["cancel_event"].set()
        _append_event(
            job_id,
            {
                "type": "cancel-requested",
                "message": "Cancel requested — stopping after in-flight requests finish",
            },
        )
    return get_job(job_id)


def _execute_job(job_id: str) -> None:
    job_t0 = time.perf_counter()
    with _lock:
        job = _jobs[job_id]
        request: JobCreateRequest = job["request"]
        cancel_event: threading.Event = job["cancel_event"]
        started = _now()
        job["status"] = "running"
        job["started_at"] = started
        job["updated_at"] = started
        job["events"].append(
            {
                "timestamp": started,
                "type": "job-started",
                "message": "Parsing Excel and building plan",
            }
        )

    try:
        if request.mode == "dry-run":
            result = run_dry_run(request)
            finished = _now()
            duration_ms = int((time.perf_counter() - job_t0) * 1000)
            with _lock:
                job = _jobs[job_id]
                job["result"] = result
                job["status"] = "succeeded" if result.ok else "failed"
                job["error"] = None if result.ok else "; ".join(result.errors)
                job["finished_at"] = finished
                job["duration_ms"] = duration_ms
                job["updated_at"] = finished
                job["events"].append(
                    {
                        "timestamp": finished,
                        "type": "job-finished",
                        "durationMs": duration_ms,
                        "message": (
                            f"Dry-run plan ready ({format_duration_ms(duration_ms)})"
                            if result.ok
                            else f"Dry-run blocked after {format_duration_ms(duration_ms)}: {job['error']}"
                        ),
                    }
                )
            return

        def on_event(event: dict[str, Any]) -> None:
            _append_event(job_id, event)

        try:
            apply_result: ApplyResult = run_apply(
                request,
                pat=request.pat or "",
                dry_run=bool(request.apply_dry_run),
                emit=on_event,
                step_filter=request.steps,
                catalog_limit=request.catalog_limit,
                should_cancel=cancel_event.is_set,
                run_id=job_id,
            )
        finally:
            # Before the job reads as finished, so an immediate next run isn't refused.
            _release_apply_key(job_id)

        finished = _now()
        # Prefer apply-engine total (step wall time); fall back to job wall clock.
        duration_ms = apply_result.duration_ms
        if duration_ms is None:
            duration_ms = int((time.perf_counter() - job_t0) * 1000)

        with _lock:
            job = _jobs[job_id]
            # The job's own event list already holds every event; don't keep a second copy.
            job["apply_result"] = apply_result.model_copy(update={"events": []})
            job["result"] = apply_result.plan
            if apply_result.ok:
                status = "succeeded"
                message = (
                    f"{'Rehearsal' if apply_result.dry_run else 'Run'} finished "
                    f"({format_duration_ms(duration_ms)})"
                )
            elif apply_result.cancelled:
                status = "cancelled"
                message = f"Apply cancelled after {format_duration_ms(duration_ms)}"
            else:
                status = "failed"
                message = (
                    f"Apply failed after {format_duration_ms(duration_ms)}: {apply_result.error}"
                )
            job["status"] = status
            job["error"] = apply_result.error
            job["finished_at"] = finished
            job["duration_ms"] = duration_ms
            job["updated_at"] = finished
            job["events"].append(
                {
                    "timestamp": finished,
                    "type": "job-finished",
                    "durationMs": duration_ms,
                    "timings": apply_result.timings,
                    "message": message,
                }
            )
    except Exception as exc:  # noqa: BLE001 - surface to job status
        finished = _now()
        duration_ms = int((time.perf_counter() - job_t0) * 1000)
        with _lock:
            job = _jobs[job_id]
            job["status"] = "failed"
            job["error"] = str(exc)
            job["finished_at"] = finished
            job["duration_ms"] = duration_ms
            job["updated_at"] = finished
            job["events"].append(
                {
                    "timestamp": finished,
                    "type": "job-error",
                    "durationMs": duration_ms,
                    "message": f"{exc} (after {format_duration_ms(duration_ms)})",
                }
            )
    finally:
        _forget_pat(job_id)


def get_job(job_id: str, *, since: int = 0) -> JobStatusResponse:
    """Return job status with events from index ``since`` (incremental polling)."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        events = job["events"]
        offset = max(0, min(int(since or 0), len(events)))
        apply_result = job["apply_result"]
        return JobStatusResponse(
            id=job["id"],
            status=job["status"],
            mode=job["mode"],
            cancel_requested=job["cancel_event"].is_set(),
            created_at=job["created_at"],
            updated_at=job["updated_at"],
            started_at=job.get("started_at"),
            finished_at=job.get("finished_at"),
            duration_ms=job.get("duration_ms"),
            result=job["result"],
            apply_result=apply_result,
            error=job["error"],
            events=list(events[offset:]),
            event_offset=offset,
            event_total=len(events),
        )
