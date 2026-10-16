"""Job cancel endpoint semantics and incremental event polling."""

from __future__ import annotations

import time

import pytest

from app import jobs
from app.models import ApplyResult, JobCreateRequest


def _request() -> JobCreateRequest:
    return JobCreateRequest(
        org_url="https://dev.azure.com/contoso",
        process_name="Demo Process",
        project_name="Demo Project",
        excel_file="/tmp/template.xlsx",
        mode="apply",
        pat="x" * 52,
    )


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def test_cancel_marks_job_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_apply(request, *, emit, should_cancel, **_kwargs):
        emit({"type": "step-started", "stepId": "catalog", "message": "go"})
        _wait_for(should_cancel)
        return ApplyResult(ok=False, dry_run=False, error="Run cancelled by user", cancelled=True)

    monkeypatch.setattr(jobs, "run_apply", fake_run_apply)
    job = jobs.create_job(_request())
    _wait_for(lambda: jobs.get_job(job.id).status == "running")

    after_cancel = jobs.cancel_job(job.id)
    assert after_cancel.cancel_requested is True
    _wait_for(lambda: jobs.get_job(job.id).status == "cancelled")

    final = jobs.get_job(job.id)
    types = [event["type"] for event in final.events]
    assert "cancel-requested" in types
    assert types[-1] == "job-finished"


def test_get_job_since_returns_only_new_events(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_apply(request, *, emit, **_kwargs):
        for index in range(3):
            emit({"type": "step-progress", "stepId": "process", "message": f"m{index}"})
        return ApplyResult(ok=True, dry_run=False, events=[{"type": "x"}] * 3)

    monkeypatch.setattr(jobs, "run_apply", fake_run_apply)
    job = jobs.create_job(_request())
    _wait_for(lambda: jobs.get_job(job.id).status == "succeeded")

    full = jobs.get_job(job.id)
    assert full.event_offset == 0
    assert full.event_total == len(full.events)

    tail = jobs.get_job(job.id, since=full.event_total - 1)
    assert len(tail.events) == 1
    assert tail.events[0]["type"] == "job-finished"
    assert tail.apply_result is not None and tail.apply_result.events == []

    beyond = jobs.get_job(job.id, since=full.event_total + 10)
    assert beyond.events == []
    assert beyond.event_offset == full.event_total


def test_cancel_finished_job_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        jobs, "run_apply", lambda request, **_kwargs: ApplyResult(ok=True, dry_run=False)
    )
    job = jobs.create_job(_request())
    _wait_for(lambda: jobs.get_job(job.id).status == "succeeded")
    result = jobs.cancel_job(job.id)
    assert result.status == "succeeded"
    assert result.cancel_requested is False
