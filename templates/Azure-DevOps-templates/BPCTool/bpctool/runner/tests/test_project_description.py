"""Project description from UI/request is applied on create and update."""

from __future__ import annotations

from typing import Any

import pytest

from app.ado_client import AdoError
from app.writers.project import apply_project


class FakeClient:
    def __init__(
        self, *, existing_id: str | None = None, existing_process: str = "proc-guid"
    ) -> None:
        self.existing_id = existing_id
        self.existing_process = existing_process
        self.created: dict[str, Any] | None = None
        self.updated: dict[str, Any] | None = None

    def get_process_id(self, _name: str) -> str:
        return "proc-guid"

    def get_project_id(self, _name: str) -> str | None:
        return self.existing_id

    def get_project_process_id(self, _project_id: str) -> str:
        return self.existing_process

    def list_processes(self) -> list[dict[str, Any]]:
        return [{"typeId": "proc-guid", "name": "MSBPCTemplate"}, {"typeId": "agile-guid", "name": "Agile"}]

    def create_project(
        self, project_name: str, process_id: str, *, description: str = ""
    ) -> str:
        self.created = {
            "name": project_name,
            "process_id": process_id,
            "description": description,
        }
        return "proj-new"

    def update_project_description(self, project_id: str, description: str) -> None:
        self.updated = {"project_id": project_id, "description": description}


def test_create_project_uses_user_description() -> None:
    client = FakeClient()
    events: list[str] = []
    ir = {
        "targets": {
            "project_name": "MSBPCProj",
            "process_name": "MSBPCTemplate",
            "project_description": "Microsoft Business Process Catalog project",
        }
    }
    stats = apply_project(client, ir, dry_run=False, emit=lambda _s, m: events.append(m))
    assert stats["created"] is True
    assert client.created is not None
    assert client.created["description"] == "Microsoft Business Process Catalog project"
    assert "Project for process" not in (client.created["description"] or "")
    assert any("description set" in m for m in events)


def test_create_project_empty_description_not_process_id() -> None:
    client = FakeClient()
    ir = {
        "targets": {
            "project_name": "MSBPCProj",
            "process_name": "MSBPCTemplate",
            "project_description": "",
        }
    }
    apply_project(client, ir, dry_run=False, emit=lambda _s, _m: None)
    assert client.created is not None
    assert client.created["description"] == ""


def test_existing_project_updates_description_when_provided() -> None:
    client = FakeClient(existing_id="proj-existing")
    events: list[str] = []
    ir = {
        "targets": {
            "project_name": "MSBPCProj",
            "process_name": "MSBPCTemplate",
            "project_description": "Updated overview text",
        }
    }
    stats = apply_project(client, ir, dry_run=False, emit=lambda _s, m: events.append(m))
    assert stats["existed"] is True
    assert stats["description_updated"] is True
    assert client.updated == {
        "project_id": "proj-existing",
        "description": "Updated overview text",
    }
    assert client.created is None


def test_failed_description_update_is_a_step_warning() -> None:
    from app.run_outcome import describe_step

    class DescriptionRefused(FakeClient):
        def update_project_description(self, project_id: str, description: str) -> None:
            raise AdoError("ADO 403 Forbidden: no permission", status=403)

    client = DescriptionRefused(existing_id="proj-existing")
    ir = {"targets": {"project_name": "MSBPCProj", "process_name": "MSBPCTemplate", "project_description": "New"}}
    stats = apply_project(client, ir, dry_run=False, emit=lambda _s, _m: None)
    assert stats["description_updated"] is False
    assert stats["warnings"] == 1
    status, text = describe_step("project", stats, dry_run=False)
    assert status == "warning"
    assert "description could not be updated: ADO 403 Forbidden" in text


def test_existing_project_on_another_process_is_rejected() -> None:
    client = FakeClient(existing_id="proj-existing", existing_process="AGILE-GUID")
    ir = {"targets": {"project_name": "MSBPCProj", "process_name": "MSBPCTemplate"}}
    with pytest.raises(AdoError, match='uses process "Agile", not "MSBPCTemplate"'):
        apply_project(client, ir, dry_run=False, emit=lambda _s, _m: None)
    assert client.updated is None
