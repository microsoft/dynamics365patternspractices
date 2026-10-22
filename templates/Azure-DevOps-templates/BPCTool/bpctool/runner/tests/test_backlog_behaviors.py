"""Backlog level rename/create and WIT→behavior assignment (reference Script 4 Parts 1–2)."""

from __future__ import annotations

from typing import Any

from app.writers.backlog import (
    _assign_wits_to_backlogs,
    _configure_backlog_levels,
    _set_default_wits,
)


class BehaviorFakeClient:
    def __init__(self, behaviors: list[dict[str, Any]], wits: list[dict[str, Any]]) -> None:
        self.behaviors = {str(b["referenceName"]): dict(b) for b in behaviors}
        self.wits = list(wits)
        self.wit_behaviors: dict[str, list[dict[str, Any]]] = {}
        self.puts: list[dict[str, Any]] = []
        self.posts: list[dict[str, Any]] = []
        self.deletes: list[str] = []

    def list_process_wits(self, _process_id: str) -> list[dict[str, Any]]:
        return list(self.wits)

    def get(self, path: str, **_kwargs: Any) -> Any:
        if path.endswith("/behaviors") and "workitemtypesbehaviors" not in path:
            return {"value": list(self.behaviors.values())}
        if "/workitemtypesbehaviors/" in path and path.endswith("/behaviors"):
            # .../workitemtypesbehaviors/{witRef}/behaviors
            wit_ref = path.split("/workitemtypesbehaviors/")[1].split("/behaviors")[0]
            return {"value": list(self.wit_behaviors.get(wit_ref, []))}
        return {"value": []}

    def put(self, path: str, **kwargs: Any) -> Any:
        body = kwargs.get("json_body") or {}
        self.puts.append({"path": path, "body": body})
        ref = path.rsplit("/", 1)[-1]
        if ref in self.behaviors:
            self.behaviors[ref]["name"] = body.get("name", self.behaviors[ref]["name"])
            if "color" in body:
                self.behaviors[ref]["color"] = body["color"]
        return self.behaviors.get(ref, body)

    def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs.get("json_body") or {}
        self.posts.append({"path": path, "body": body})
        if path.endswith("/behaviors") and "workitemtypesbehaviors" not in path:
            ref = f"Custom.{body['name'].replace(' ', '')}"
            created = {
                "name": body["name"],
                "referenceName": ref,
                "color": body.get("color"),
            }
            self.behaviors[ref] = created
            return created
        if "/workitemtypesbehaviors/" in path:
            wit_ref = path.split("/workitemtypesbehaviors/")[1].split("/behaviors")[0]
            entry = {
                "behavior": {"id": body["behavior"]["id"]},
                "isDefault": bool(body.get("isDefault")),
            }
            self.wit_behaviors.setdefault(wit_ref, []).append(entry)
            return entry
        return body

    def delete(self, path: str, **_kwargs: Any) -> Any:
        self.deletes.append(path)
        if "/workitemtypesbehaviors/" in path and "/behaviors/" in path:
            parts = path.split("/workitemtypesbehaviors/")[1]
            wit_ref, rest = parts.split("/behaviors/", 1)
            behavior_ref = rest
            current = self.wit_behaviors.get(wit_ref, [])
            self.wit_behaviors[wit_ref] = [
                cb
                for cb in current
                if str((cb.get("behavior") or {}).get("id") or "") != behavior_ref
            ]
            return None
        # DELETE /_apis/work/processes/{id}/behaviors/{ref}
        if "/behaviors/" in path:
            ref = path.rsplit("/", 1)[-1]
            self.behaviors.pop(ref, None)
        return None


