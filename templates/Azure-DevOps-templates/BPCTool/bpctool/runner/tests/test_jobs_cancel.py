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


def test_second_apply_for_same_project_is_rejected_until_first_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = {"go": False}

    def fake_run_apply(request, **_kwargs):
        _wait_for(lambda: release["go"])
        return ApplyResult(ok=True, dry_run=False)

    monkeypatch.setattr(jobs, "run_apply", fake_run_apply)
    first = jobs.create_job(_request())
    same_project = _request().model_copy(
        update={"org_url": "https://dev.azure.com/Contoso/", "project_name": "demo project"}
    )
    with pytest.raises(jobs.ApplyInProgressError, match=first.id):
        jobs.create_job(same_project)
    other = jobs.create_job(_request().model_copy(update={"project_name": "Other Project"}))
    assert jobs.active_job_count() == 2

    release["go"] = True
    _wait_for(lambda: jobs.get_job(first.id).status == "succeeded")
    _wait_for(lambda: jobs.get_job(other.id).status == "succeeded")
    again = jobs.create_job(same_project)
    _wait_for(lambda: jobs.get_job(again.id).status == "succeeded")


def test_crashed_apply_releases_its_slot_once(monkeypatch: pytest.MonkeyPatch) -> None:
    def crash(request, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(jobs, "run_apply", crash)
    failed = jobs.create_job(_request())
    _wait_for(lambda: jobs.get_job(failed.id).status == "failed")
    assert jobs.get_job(failed.id).error == "boom"

    release = {"go": False}
    monkeypatch.setattr(
        jobs,
        "run_apply",
        lambda request, **_kwargs: _wait_for(lambda: release["go"]) or ApplyResult(ok=True, dry_run=False),
    )
    running = jobs.create_job(_request())
    jobs._release_apply_key(failed.id)
    with pytest.raises(jobs.ApplyInProgressError):
        jobs.create_job(_request())
    release["go"] = True
    _wait_for(lambda: jobs.get_job(running.id).status == "succeeded")


def test_finished_job_forgets_the_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_run_apply(request, *, pat, **_kwargs):
        seen.append(pat)
        return ApplyResult(ok=True, dry_run=False)

    monkeypatch.setattr(jobs, "run_apply", fake_run_apply)
    job = jobs.create_job(_request())
    _wait_for(lambda: jobs.get_job(job.id).status == "succeeded")
    _wait_for(lambda: jobs._jobs[job.id]["request"].pat is None)
    assert seen == ["x" * 52]


def test_finished_job_keeps_one_copy_of_its_events(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_apply(request, *, emit, **_kwargs):
        emit({"type": "step-progress", "stepId": "process", "message": "m"})
        return ApplyResult(ok=True, dry_run=False, events=[{"type": "step-progress"}])

    monkeypatch.setattr(jobs, "run_apply", fake_run_apply)
    job = jobs.create_job(_request())
    _wait_for(lambda: jobs.get_job(job.id).status == "succeeded")
    full = jobs.get_job(job.id)
    assert full.apply_result is not None and full.apply_result.events == []
    assert any(event.get("message") == "m" for event in full.events)


def test_only_recent_finished_jobs_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        jobs, "run_apply", lambda request, **_kwargs: ApplyResult(ok=True, dry_run=False)
    )
    created = []
    for _ in range(jobs.MAX_FINISHED_JOBS + 5):
        job = jobs.create_job(_request())
        _wait_for(lambda job_id=job.id: jobs.get_job(job_id).status == "succeeded")
        created.append(job.id)

    with pytest.raises(KeyError):
        jobs.get_job(created[0])
    assert jobs.get_job(created[-1]).status == "succeeded"
    finished = [j for j in jobs._jobs.values() if j["status"] not in {"queued", "running"}]
    assert len(finished) <= jobs.MAX_FINISHED_JOBS


def test_cancel_finished_job_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        jobs, "run_apply", lambda request, **_kwargs: ApplyResult(ok=True, dry_run=False)
    )
    job = jobs.create_job(_request())
    _wait_for(lambda: jobs.get_job(job.id).status == "succeeded")
    result = jobs.cancel_job(job.id)
    assert result.status == "succeeded"
    assert result.cancel_requested is False
