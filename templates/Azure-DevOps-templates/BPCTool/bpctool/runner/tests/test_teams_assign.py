"""Team area assignment aggregation (reference Script 3 semantics)."""

from __future__ import annotations

from typing import Any

from app.ado_client import AdoError
from app.writers.teams import _assign_team_areas, _format_area_path, apply_teams


class FakeClient:
    def __init__(self) -> None:
        self.patches: list[dict[str, Any]] = []
        self.project_id = "proj-1"
        self.teams = {
            "value": [
                {"name": "Business process catalog"},
                {"name": "Accounting"},
            ]
        }

    def get_project_id(self, _project: str) -> str:
        return self.project_id

    def get(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/teams"):
            return self.teams
        # Area nodes already exist.
        if "classificationnodes" in path:
            return {"name": "ok"}
        return {}

    def post(self, path: str, **kwargs: Any) -> Any:
        return {"ok": True}

    def patch(self, path: str, **kwargs: Any) -> Any:
        self.patches.append({"path": path, "project": kwargs.get("project"), "body": kwargs.get("json_body")})
        return {"ok": True}


def test_format_area_path() -> None:
    assert _format_area_path("MSBPCProj", "Functional areas\\Finance") == (
        "MSBPCProj\\Functional areas\\Finance"
    )


def test_assign_aggregates_all_paths_one_patch() -> None:
    client = FakeClient()
    _assign_team_areas(
        client,
        "MSBPCProj",
        "Accounting",
        "Functional areas\\Finance",
        {
            "Functional areas\\Finance",
            "Functional areas\\Finance\\Accounting",
        },
    )
    assert len(client.patches) == 1
    body = client.patches[0]["body"]
    assert body["defaultValue"] == "MSBPCProj\\Functional areas\\Finance"
    values = {row["value"] for row in body["values"]}
    assert values == {
        "MSBPCProj\\Functional areas\\Finance",
        "MSBPCProj\\Functional areas\\Finance\\Accounting",
    }
    assert all(row["includeChildren"] is False for row in body["values"])


def test_apply_teams_assigns_each_mapped_team() -> None:
    client = FakeClient()
    events: list[str] = []
    ir = {
        "targets": {"project_name": "MSBPCProj"},
        "counts": {"teams": 2, "area_paths": 3},
        "project": {
            "teams": [
                {"name": "Business process catalog"},
                {"name": "Accounting"},
            ],
            "area_paths": [
                {
                    "path": "Business process catalog",
                    "team": "Business process catalog",
                },
                {
                    "path": "Business process catalog\\Acquire to dispose",
                    "team": "Business process catalog",
                },
                {
                    "path": "Functional areas\\Finance\\Accounting",
                    "team": "Accounting",
                },
            ],
        },
    }
    stats = apply_teams(client, ir, dry_run=False, emit=lambda _s, m: events.append(m))
    assert stats["assignments"] == 2
    assert len(client.patches) == 2
    bpc = next(p for p in client.patches if p["project"] == "MSBPCProj/Business process catalog")
    assert len(bpc["body"]["values"]) == 2
    assert any("Assigned team 'Business process catalog'" in m for m in events)


class EmptyAreasClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.created_areas: list[tuple[str, str]] = []

    def get(self, path: str, **kwargs: Any) -> Any:
        if "classificationnodes" in path:
            if path not in {f"{parent}/{name}" for parent, name in self.created_areas}:
                raise AdoError("not found", status=404)
            return {"name": "ok"}
        return super().get(path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        if "classificationnodes" in path:
            self.created_areas.append((path, kwargs["json_body"]["name"]))
        return {}


def test_apply_teams_nests_areas_under_root_area_path() -> None:
    client = EmptyAreasClient()
    ir = {
        "targets": {"project_name": "MSBPCProj"},
        "counts": {"teams": 1, "area_paths": 1},
        "project": {
            "teams": [{"name": "Accounting"}],
            "area_paths": [{"path": "MSBPCProj\\Finance", "team": "Accounting"}],
        },
    }
    apply_teams(client, ir, dry_run=False, emit=lambda *_: None, root_area_path="MSBPCProj\\Imported")
    assert client.created_areas == [
        ("/_apis/wit/classificationnodes/Areas", "Imported"),
        ("/_apis/wit/classificationnodes/Areas/Imported", "Finance"),
    ]
    body = client.patches[0]["body"]
    assert body["defaultValue"] == "MSBPCProj\\Imported\\Finance"


def test_apply_teams_merges_team_names_that_differ_only_in_case() -> None:
    client = FakeClient()
    events: list[str] = []
    ir = {
        "targets": {"project_name": "MSBPCProj"},
        "counts": {"teams": 1, "area_paths": 2},
        "project": {
            "teams": [{"name": "Accounting"}],
            "area_paths": [
                {"path": "Functional areas\\Finance", "team": "Accounting"},
                {"path": "Functional areas\\Finance\\Payables", "team": "accounting"},
            ],
        },
    }
    stats = apply_teams(client, ir, dry_run=False, emit=lambda _s, m: events.append(m))
    assert stats["assignments"] == 1
    assert len(client.patches) == 1
    assert client.patches[0]["project"] == "MSBPCProj/Accounting"
    assert {row["value"] for row in client.patches[0]["body"]["values"]} == {
        "MSBPCProj\\Functional areas\\Finance",
        "MSBPCProj\\Functional areas\\Finance\\Payables",
    }
    assert not any("no Area paths row" in m for m in events)


def test_apply_teams_sends_include_sub_areas_from_the_teams_sheet() -> None:
    client = FakeClient()
    ir = {
        "targets": {"project_name": "MSBPCProj"},
        "counts": {"teams": 2, "area_paths": 2},
        "project": {
            "teams": [
                {"name": "Accounting", "include_sub_areas": "Yes"},
                {"name": "Business process catalog", "include_sub_areas": "No"},
            ],
            "area_paths": [
                {"path": "Functional areas\\Finance", "team": "Accounting"},
                {"path": "Business process catalog", "team": "Business process catalog"},
            ],
        },
    }
    apply_teams(client, ir, dry_run=False, emit=lambda *_: None)
    include = {
        patch["project"]: {row["includeChildren"] for row in patch["body"]["values"]}
        for patch in client.patches
    }
    assert include == {
        "MSBPCProj/Accounting": {True},
        "MSBPCProj/Business process catalog": {False},
    }


class AreaTreeClient(FakeClient):
    """Answers the whole-tree read; per-node existence GETs would be a regression."""

    def __init__(self) -> None:
        super().__init__()
        self.gets: list[str] = []
        self.created_areas: list[tuple[str, str]] = []

    def get(self, path: str, **kwargs: Any) -> Any:
        self.gets.append(path)
        if path.startswith("/_apis/wit/classificationnodes/Areas?$depth="):
            return {
                "name": "MSBPCProj",
                "children": [{"name": "Functional areas", "children": [{"name": "Finance"}]}],
            }
        return super().get(path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        if "classificationnodes" in path:
            self.created_areas.append((path, kwargs["json_body"]["name"]))
        return {}


def test_apply_teams_reads_the_area_tree_once_and_creates_only_missing_nodes() -> None:
    client = AreaTreeClient()
    ir = {
        "targets": {"project_name": "MSBPCProj"},
        "counts": {"teams": 1, "area_paths": 2},
        "project": {
            "teams": [{"name": "Accounting"}],
            "area_paths": [
                {"path": "functional areas\\Finance", "team": "Accounting"},
                {"path": "Functional areas\\Finance\\Payables", "team": "Accounting"},
            ],
        },
    }
    stats = apply_teams(client, ir, dry_run=False, emit=lambda *_: None)
    assert client.created_areas == [
        ("/_apis/wit/classificationnodes/Areas/Functional%20areas/Finance", "Payables")
    ]
    assert stats["areas"] == 1
    assert [path for path in client.gets if "classificationnodes" in path] == [
        "/_apis/wit/classificationnodes/Areas?$depth=14"
    ]


def test_apply_teams_dry_run_does_not_patch() -> None:
    client = FakeClient()
    ir = {
        "targets": {"project_name": "MSBPCProj"},
        "counts": {"teams": 1, "area_paths": 1},
        "project": {
            "teams": [{"name": "Accounting"}],
            "area_paths": [{"path": "Functional areas", "team": "Accounting"}],
        },
    }
    stats = apply_teams(client, ir, dry_run=True, emit=lambda *_: None)
    assert stats.get("dry_run") is True
    assert stats["assignments"] == 1
    assert client.patches == []
