"""Work item types matrix: X = on WIT + form, H = on WIT but hidden from the form."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook

from app.excel_ir import parse_work_item_types
from app.mapping import build_mapping_from_ir
from app.writers.layout import apply_layout

PARTNER = "MSBPC.partnerworkshoptype"
MICROSOFT = "MSBPC.microsoftworkshoptype"


def _write_matrix(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Work item types"
    ws.append(
        [
            "Work item type",
            "Custom work item type",
            "Microsoft workshop type",
            "Partner workshop type",
            "Questions",
        ]
    )
    ws.append(["Workshop", "Yes", "H", "X", None])
    ws.append(["Scenario", "Yes", None, None, "x"])
    ws.append(["Folder", "Yes", "h", None, ""])
    wb.save(path)


def test_parse_work_item_types_splits_x_and_h(tmp_path: Path) -> None:
    path = tmp_path / "template.xlsx"
    _write_matrix(path)
    by_name = {wit["name"]: wit for wit in parse_work_item_types(path)}

    assert by_name["Workshop"]["applicable_field_labels"] == ["Partner workshop type"]
    assert by_name["Workshop"]["hidden_field_labels"] == ["Microsoft workshop type"]
    assert by_name["Scenario"]["applicable_field_labels"] == ["Questions"]
    assert by_name["Scenario"]["hidden_field_labels"] == []
    assert by_name["Folder"]["hidden_field_labels"] == ["Microsoft workshop type"]


def test_template_workshop_hides_microsoft_workshop_type(template_path: Path) -> None:
    workshop = next(
        wit for wit in parse_work_item_types(template_path) if wit["name"] == "Workshop"
    )
    assert "Microsoft workshop type" in workshop["hidden_field_labels"]
    assert "Microsoft workshop type" not in workshop["applicable_field_labels"]
    assert "Partner workshop type" in workshop["applicable_field_labels"]


def test_mapping_treats_hidden_fields_as_on_the_wit() -> None:
    ir = {
        "process": {
            "fields": [],
            "work_item_types": [
                {
                    "name": "Workshop",
                    "applicable_field_labels": ["Partner workshop type"],
                    "hidden_field_labels": ["Microsoft workshop type"],
                }
            ],
        }
    }
    mapping = build_mapping_from_ir(ir)
    assert mapping.applicable_fields_by_wit["workshop"] == {
        "partner workshop type",
        "microsoft workshop type",
    }
    assert mapping.hidden_fields_by_wit["workshop"] == {"microsoft workshop type"}


class FakeLayoutClient:
    def __init__(self, layout: dict[str, Any]) -> None:
        self.layout = layout
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.patches: list[tuple[str, dict[str, Any]]] = []

    def list_process_wits(self, process_id: str) -> list[dict[str, Any]]:
        return [{"name": "Workshop", "referenceName": "BPC.Workshop", "customization": "custom"}]

    def get(self, path: str, **_kwargs: Any) -> dict[str, Any]:
        return self.layout

    def post(self, path: str, json_body: Any = None, **_kwargs: Any) -> dict[str, Any]:
        self.posts.append((path, json_body))
        if path.endswith("/groups"):
            return {"id": "new-group"}
        return {}

    def patch(self, path: str, json_body: Any = None, **_kwargs: Any) -> dict[str, Any]:
        self.patches.append((path, json_body))
        return {}


def _layout(*controls: dict[str, Any]) -> dict[str, Any]:
    return {
        "pages": [
            {
                "id": "page-1",
                "label": "Details",
                "sections": [
                    {
                        "id": "Section1",
                        "groups": [
                            {"id": "group-1", "label": "Workshop", "controls": list(controls)}
                        ],
                    }
                ],
            }
        ]
    }


def _ir(*, visible: list[str], hidden: list[str], required: str = "") -> dict[str, Any]:
    fields = [
        {
            "label": "Partner workshop type",
            "reference_name": PARTNER,
            "field_type": "String",
            "group_name": "Workshop",
        },
        {
            "label": "Microsoft workshop type",
            "reference_name": MICROSOFT,
            "field_type": "String",
            "group_name": "Workshop",
            "required": required,
        },
    ]
    return {
        "targets": {"process_name": "Demo"},
        "counts": {"html_fields": 0, "hidden_field_placements": len(hidden)},
        "process": {
            "fields": fields,
            "work_item_types": [
                {
                    "name": "Workshop",
                    "reference_name": "BPC.Workshop",
                    "applicable_field_labels": visible,
                    "hidden_field_labels": hidden,
                }
            ],
        },
    }


def _field_posts(client: FakeLayoutClient) -> list[str]:
    return [body["referenceName"] for path, body in client.posts if path.endswith("/fields")]


def _control_posts(client: FakeLayoutClient) -> list[str]:
    return [body["id"] for path, body in client.posts if path.endswith("/controls")]


def test_layout_adds_hidden_field_to_wit_without_a_control() -> None:
    client = FakeLayoutClient(_layout())
    events: list[str] = []
    stats = apply_layout(
        client,  # type: ignore[arg-type]
        _ir(visible=["Partner workshop type"], hidden=["Microsoft workshop type"]),
        dry_run=False,
        emit=lambda _step, message: events.append(message),
        process_id="proc-1",
    )
    assert _field_posts(client) == [PARTNER, MICROSOFT]
    assert _control_posts(client) == [PARTNER]
    assert client.patches == []
    assert stats["hidden_fields"] == 1
    assert stats["controls_hidden"] == 0
    assert any("1 hidden (H) fields" in message for message in events)


def test_layout_hides_existing_control_for_h_field() -> None:
    client = FakeLayoutClient(_layout({"id": MICROSOFT, "visible": True}))
    stats = apply_layout(
        client,  # type: ignore[arg-type]
        _ir(visible=[], hidden=["Microsoft workshop type"]),
        dry_run=False,
        emit=lambda *_: None,
        process_id="proc-1",
    )
    assert _control_posts(client) == []
    assert len(client.patches) == 1
    path, body = client.patches[0]
    assert path.endswith(f"/layout/groups/group-1/controls/{MICROSOFT}")
    assert body == {"id": MICROSOFT, "visible": False}
    assert stats["controls_hidden"] == 1


def test_layout_shows_control_again_when_h_changes_to_x() -> None:
    client = FakeLayoutClient(_layout({"id": MICROSOFT, "visible": False}))
    stats = apply_layout(
        client,  # type: ignore[arg-type]
        _ir(visible=["Microsoft workshop type"], hidden=[]),
        dry_run=False,
        emit=lambda *_: None,
        process_id="proc-1",
    )
    assert _control_posts(client) == []
    assert client.patches[0][1] == {"id": MICROSOFT, "visible": True}
    assert stats["controls_shown"] == 1


def test_layout_warns_when_hidden_field_is_required_without_default() -> None:
    client = FakeLayoutClient(_layout())
    events: list[str] = []
    stats = apply_layout(
        client,  # type: ignore[arg-type]
        _ir(visible=[], hidden=["Microsoft workshop type"], required="Yes"),
        dry_run=False,
        emit=lambda _step, message: events.append(message),
        process_id="proc-1",
    )
    assert stats["warnings"] == 1
    assert any("required with no default value" in message for message in events)


def test_layout_dry_run_mentions_hidden_fields() -> None:
    events: list[str] = []
    apply_layout(
        None,  # type: ignore[arg-type]
        _ir(visible=[], hidden=["Microsoft workshop type"]),
        dry_run=True,
        emit=lambda _step, message: events.append(message),
    )
    assert "1 hidden (H) fields" in events[0]
