"""Run outcome headline/attention and the always-written summary report."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.run_outcome import build_outcome
from app.writers.report import write_run_summary


def _ir() -> dict:
    return {
        "targets": {"process_name": "Proc", "project_name": "Proj"},
        "source": {"fingerprint": "sha256:abc"},
        "counts": {"catalog_rows": 10},
    }


def _catalog_with_failures() -> dict:
    return {
        "drafts": 10, "created": 7, "skipped": 0, "failed": 3, "missing_parent": 2,
        "failure_summary": {
            "total": 3, "rootCauses": 1, "blockedByParent": 2,
            "groups": [{"category": "area_path", "label": "Area path does not exist in the project",
                        "fix": "Add it.", "count": 1, "blockedChildren": 2,
                        "examples": [{"key": "k", "sourceFile": "bpc.xlsx", "sourceRow": 5,
                                      "problem": "Area path 'X' does not exist in the project."}]}],
        },
        "prevalidate": {"needsReview": [], "automaticFixes": [], "needsReviewTotal": 0},
    }


def test_outcome_explains_catalog_failures() -> None:
    outcome = build_outcome({"catalog": _catalog_with_failures()}, dry_run=False, output_dir=None)
    assert outcome["status"] == "attention"
    assert outcome["headline"] == "Finished with problems: 7 of 10 catalog items imported"
    assert "1 row needs fixing; it blocked 2 more" in outcome["subline"]
    item = outcome["attention"][0]
    assert item["severity"] == "error" and item["file"] == "import-failures.csv"
    assert "2 child rows" in item["detail"]
    assert item["examples"] == ["bpc.xlsx row 5 (k) — Area path 'X' does not exist in the project."]


def test_outcome_headline_says_when_catalog_problems_are_from_earlier_run() -> None:
    outcome = build_outcome(
        {"teams": {"teams": 2}, "catalog": _catalog_with_failures()},
        dry_run=False,
        output_dir=None,
        earlier_steps={"catalog": "2026-10-14T09:30:00+00:00"},
    )
    assert outcome["headline"] == "Finished — problems from an earlier Catalog Import are still open"
    assert "1 row from the Catalog Import on 2026-10-14 09:30 still needs fixing" in outcome["subline"]


def test_summary_headline_for_catalog_rerun_vs_other_steps(tmp_path) -> None:
    def run(step_results: dict, run_id: str) -> dict:
        return write_run_summary(
            _ir(), step_results=step_results, output_dir=tmp_path,
            org_url="https://dev.azure.com/o", dry_run=False, run_id=run_id,
        )

    run({"catalog": _catalog_with_failures()}, "run1")
    # Catalog Import ran again and still failed: this run's problems, not earlier ones.
    rerun = run({"catalog": _catalog_with_failures()}, "run2")
    assert rerun["headline"] == "Finished with problems: 7 of 10 catalog items imported"
    # Only Teams ran: the open catalog failures come from the earlier run.
    teams_only = run({"teams": {"teams": 2}}, "run3")
    assert teams_only["headline"] == "Finished — problems from an earlier Catalog Import are still open"


def test_outcome_success_and_rehearsal() -> None:
    clean = {"drafts": 4, "created": 4, "skipped": 0, "failed": 0}
    assert build_outcome({"catalog": clean}, dry_run=False, output_dir=None)["status"] == "success"
    rehearsal = build_outcome({"catalog": clean}, dry_run=True, output_dir=None)
    assert rehearsal["status"] == "rehearsal"
    assert rehearsal["steps"][0]["status"] == "rehearsed"


def test_summary_keeps_earlier_steps_and_lists_files(tmp_path) -> None:
    write_run_summary(
        _ir(), step_results={"process": {"wits_created": 3}}, output_dir=tmp_path,
        org_url="https://dev.azure.com/o", dry_run=False, run_id="run1",
    )
    outcome = write_run_summary(
        _ir(), step_results={"catalog": _catalog_with_failures()}, output_dir=tmp_path,
        org_url="https://dev.azure.com/o", dry_run=False, run_id="run2",
    )
    data = json.loads((tmp_path / "bpc-ado-setup-summary.json").read_text())
    assert data["runId"] == "run2"
    assert data["stepResults"]["process"]["runId"] == "run1"
    assert data["stepResults"]["catalog"]["runId"] == "run2"
    process_step = next(step for step in outcome["steps"] if step["id"] == "process")
    assert process_step["earlierRun"]
    html = (tmp_path / "bpc-ado-setup-summary.html").read_text()
    assert "Finished with problems" in html and "What needs attention" in html
    assert {f["name"] for f in outcome["files"]} >= {"bpc-ado-setup-summary.html"}


def test_project_name_substitution_is_shown_in_outcome_and_html(tmp_path) -> None:
    from app.run_outcome import project_name_notice

    assert project_name_notice("Contoso", template_rows=0, catalog_values=0) == ""
    ir = _ir()
    ir["project"] = {"project_placeholders_replaced": 4}
    catalog = {
        "drafts": 2,
        "created": 2,
        "prevalidate": {
            "automaticFixes": [{"kind": "project_placeholder_replaced", "label": "x", "count": 30}]
        },
    }
    outcome = write_run_summary(
        ir, step_results={"catalog": catalog}, output_dir=tmp_path, org_url="o", dry_run=True, run_id="r"
    )
    assert outcome["notices"] == [
        "Project name applied: 'Your Project Name Here' → '"
        + ir["targets"]["project_name"]
        + "' in 4 template area/iteration rows and 30 catalog Area/Iteration Path values."
    ]
    html_text = (tmp_path / "rehearsal-summary.html").read_text(encoding="utf-8")
    assert 'class="notice"' in html_text and "Your Project Name Here" in html_text


def test_rehearsal_writes_separate_summary(tmp_path) -> None:
    write_run_summary(
        _ir(), step_results={}, output_dir=tmp_path, org_url="o", dry_run=True, run_id="r"
    )
    assert (tmp_path / "rehearsal-summary.html").is_file()
    assert not (tmp_path / "bpc-ado-setup-summary.html").exists()


def test_outputs_endpoint_serves_known_files_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BPCTOOL_OUTPUT_DIR", str(tmp_path))
    from app.main import output_file

    folder = tmp_path / "org_Proj"
    folder.mkdir()
    (folder / "import-failures.csv").write_text("Status\n", encoding="utf-8")
    (folder / "secret.txt").write_text("x", encoding="utf-8")
    response = output_file("org_Proj", "import-failures.csv")
    assert str(response.path) == str((folder / "import-failures.csv").resolve())
    assert "attachment" in response.headers["content-disposition"]
    for folder_name, name in [
        ("org_Proj", "secret.txt"),
        ("../etc", "import-failures.csv"),
        ("..", "import-failures.csv"),
        ("org_Proj", "import-prevalidate.csv"),
    ]:
        with pytest.raises(HTTPException):
            output_file(folder_name, name)


def test_outputs_endpoint_serves_from_user_selected_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BPCTOOL_OUTPUT_DIR", str(tmp_path / "default"))
    from app.main import output_file

    chosen = tmp_path / "chosen"
    folder = chosen / "org_Proj"
    folder.mkdir(parents=True)
    (folder / "import-failures.csv").write_text("Status\n", encoding="utf-8")
    (folder / "bpc-ado-setup-summary.html").write_text(
        '<a href="import-failures.csv">x</a> <a href="https://example.com/">y</a>', encoding="utf-8"
    )
    response = output_file("org_Proj", "import-failures.csv", root=str(chosen))
    assert str(response.path) == str((folder / "import-failures.csv").resolve())
    page = output_file("org_Proj", "bpc-ado-setup-summary.html", root=str(chosen)).body.decode()
    assert f'href="import-failures.csv?root={chosen}"' in page
    assert 'href="https://example.com/"' in page
    with pytest.raises(HTTPException):
        output_file("org_Proj", "bpc-ado-setup-summary.html", root=None)
    with pytest.raises(HTTPException):
        output_file("org_Proj", "bpc-ado-setup-summary.html", root="relative")


def test_rehearsal_run_end_to_end_writes_summary(template_path, tmp_path) -> None:
    from app.apply_engine import run_apply
    from app.models import DryRunRequest

    request = DryRunRequest(
        org_url="https://dev.azure.com/contoso",
        process_name="Business Process Catalog",
        project_name="Contoso-BPC",
        excel_file=str(template_path),
        output_root=str(tmp_path),
    )
    result = run_apply(request, pat="", dry_run=True, step_filter=["process", "report"])
    assert result.ok, result.error
    assert result.output_dir == str(tmp_path / "contoso_Contoso-BPC")
    assert (tmp_path / "contoso_Contoso-BPC" / "rehearsal-summary.html").is_file()
    assert result.outcome and result.outcome["status"] == "rehearsal"


def test_skip_existing_run_tells_backlog_to_leave_the_process_alone(
    template_path, tmp_path, monkeypatch
) -> None:
    from app import apply_engine
    from app.models import DryRunRequest

    seen: dict[str, bool] = {}

    def fake_backlog(_client, _ir, *, process_changes=True, **_kwargs):
        seen["process_changes"] = process_changes
        return {"warnings": 0}

    monkeypatch.setattr(apply_engine, "apply_backlog", fake_backlog)
    request = DryRunRequest(
        org_url="https://dev.azure.com/contoso",
        process_name="Business Process Catalog",
        project_name="Contoso-BPC",
        excel_file=str(template_path),
        output_root=str(tmp_path),
        update_policy="skip-existing",
        known_process_exists=True,
    )
    apply_engine.run_apply(request, pat="", dry_run=True, step_filter=["backlog"])
    assert seen == {"process_changes": False}

    seen.clear()
    fresh = request.model_copy(update={"known_process_exists": False})
    apply_engine.run_apply(fresh, pat="", dry_run=True, step_filter=["backlog"])
    assert seen == {"process_changes": True}


def test_live_run_checks_ado_for_existing_targets_without_inventory(
    template_path, tmp_path, monkeypatch
) -> None:
    from app import apply_engine
    from app.models import DryRunRequest

    class ExistingTargets:
        def __init__(self, *_args) -> None:
            pass

        def get_process_id(self, _name: str) -> str:
            return "proc-guid"

        def get_project_id(self, _name: str) -> None:
            return None

    monkeypatch.setattr(apply_engine, "AdoClient", ExistingTargets)
    request = DryRunRequest(
        org_url="https://dev.azure.com/contoso",
        process_name="Business Process Catalog",
        project_name="Contoso-BPC",
        excel_file=str(template_path),
        output_root=str(tmp_path),
        update_policy="create-only",
    )
    result = apply_engine.run_apply(request, pat="x", dry_run=False, step_filter=["process"])
    assert not result.ok
    assert 'Process "Business Process Catalog" already exists and policy is create-only' in result.error
    assert "the browser hadn't loaded its list of existing processes" in result.error
    assert "Click Fetch existing processes in the Connection section so the confirm box appears" in result.error

    stale = request.model_copy(update={"known_process_exists": False})
    result = apply_engine.run_apply(stale, pat="x", dry_run=False, step_filter=["process"])
    assert "wasn't in the browser's list of existing processes (the list was out of date)" in result.error

    preview = apply_engine.build_dry_run_plan(
        apply_engine.build_ir(str(template_path), process_name="P1", project_name="Proj1"),
        update_policy="create-only",
        confirm_process_update=False,
        confirm_project_update=False,
        known_process_exists=None,
        known_project_exists=False,
        step_filter=["process", "project"],
    )
    assert any("Not known whether the process already exists" in w for w in preview.warnings)


def test_live_run_writes_summary_when_ado_check_fails(template_path, tmp_path, monkeypatch) -> None:
    from app import apply_engine
    from app.ado_client import AdoError
    from app.models import DryRunRequest

    class ExpiredPat:
        def __init__(self, *_args) -> None:
            pass

        def get_process_id(self, _name: str) -> str:
            raise AdoError("Azure DevOps returned a sign-in page (HTTP 203)", status=401)

    monkeypatch.setattr(apply_engine, "AdoClient", ExpiredPat)
    request = DryRunRequest(
        org_url="https://dev.azure.com/contoso",
        process_name="Business Process Catalog",
        project_name="Contoso-BPC",
        excel_file=str(template_path),
        output_root=str(tmp_path),
    )
    events: list[dict] = []
    result = apply_engine.run_apply(request, pat="x", dry_run=False, step_filter=["process"], emit=events.append)
    assert not result.ok
    assert result.error.startswith("Could not check the process and project in Azure DevOps before the run")
    assert "sign-in page" in result.error
    assert result.outcome and result.outcome["status"] == "failed"
    assert (tmp_path / "contoso_Contoso-BPC" / "bpc-ado-setup-summary.html").is_file()
    assert any(event["type"] == "job-error" for event in events)


def test_cancel_after_the_last_step_still_counts_as_finished(template_path, tmp_path) -> None:
    from app.apply_engine import run_apply
    from app.models import DryRunRequest

    request = DryRunRequest(
        org_url="https://dev.azure.com/contoso",
        process_name="Business Process Catalog",
        project_name="Contoso-BPC",
        excel_file=str(template_path),
        output_root=str(tmp_path),
    )
    steps_done: list[str] = []

    def cancel_once_report_finished() -> bool:
        return "report" in steps_done

    result = run_apply(
        request,
        pat="",
        dry_run=True,
        step_filter=["report"],
        should_cancel=cancel_once_report_finished,
        emit=lambda event: event["type"] == "step-completed" and steps_done.append(event["stepId"]),
    )
    assert result.ok and not result.cancelled, result.error
