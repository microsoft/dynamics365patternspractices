"""The Process step fails when something the workbook defines can't be created."""

from __future__ import annotations

from typing import Any

import pytest

from app.ado_client import AdoError
from app.run_outcome import describe_step
from app.writers.process import ProcessSetupError, apply_process


def _ir() -> dict[str, Any]:
    return {
        "targets": {"process_name": "Contoso BPC"},
        "counts": {"work_item_types": 1, "fields": 1, "html_fields": 0},
        "process": {
            "work_item_types": [
                {"name": "Business Process", "custom": True, "reference_name": "ContosoBPC.BusinessProcess"},
            ],
            "picklists": {"Industry": ["Retail", "Finance"]},
            "fields": [
                {
                    "custom_field": True,
                    "reference_name": "Custom.Industry",
                    "field_type": "PicklistString",
                    "label": "Industry",
                    "field_name": "Industry",
                },
            ],
        },
    }


class FakeClient:
    def __init__(self, *, fail: dict[str, AdoError] | None = None, fields: list[str] | None = None) -> None:
        self.fail = fail or {}
        self.fields = fields or []
        self.lists: list[dict[str, Any]] = []

    def create_process(self, _name: str) -> str:
        return "proc-1"

    def list_process_wits(self, _process_id: str) -> list[dict[str, Any]]:
        return []

    def get(self, path: str, **_kw: Any) -> dict[str, Any]:
        if path.endswith("/lists"):
            return {"value": self.lists}
        if path.endswith("/wit/fields"):
            return {"value": [{"referenceName": ref} for ref in self.fields]}
        return {}

    def _maybe_fail(self, method: str, path: str) -> None:
        for key, exc in self.fail.items():
            if key == f"{method} {path.split('/_apis/')[-1].split('/')[-1]}":
                raise exc

    def post(self, path: str, *, json_body: dict[str, Any], **_kw: Any) -> dict[str, Any]:
        self._maybe_fail("POST", path)
        if path.endswith("/lists"):
            self.lists.append({"name": json_body["name"], "id": "list-1"})
        return {"name": json_body.get("name"), "referenceName": json_body.get("referenceName")}

    def patch(self, path: str, **_kw: Any) -> dict[str, Any]:
        self._maybe_fail("PATCH", path)
        return {}

    def put(self, path: str, **_kw: Any) -> dict[str, Any]:
        self._maybe_fail("PUT", path)
        return {}


def _run(client: FakeClient, ir: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    messages: list[str] = []
    result = apply_process(client, ir, dry_run=False, emit=lambda _step, msg: messages.append(msg))
    return result, messages


def test_everything_created_is_ok() -> None:
    result, _ = _run(FakeClient(), _ir())
    assert result["wits_created"] == 1 and result["picklists"] == 1 and result["fields_created"] == 1
    assert describe_step("process", result, dry_run=False)[0] == "ok"


def test_a_work_item_type_that_cannot_be_created_fails_the_step() -> None:
    client = FakeClient(fail={"POST workItemTypes": AdoError("403 Forbidden: insufficient permissions", status=403)})
    with pytest.raises(ProcessSetupError) as caught:
        _run(client, _ir())
    message = str(caught.value)
    assert "1 work item type(s) / picklist(s) / field(s)" in message
    assert "Business Process" in message and "403" in message


def test_a_field_that_cannot_be_created_fails_the_step_after_trying_the_rest() -> None:
    client = FakeClient(fail={"POST fields": AdoError("400 Bad Request", status=400)})
    messages: list[str] = []
    with pytest.raises(ProcessSetupError):
        apply_process(client, _ir(), dry_run=False, emit=lambda _s, m: messages.append(m))
    assert any(m.startswith("FAILED: Field 'Custom.Industry'") for m in messages)
    assert any(m.startswith("Process apply finished") for m in messages)


def test_already_existing_items_are_not_failures() -> None:
    client = FakeClient(fail={"POST workItemTypes": AdoError("409 Conflict", status=409)})
    result, _ = _run(client, _ir())
    assert result["wits_skipped"] == 1


def test_an_existing_field_is_used_as_is_without_warnings() -> None:
    client = FakeClient(
        fields=["Custom.Industry"],
        fail={"PATCH Custom.Industry": AdoError("404 Not Found", status=404)},
    )
    result, _ = _run(client, _ir())
    assert result["fields_existing"] == 1 and result["fields_created"] == 0
    assert result["warnings"] == 0
    status, text = describe_step("process", result, dry_run=False)
    assert status == "ok" and "(1 already existed)" in text


def test_a_picklist_that_cannot_be_created_is_reported_once() -> None:
    client = FakeClient(fail={"POST lists": AdoError("403 Forbidden", status=403)})
    with pytest.raises(ProcessSetupError) as caught:
        _run(client, _ir())
    assert "1 work item type(s) / picklist(s) / field(s)" in str(caught.value)
    assert "Picklist 'Industry'" in str(caught.value)


def test_update_failures_are_warnings() -> None:
    client = FakeClient(fail={"PUT list-1": AdoError("400 Bad Request", status=400)})
    client.lists.append({"name": "Industry", "id": "list-1"})
    result, messages = _run(client, _ir())
    assert result["warnings"] == 1
    assert any(m.startswith("WARNING: Picklist 'Industry' exists") for m in messages)
    status, text = describe_step("process", result, dry_run=False)
    assert status == "warning" and "1 warning" in text