TEMPLATE_BACKLOGS = [
    {
        "name": "Highest",
        "type": "Portfolio backlog",
        "color": "FF69B4",
        "default_wit": "Functional area",
        "rename_from": "(new)",
    },
    {
        "name": "Kanban",
        "type": "Portfolio backlog",
        "color": "007ACC",
        "default_wit": "Test Case",
        "rename_from": "(new)",
    },
    {
        "name": "Levels",
        "type": "Portfolio backlog",
        "color": "",
        "default_wit": "Process",
        "rename_from": "Epic",
    },
    {
        "name": "Lowest",
        "type": "Portfolio backlog",
        "color": "",
        "default_wit": "Scenario",
        "rename_from": "Feature",
    },
    {
        "name": "Deliverables",
        "type": "Requirements backlog",
        "color": "",
        "default_wit": "Configuration",
        "rename_from": "(rename)",
    },
    {
        "name": "Tasks",
        "type": "Iteration backlog",
        "color": "",
        "default_wit": "Task",
        "rename_from": "(rename)",
    },
]


def test_configure_backlog_levels_renames_and_creates() -> None:
    client = BehaviorFakeClient(
        behaviors=[
            {
                "name": "Epics",
                "referenceName": "Microsoft.VSTS.Agile.EpicBacklogBehavior",
            },
            {
                "name": "Features",
                "referenceName": "Microsoft.VSTS.Agile.FeatureBacklogBehavior",
            },
            {
                "name": "Stories",
                "referenceName": "System.RequirementBacklogBehavior",
            },
            {
                "name": "Tasks",
                "referenceName": "System.TaskBacklogBehavior",
            },
        ],
        wits=[],
    )
    stats: dict[str, Any] = {"behaviors": 0, "warnings": 0}
    events: list[str] = []
    refs = _configure_backlog_levels(
        client,
        {"process": {"backlogs": TEMPLATE_BACKLOGS}},
        "proc-1",
        stats,
        lambda _s, m: events.append(m),
    )

    assert refs["Levels"] == "Microsoft.VSTS.Agile.EpicBacklogBehavior"
    assert refs["Lowest"] == "Microsoft.VSTS.Agile.FeatureBacklogBehavior"
    assert refs["Deliverables"] == "System.RequirementBacklogBehavior"
    assert refs["Tasks"] == "System.TaskBacklogBehavior"
    assert refs["Highest"].startswith("Custom.")
    assert refs["Kanban"].startswith("Custom.")
    assert stats["behaviors"] == 6

    put_names = {p["body"]["name"] for p in client.puts}
    assert put_names == {"Levels", "Lowest", "Deliverables"}
    # Tasks already named correctly — no PUT required for that row.
    assert "Tasks" not in put_names
    assert any("Renamed behavior 'Epics' → 'Levels'" in m for m in events)
    assert any("Created backlog behavior 'Highest'" in m for m in events)


def test_configure_heals_duplicate_levels_left_beside_epics() -> None:
    """Prior buggy apply created custom Levels while leaving system Epics."""
    client = BehaviorFakeClient(
        behaviors=[
            {
                "name": "Levels",
                "referenceName": "Custom.Levels",
            },
            {
                "name": "Epics",
                "referenceName": "Microsoft.VSTS.Agile.EpicBacklogBehavior",
            },
            {
                "name": "Lowest",
                "referenceName": "Custom.Lowest",
            },
            {
                "name": "Features",
                "referenceName": "Microsoft.VSTS.Agile.FeatureBacklogBehavior",
            },
            {
                "name": "Stories",
                "referenceName": "System.RequirementBacklogBehavior",
            },
            {
                "name": "Tasks",
                "referenceName": "System.TaskBacklogBehavior",
            },
        ],
        wits=[],
    )
    stats: dict[str, Any] = {"behaviors": 0, "warnings": 0}
    events: list[str] = []
    refs = _configure_backlog_levels(
        client,
        {"process": {"backlogs": TEMPLATE_BACKLOGS}},
        "proc-1",
        stats,
        lambda _s, m: events.append(m),
    )

    assert refs["Levels"] == "Microsoft.VSTS.Agile.EpicBacklogBehavior"
    assert refs["Lowest"] == "Microsoft.VSTS.Agile.FeatureBacklogBehavior"
    assert "Custom.Levels" not in client.behaviors
    assert "Custom.Lowest" not in client.behaviors
    assert client.behaviors["Microsoft.VSTS.Agile.EpicBacklogBehavior"]["name"] == "Levels"
    assert client.behaviors["Microsoft.VSTS.Agile.FeatureBacklogBehavior"]["name"] == "Lowest"
    assert any("Removing duplicate custom backlog 'Levels'" in m for m in events)
    assert any("Renamed behavior 'Epics' → 'Levels'" in m for m in events)
    # No leftover Epics display name.
    assert all(b.get("name") != "Epics" for b in client.behaviors.values())


