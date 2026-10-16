"""Team area assignment aggregation (reference Script 3 semantics)."""

from __future__ import annotations

from typing import Any

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
