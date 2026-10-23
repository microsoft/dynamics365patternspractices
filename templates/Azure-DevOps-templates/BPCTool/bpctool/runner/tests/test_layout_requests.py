"""Layout reads each WIT's fields and form once, and retries boolean payloads on 400."""

from __future__ import annotations

from typing import Any

from app.ado_client import AdoError
from app.writers.layout import apply_layout

WIT_REF = "BPC.Workshop"


class CountingLayoutClient:
    def __init__(
        self,
        *,
        wit_fields: list[str],
        controls: list[str],
        reject_field_posts: int = 0,
        reject_message: str = "VS403099: invalid default value",
    ) -> None:
        self.wit_fields = list(wit_fields)
        self.controls = list(controls)
        self.reject_field_posts = reject_field_posts
        self.reject_message = reject_message
        self.gets: list[str] = []
        self.field_posts: list[dict[str, Any]] = []
        self.control_posts: list[str] = []
        self.group_posts: list[str] = []

    def list_process_wits(self, process_id: str) -> list[dict[str, Any]]:
        return [{"name": "Workshop", "referenceName": WIT_REF, "customization": "custom"}]

    def get(self, path: str, **_kwargs: Any) -> dict[str, Any]:
        self.gets.append(path)
        if path.endswith("/fields"):
            return {"value": [{"referenceName": ref} for ref in self.wit_fields]}
        return {
            "pages": [
                {
                    "id": "page-1",
                    "label": "Details",
                    "sections": [
                        {
                            "id": "Section1",
                            "groups": [
                                {"id": f"group-{label}", "label": label, "controls": []}
                                for label in self.group_posts
                            ]
                            + [
                                {
                                    "id": "group-1",
                                    "label": "Existing",
                                    "controls": [{"id": ref} for ref in self.controls],
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    def post(self, path: str, json_body: Any = None, **_kwargs: Any) -> dict[str, Any]:
        if path.endswith("/fields"):
            self.field_posts.append(json_body)
            if self.reject_field_posts:
                self.reject_field_posts -= 1
                raise AdoError(self.reject_message, status=400)
            self.wit_fields.append(json_body["referenceName"])
            return {}
        if path.endswith("/groups"):
            self.group_posts.append(json_body["label"])
            return {"id": f"group-{json_body['label']}"}
        if path.endswith("/controls"):
            self.control_posts.append(json_body["id"])
            self.controls.append(json_body["id"])
            return {}
        return {}

    def patch(self, path: str, json_body: Any = None, **_kwargs: Any) -> dict[str, Any]:
        return {}


def _ir(fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "targets": {"process_name": "Demo"},
        "counts": {"html_fields": 0, "hidden_field_placements": 0},
        "process": {
            "fields": fields,
            "work_item_types": [
                {
                    "name": "Workshop",
                    "reference_name": WIT_REF,
                    "applicable_field_labels": [f["label"] for f in fields],
                    "hidden_field_labels": [],
                }
            ],
        },
    }


def _field(n: int, *, field_type: str = "String") -> dict[str, Any]:
    return {
        "label": f"Field {n}",
        "reference_name": f"MSBPC.field{n}",
        "field_type": field_type,
        "group_name": "Existing",
    }


def _run(client: CountingLayoutClient, ir: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    events: list[str] = []
    stats = apply_layout(
        client,  # type: ignore[arg-type]
        ir,
        dry_run=False,
        emit=lambda _step, message: events.append(message),
        process_id="proc-1",
    )
    return stats, events


def test_rerun_reads_fields_and_layout_once_and_posts_nothing() -> None:
    fields = [_field(n) for n in range(5)]
    refs = [f["reference_name"] for f in fields]
    client = CountingLayoutClient(wit_fields=refs, controls=refs)
    stats, _ = _run(client, _ir(fields))

    assert client.field_posts == []
    assert client.control_posts == []
    assert sum(path.endswith("/fields") for path in client.gets) == 1
    assert sum(path.endswith("/layout") for path in client.gets) == 1
    assert stats["warnings"] == 0


def test_new_controls_reuse_a_group_created_earlier_in_the_run() -> None:
    fields = [dict(_field(n), group_name="New group") for n in range(3)]
    client = CountingLayoutClient(wit_fields=[], controls=[])
    stats, _ = _run(client, _ir(fields))

    assert client.group_posts == ["New group"]
    assert client.control_posts == [f["reference_name"] for f in fields]
    assert stats["fields_added"] == 3
    assert stats["controls"] == 3


def test_boolean_field_tries_fallback_payloads_after_a_400() -> None:
    field = dict(_field(1, field_type="Boolean"), default_value="false", required="Yes")
    client = CountingLayoutClient(wit_fields=[], controls=[], reject_field_posts=1)
    stats, events = _run(client, _ir([field]))

    assert len(client.field_posts) == 2
    assert stats["fields_added"] == 1
    assert stats["warnings"] == 0
    assert not any("Add boolean field" in message for message in events)


def test_field_rejected_with_400_is_reported_not_treated_as_present() -> None:
    client = CountingLayoutClient(wit_fields=[], controls=[], reject_field_posts=1)
    stats, events = _run(client, _ir([_field(1)]))

    assert len(client.field_posts) == 1
    assert stats["fields_added"] == 0
    assert stats["warnings"] == 1
    assert client.control_posts == []
    assert any("Add field MSBPC.field1" in message for message in events)


class RejectingLayoutClient(CountingLayoutClient):
    def __init__(self, reject: str, **kwargs: Any) -> None:
        super().__init__(wit_fields=[], controls=[], **kwargs)
        self.reject = reject

    def post(self, path: str, json_body: Any = None, **kwargs: Any) -> dict[str, Any]:
        if path.endswith(self.reject):
            raise AdoError("VS402500: rejected", status=400)
        return super().post(path, json_body, **kwargs)


def test_html_control_rejected_with_400_is_a_warning() -> None:
    field = dict(_field(1, field_type="html"), is_html=True)
    client = RejectingLayoutClient("/groups")
    stats, events = _run(client, _ir([field]))

    assert stats["html_controls"] == 0
    assert stats["warnings"] == 1
    assert any("HTML control MSBPC.field1 on Workshop: VS402500" in m for m in events)


def test_group_failure_reports_the_azure_devops_reason() -> None:
    field = dict(_field(1), group_name="New group")
    client = RejectingLayoutClient("/groups")
    stats, events = _run(client, _ir([field]))

    assert stats["warnings"] == 1
    assert any("Could not create group 'New group' on Workshop: VS402500" in m for m in events)


def test_page_rejected_and_still_missing_reports_the_reason() -> None:
    field = dict(_field(1), page_name="Extra")
    client = RejectingLayoutClient("/pages")
    stats, events = _run(client, _ir([field]))

    assert stats["warnings"] == 1
    assert any("Could not create page 'Extra' on Workshop: VS402500" in m for m in events)


def test_already_exists_message_counts_as_present() -> None:
    client = CountingLayoutClient(
        wit_fields=[],
        controls=[],
        reject_field_posts=1,
        reject_message="VS402805: Field MSBPC.field1 already exists on the work item type",
    )
    stats, _ = _run(client, _ir([_field(1)]))

    assert stats["warnings"] == 0
    assert client.control_posts == ["MSBPC.field1"]