def test_assign_wits_skips_disabled_and_maps_enabled() -> None:
    client = BehaviorFakeClient(
        behaviors=[],
        wits=[
            {"name": "Process", "referenceName": "MSBPC.Process"},
            {"name": "Epic", "referenceName": "MSBPC.Epic"},
            {"name": "Configuration", "referenceName": "MSBPC.Configuration"},
        ],
    )
    # Seed Epic still on old Epics behavior so assign would rewire if not skipped.
    client.wit_behaviors["MSBPC.Epic"] = [
        {"behavior": {"id": "Microsoft.VSTS.Agile.EpicBacklogBehavior"}, "isDefault": True}
    ]
    client.wit_behaviors["MSBPC.Process"] = [
        {"behavior": {"id": "Microsoft.VSTS.Agile.EpicBacklogBehavior"}, "isDefault": False}
    ]

    stats: dict[str, Any] = {"wit_assignments": 0, "warnings": 0}
    events: list[str] = []
    backlog_refs = {
        "Levels": "Microsoft.VSTS.Agile.EpicBacklogBehavior",
        "Deliverables": "System.RequirementBacklogBehavior",
    }
    ir = {
        "process": {
            "work_item_types": [
                {
                    "name": "Epic",
                    "disabled": True,
                    "backlog_name": "Levels",
                },
                {
                    "name": "Process",
                    "disabled": False,
                    "backlog_name": "Levels",
                },
                {
                    "name": "Configuration",
                    "disabled": False,
                    "backlog_name": "Deliverables",
                },
                {
                    "name": "Bug",
                    "disabled": False,
                    "backlog_name": "No associated backlog",
                },
            ]
        }
    }
    _assign_wits_to_backlogs(
        client, ir, "proc-1", backlog_refs, stats, lambda _s, m: events.append(m)
    )

    assert any("Skipping 'Epic' — disabled WIT" in m for m in events)
    assert stats["wit_assignments"] == 1  # Configuration only (Process already on Levels)
    assert any(p for p in client.posts if "MSBPC.Configuration" in p["path"])
    assert client.wit_behaviors["MSBPC.Configuration"][0]["behavior"]["id"] == (
        "System.RequirementBacklogBehavior"
    )
    # Disabled Epic must not be reassigned.
    assert not any("MSBPC.Epic" in p["path"] for p in client.posts)


def test_set_default_wits_marks_is_default() -> None:
    client = BehaviorFakeClient(
        behaviors=[],
        wits=[
            {"name": "Process", "referenceName": "MSBPC.Process"},
            {"name": "Configuration", "referenceName": "MSBPC.Configuration"},
        ],
    )
    client.wit_behaviors["MSBPC.Process"] = [
        {
            "behavior": {"id": "Microsoft.VSTS.Agile.EpicBacklogBehavior"},
            "isDefault": False,
        }
    ]
    stats: dict[str, Any] = {"default_wits": 0, "warnings": 0}
    events: list[str] = []
    _set_default_wits(
        client,
        {
            "process": {
                "backlogs": [
                    {
                        "name": "Levels",
                        "default_wit": "Process",
                        "rename_from": "Epic",
                    }
                ]
            }
        },
        "proc-1",
        {"Levels": "Microsoft.VSTS.Agile.EpicBacklogBehavior"},
        stats,
        lambda _s, m: events.append(m),
    )
    assert stats["default_wits"] == 1
    assert client.wit_behaviors["MSBPC.Process"][0]["isDefault"] is True
    assert any("Set 'Process' as default for 'Levels'" in m for m in events)
