"""Existing-target policy gates and step selection validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.excel_ir import build_ir
from app.models import DryRunRequest, JobCreateRequest
from app.planner import build_dry_run_plan


@pytest.fixture
def ir(template_path):
    return build_ir(str(template_path), process_name="BPC Process", project_name="BPC Project")


def _plan(ir, policy: str, steps: list[str], **confirm: bool):
    return build_dry_run_plan(
        ir,
        update_policy=policy,
        confirm_process_update=confirm.get("process", False),
        confirm_project_update=confirm.get("project", False),
        known_process_exists=True,
        known_project_exists=False,
        step_filter=steps,
    )


def test_backlog_only_run_needs_process_confirmation(ir) -> None:
    blocked = _plan(ir, "require-confirmation", ["backlog"])
    assert any('Process "BPC Process" already exists' in error for error in blocked.errors)
    assert _plan(ir, "require-confirmation", ["backlog"], process=True).ok


def test_backlog_only_run_is_refused_by_create_only(ir) -> None:
    plan = _plan(ir, "create-only", ["backlog"])
    assert any("already exists and policy is create-only" in error for error in plan.errors)


def test_skip_existing_keeps_backlog_for_the_new_project_only(ir) -> None:
    plan = _plan(ir, "skip-existing", ["process", "layout", "project", "teams", "backlog"])
    steps = {step["id"]: step for step in plan.steps}
    assert plan.ok
    assert steps["process"]["planned_action"] == "skip"
    assert steps["backlog"]["planned_action"] == "update"
    assert "backlog levels are left as they are" in steps["backlog"]["summary"]


def test_teams_only_run_does_not_need_process_confirmation(ir) -> None:
    assert _plan(ir, "require-confirmation", ["teams"]).ok


def _request(steps):
    return {
        "org_url": "https://dev.azure.com/contoso",
        "process_name": "BPC Process",
        "project_name": "BPC Project",
        "excel_file": "/tmp/template.xlsx",
        "steps": steps,
    }


@pytest.mark.parametrize("model", [DryRunRequest, JobCreateRequest])
def test_steps_must_be_known_and_non_empty(model) -> None:
    with pytest.raises(ValidationError, match="at least one step"):
        model(**_request([]))
    with pytest.raises(ValidationError, match="Unknown step\\(s\\): backlogg"):
        model(**_request(["backlogg"]))
    assert model(**_request(None)).steps is None


def test_steps_are_normalized_to_engine_order() -> None:
    request = DryRunRequest(**_request(["Catalog", "process", "catalog"]))
    assert request.steps == ["process", "catalog"]
