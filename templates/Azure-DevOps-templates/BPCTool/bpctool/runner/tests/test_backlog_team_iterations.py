"""Team iteration assignment (reference Script 4 Part 4)."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from app.writers.backlog import (
    _collect_iteration_ids,
    _index_iteration_tree,
    _team_settings_payload,
    apply_backlog,
)


class FakeClient:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.patches: list[dict[str, Any]] = []
        self.tree = {
            "name": "MSBPCProj",
            "identifier": "root-guid",
            "children": [
                {
                    "name": "Phase 1 - Initiate",
                    "identifier": "phase1-guid",
                    "children": [
                        {"name": "Sprint 1", "identifier": "s1-guid", "children": []},
                    ],
                }
            ],
        }
        self.team_iters: dict[str, list[str]] = {}

    def get_process_id(self, _name: str) -> str:
        return "proc-1"

    def list_process_wits(self, _process_id: str) -> list[dict[str, Any]]:
        return []

    def get(self, path: str, **kwargs: Any) -> Any:
        project = kwargs.get("project") or ""
        if "behaviors" in path:
            return {"value": []}
        lowered = path.lower()
        if "classificationnodes/iterations" in lowered and (
            "$depth" in lowered or "%24depth" in lowered
        ):
            return self.tree
        if path == "/_apis/work/teamsettings":
            return {
                "bugsBehavior": "off",
                # Unset backlog iteration (matches ADO empty Backlog iteration UI).
                "backlogIteration": {"id": "00000000-0000-0000-0000-000000000000"},
                "defaultIterationMacro": "",
            }
        if path == "/_apis/work/teamsettings/iterations":
            return {"value": [{"id": x} for x in self.team_iters.get(project, [])]}
        if path == "/_apis/work/teamsettings/teamfieldvalues":
            return {
                "defaultValue": "MSBPCProj\\Business process catalog",
                "values": [
                    {
                        "value": "MSBPCProj\\Business process catalog",
                        "includeChildren": False,
                    }
                ],
            }
        return {}

    def post(self, path: str, **kwargs: Any) -> Any:
        self.posts.append({"path": path, "project": kwargs.get("project"), "body": kwargs.get("json_body")})
        if "classificationnodes" in path.lower():
            return {"ok": True}
        if path == "/_apis/work/teamsettings/iterations":
            project = kwargs.get("project") or ""
            self.team_iters.setdefault(project, []).append(kwargs["json_body"]["id"])
            return {"ok": True}
        return {"ok": True}

    def put(self, path: str, **kwargs: Any) -> Any:
        return {"ok": True}

    def delete(self, path: str, **kwargs: Any) -> Any:
        return None

    def patch(self, path: str, **kwargs: Any) -> Any:
        self.patches.append({"path": path, "project": kwargs.get("project"), "body": kwargs.get("json_body")})
        return {"ok": True}


class BacklogFakeClient(FakeClient):
    def get(self, path: str, **kwargs: Any) -> Any:
        lowered = path.lower()
        if "classificationnodes/iterations" in lowered and "$depth" not in lowered and "%24depth" not in lowered:
            from app.ado_client import AdoError

            raise AdoError("missing", status=404)
        return super().get(path, **kwargs)


def test_collect_iteration_ids() -> None:
    result: dict[str, str] = {}
    _collect_iteration_ids(
        {
            "name": "MSBPCProj",
            "identifier": "root",
            "children": [{"name": "Phase 1", "identifier": "p1", "children": []}],
        },
        "",
        result,
    )
    assert result["MSBPCProj"] == "root"
    assert result["MSBPCProj\\Phase 1"] == "p1"


def test_index_uses_tree_root_identifier_not_project_name_lookup() -> None:
    tree = {
        "name": "DifferentRootName",
        "identifier": "root-guid",
        "children": [{"name": "Phase 1", "identifier": "p1", "children": []}],
    }
    root_id, _map, children = _index_iteration_tree(tree, "MSBPCProj")
    assert root_id == "root-guid"
    assert {c["id"] for c in children} == {"p1"}
    assert "root-guid" not in {c["id"] for c in children}


def test_team_settings_payload_sets_backlog_when_unset() -> None:
    payload = _team_settings_payload(
        {
            "bug_behavior": "asRequirements",
            "backlog_iteration": "@currentIteration",
        },
        {
            "bugsBehavior": "off",
            "backlogIteration": {"id": "00000000-0000-0000-0000-000000000000"},
            "defaultIterationMacro": "",
        },
        "root-guid",
        {},
    )
    assert payload["backlogIteration"] == "root-guid"
    assert payload["defaultIterationMacro"] == "@CurrentIteration"
    assert payload["bugsBehavior"] == "asRequirements"


def test_team_settings_payload_empty_without_root() -> None:
    payload = _team_settings_payload(
        {"bug_behavior": "asRequirements", "backlog_iteration": "@currentIteration"},
        {"bugsBehavior": "off", "defaultIterationMacro": ""},
        None,
        {},
    )
    # Must not set macro alone — that produces the empty Backlog iteration UI state.
    assert payload == {}


def _backlog_ir(team_names: list[str]) -> dict[str, Any]:
    return {
        "targets": {"project_name": "MSBPCProj", "process_name": "MSBPCTemplate"},
        "counts": {"backlogs": 0, "iteration_paths": 2, "teams": len(team_names)},
        "process": {"backlogs": [], "work_item_types": []},
        "project": {
            "iteration_paths": [
                {"path": "Phase 1 - Initiate", "level": "1"},
                {"path": "Phase 1 - Initiate\\Sprint 1", "level": "2"},
            ],
            "teams": [
                {
                    "name": name,
                    "bug_behavior": "asRequirements",
                    "include_sub_areas": "Yes",
                    "backlog_iteration": "@currentIteration",
                }
                for name in team_names
            ],
        },
    }


def test_apply_backlog_parallel_teams_match_serial_counts() -> None:
    names = [f"Team {n}" for n in range(9)]
    serial_client = BacklogFakeClient()
    serial = apply_backlog(serial_client, _backlog_ir(names), dry_run=False, emit=lambda *_: None)
    parallel_client = BacklogFakeClient()
    parallel = apply_backlog(
        parallel_client, _backlog_ir(names), dry_run=False, emit=lambda *_: None, workers=4
    )

    assert parallel == serial
    assert parallel["team_settings"] == 9
    assert parallel["team_iterations"] == 9 * 2
    assert sorted(parallel_client.team_iters) == sorted(f"MSBPCProj/{n}" for n in names)


def test_cancel_stops_queued_teams_when_parallel() -> None:
    class Cancelled(Exception):
        pass

    cancelled = threading.Event()

    def emit(_step: str, message: str) -> None:
        if "Updated team settings" in message:
            cancelled.set()
        if cancelled.is_set():
            raise Cancelled()

    client = BacklogFakeClient()
    with pytest.raises(Cancelled):
        apply_backlog(
            client, _backlog_ir([f"Team {n}" for n in range(12)]), dry_run=False, emit=emit, workers=4
        )
    patched = {p["project"] for p in client.patches if p["path"] == "/_apis/work/teamsettings"}
    # Only teams already in flight when the cancel landed finish their settings PATCH.
    assert 1 <= len(patched) <= 4


def test_skip_existing_process_leaves_backlog_levels_alone() -> None:
    class RecordingClient(BacklogFakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.process_calls: list[str] = []

        def get(self, path: str, **kwargs: Any) -> Any:
            if "/_apis/work/processes" in path:
                self.process_calls.append(path)
            return super().get(path, **kwargs)

        def put(self, path: str, **kwargs: Any) -> Any:
            self.process_calls.append(path)
            return super().put(path, **kwargs)

        def get_process_id(self, _name: str) -> str:
            self.process_calls.append("get_process_id")
            return "proc-1"

    client = RecordingClient()
    events: list[str] = []
    stats = apply_backlog(
        client,
        _backlog_ir(["Accounting"]),
        dry_run=False,
        emit=lambda _s, m: events.append(m),
        process_changes=False,
    )
    assert client.process_calls == []
    assert not any("/_apis/work/processes" in p["path"] for p in client.posts + client.patches)
    assert stats["behaviors"] == 0
    assert stats["team_settings"] == 1
    assert any("left as they are" in m for m in events)


def test_apply_backlog_assigns_iterations_to_each_team() -> None:
    client = BacklogFakeClient()
    events: list[str] = []
    ir = {
        "targets": {"project_name": "MSBPCProj", "process_name": "MSBPCTemplate"},
        "counts": {"backlogs": 0, "iteration_paths": 2, "teams": 2},
        "process": {"backlogs": [], "work_item_types": []},
        "project": {
            "iteration_paths": [
                {"path": "Phase 1 - Initiate", "level": "1"},
                {"path": "Phase 1 - Initiate\\Sprint 1", "level": "2"},
            ],
            "teams": [
                {
                    "name": "Accounts payable",
                    "bug_behavior": "asRequirements",
                    "include_sub_areas": "Yes",
                    "backlog_iteration": "@currentIteration",
                },
                {
                    "name": "Accounting",
                    "bug_behavior": "asRequirements",
                    "include_sub_areas": "Yes",
                    "backlog_iteration": "@currentIteration",
                },
            ],
        },
    }
    stats = apply_backlog(client, ir, dry_run=False, emit=lambda _s, m: events.append(m))
    assert stats["team_settings"] == 2
    assert stats["team_iterations"] >= 2
    settings_patches = [p for p in client.patches if p["path"] == "/_apis/work/teamsettings"]
    assert settings_patches
    assert settings_patches[0]["body"]["backlogIteration"] == "root-guid"
    iter_posts = [p for p in client.posts if p["path"] == "/_apis/work/teamsettings/iterations"]
    # Root GUID must never be POSTed as a team iteration (TF400494).
    assert all(p["body"]["id"] != "root-guid" for p in iter_posts)
    assert any("backlogIteration=root-guid" in m for m in events)
