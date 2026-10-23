"""Resume, parent-aware ready queue, and id-map helpers for catalog import."""

from __future__ import annotations

import csv
import threading
from pathlib import Path

import pytest

from app import catalog_runtime
from app.ado_client import AdoError
from app.catalog_import import WorkItemDraft
from app.catalog_runtime import (
    ReadyQueue,
    append_id_map_row,
    backfill_parent_links,
    clamp_parallel_workers,
    import_drafts_parent_aware,
    load_id_map,
    load_id_map_parents,
    open_id_map_for_append,
)


def _draft(
    key: str,
    *,
    parent_key: str | None = None,
    wit: str = "Scenario",
    title: str | None = None,
    row: int = 1,
) -> WorkItemDraft:
    return WorkItemDraft(
        key=key,
        parent_key=parent_key,
        work_item_type=wit,
        title=title or key,
        fields={"System.Title": title or key},
        source_file="bpc.xlsx",
        source_row=row,
    )


def test_clamp_parallel_workers() -> None:
    assert clamp_parallel_workers(None) == 4
    assert clamp_parallel_workers(0) == 1
    assert clamp_parallel_workers(99) == 16
    assert clamp_parallel_workers(8) == 8


def test_load_id_map_resume(tmp_path: Path) -> None:
    path = tmp_path / "ado-id-map.csv"
    path.write_text(
        "Key,WorkItemId,WorkItemType,Title,ParentKey,ParentId\n"
        "root,101,End to end,Root,,\n"
        "child,102,Scenario,Child,root,101\n",
        encoding="utf-8",
    )
    assert load_id_map(path) == {"root": 101, "child": 102}
    assert load_id_map(tmp_path / "missing.csv") == {}


def test_load_id_map_parents(tmp_path: Path) -> None:
    path = tmp_path / "ado-id-map.csv"
    path.write_text(
        "Key,WorkItemId,WorkItemType,Title,ParentKey,ParentId\n"
        "root,101,End to end,Root,,\n"
        "child,102,Scenario,Child,root,101\n",
        encoding="utf-8",
    )
    assert load_id_map_parents(path) == {"child": 101}


def test_ready_queue_parent_aware() -> None:
    pending = {
        "a": _draft("a", row=1),
        "b": _draft("b", parent_key="a", row=2),
        "c": _draft("c", parent_key="missing", row=3),
        "d": _draft("d", row=4),
    }
    queue = ReadyQueue(pending, id_map={})
    assert [d.key for d in queue.pop(10)] == ["a", "d"]
    assert queue.pop(10) == []
    queue.parent_created("a")
    assert [d.key for d in queue.pop(10)] == ["b"]
    assert [d.key for d in queue.remaining()] == ["c"]


def test_ready_queue_respects_limit_and_source_order() -> None:
    pending = {key: _draft(key, row=row) for key, row in (("z", 1), ("y", 2), ("x", 3))}
    queue = ReadyQueue(pending, id_map={})
    assert [d.key for d in queue.pop(2)] == ["z", "y"]
    assert [d.key for d in queue.pop(2)] == ["x"]


def test_import_reports_missing_parent(tmp_path: Path) -> None:
    class FakeClient:
        def create_work_item(self, project, wit, fields, **kwargs):
            if fields["System.Title"] == "root":
                raise AdoError("ADO 400 Bad Request: boom", status=400)
            return {"id": 5}

    drafts = [_draft("root", row=1), _draft("child", parent_key="root", row=2)]
    _, failures, stats = import_drafts_parent_aware(
        FakeClient(),  # type: ignore[arg-type]
        drafts,
        project="Demo",
        id_map={},
        id_map_path=tmp_path / "ado-id-map.csv",
        parallel_workers=2,
        emit=lambda *_: None,
    )
    assert stats["failed"] == 2
    assert stats["missing_parent"] == 1
    assert stats["cancelled"] == 0
    assert {f["key"] for f in failures} == {"root", "child"}


def test_import_cancel_stops_submitting_and_records_in_flight(tmp_path: Path) -> None:
    cancel = threading.Event()

    class FakeClient:
        def __init__(self) -> None:
            self.created: list[str] = []

        def create_work_item(self, project, wit, fields, **kwargs):
            self.created.append(fields["System.Title"])
            cancel.set()
            return {"id": 100 + len(self.created)}

    client = FakeClient()
    id_map_path = tmp_path / "ado-id-map.csv"
    drafts = [_draft(f"k{i}", row=i) for i in range(1, 6)]
    progress: list[dict] = []
    id_map, failures, stats = import_drafts_parent_aware(
        client,  # type: ignore[arg-type]
        drafts,
        project="Demo",
        id_map={},
        id_map_path=id_map_path,
        parallel_workers=1,
        emit=lambda *_: None,
        progress=progress.append,
        should_cancel=cancel.is_set,
    )
    assert client.created == ["k1"]
    assert stats["created"] == 1
    assert stats["cancelled"] == 4
    assert stats["missing_parent"] == 0
    assert failures == []
    assert load_id_map(id_map_path) == {"k1": 101}
    assert progress[-1]["phase"] == "create"
    assert progress[-1]["created"] == 1


def test_cancel_keeps_failed_parent_descendants_as_missing_parent(tmp_path: Path) -> None:
    cancel = threading.Event()

    class FakeClient:
        def create_work_item(self, project, wit, fields, **kwargs):
            title = fields["System.Title"]
            if title == "bad":
                raise AdoError("ADO 400 Bad Request: boom", status=400)
            cancel.set()
            return {"id": 7}

    drafts = [
        _draft("bad", row=1),
        _draft("bad-child", parent_key="bad", row=2),
        _draft("good", row=3),
        _draft("good-child", parent_key="good", row=4),
        _draft("other", row=5),
    ]
    _, failures, stats = import_drafts_parent_aware(
        FakeClient(),  # type: ignore[arg-type]
        drafts,
        project="Demo",
        id_map={},
        id_map_path=tmp_path / "ado-id-map.csv",
        parallel_workers=1,
        emit=lambda *_: None,
        should_cancel=cancel.is_set,
    )
    assert stats["created"] == 1
    assert stats["missing_parent"] == 1
    assert {f["key"] for f in failures} == {"bad", "bad-child"}
    assert stats["cancelled"] == 2


def test_create_outcome_unknown_adopts_single_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalog_runtime, "RECONCILE_DELAY_S", 0)

    class FakeClient:
        def __init__(self) -> None:
            self.creates = 0

        def create_work_item(self, project, wit, fields, **kwargs):
            self.creates += 1
            raise AdoError("socket reset", transient=True, outcome_unknown=True)

        def find_work_item_ids(self, project, wit, **kwargs):
            return [777]

    client = FakeClient()
    id_map_path = tmp_path / "ado-id-map.csv"
    id_map, failures, stats = import_drafts_parent_aware(
        client,  # type: ignore[arg-type]
        [_draft("only", row=1)],
        project="Demo",
        id_map={},
        id_map_path=id_map_path,
        parallel_workers=1,
        emit=lambda *_: None,
    )
    assert client.creates == 1
    assert failures == []
    assert id_map == {"only": 777}
    assert stats["reconciled"] == 1


def test_create_outcome_unknown_retries_once_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalog_runtime, "RECONCILE_DELAY_S", 0)

    class FakeClient:
        def __init__(self) -> None:
            self.creates = 0

        def create_work_item(self, project, wit, fields, **kwargs):
            self.creates += 1
            if self.creates == 1:
                raise AdoError("socket reset", transient=True, outcome_unknown=True)
            return {"id": 55}

        def find_work_item_ids(self, project, wit, **kwargs):
            return []

    client = FakeClient()
    id_map_path = tmp_path / "ado-id-map.csv"
    id_map, failures, stats = import_drafts_parent_aware(
        client,  # type: ignore[arg-type]
        [_draft("only", parent_key="root", row=2)],
        project="Demo",
        id_map={"root": 10},
        id_map_path=id_map_path,
        parallel_workers=1,
        emit=lambda *_: None,
    )
    assert client.creates == 2
    assert id_map == {"root": 10, "only": 55}
    assert failures == []
    assert stats["linked"] == 0
    # ParentId left blank so backfill re-checks the link instead of trusting it.
    assert load_id_map_parents(id_map_path) == {}


def test_create_outcome_unknown_with_duplicates_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalog_runtime, "RECONCILE_DELAY_S", 0)

    class FakeClient:
        def create_work_item(self, project, wit, fields, **kwargs):
            raise AdoError("socket reset", transient=True, outcome_unknown=True)

        def find_work_item_ids(self, project, wit, **kwargs):
            return [1, 2]

    _, failures, stats = import_drafts_parent_aware(
        FakeClient(),  # type: ignore[arg-type]
        [_draft("only", row=1)],
        project="Demo",
        id_map={},
        id_map_path=tmp_path / "ado-id-map.csv",
        parallel_workers=1,
        emit=lambda *_: None,
    )
    assert stats["outcome_unknown"] == 1
    assert "2 matching work items" in failures[0]["error"]


def test_backfill_skips_links_recorded_at_create(tmp_path: Path) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.checked: list[int] = []
            self.linked: list[tuple[int, int]] = []

        def get_parent_id(self, project, child_id):
            with self.lock:
                self.checked.append(child_id)
            return {3: None, 4: 99}.get(child_id)

        def add_parent_link(self, project, child_id, parent_id, **kwargs):
            with self.lock:
                self.linked.append((child_id, parent_id))

    client = FakeClient()
    drafts = [
        _draft("root", row=1),
        _draft("a", parent_key="root", row=2),
        _draft("b", parent_key="root", row=3),
        _draft("c", parent_key="root", row=4),
    ]
    id_map = {"root": 1, "a": 2, "b": 3, "c": 4}
    counts = backfill_parent_links(
        client,  # type: ignore[arg-type]
        drafts,
        id_map,
        project="Demo",
        output_dir=tmp_path,
        emit=lambda *_: None,
        recorded_parents={"a": 1},
        parallel_workers=4,
    )
    assert sorted(client.checked) == [3, 4]
    assert client.linked == [(3, 1)]
    assert counts["linked_at_create"] == 1
    assert counts["already_linked"] == 1
    assert counts["linked"] == 1
    assert counts["conflict_existing_parent"] == 1
    with (tmp_path / "backfill-links-report.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [(r["Key"], r["Status"]) for r in rows] == [
        ("a", "already_linked"),
        ("b", "linked"),
        ("c", "conflict_existing_parent"),
    ]


def test_import_resume_skips_existing(tmp_path: Path) -> None:
    id_map_path = tmp_path / "ado-id-map.csv"
    handle, writer = open_id_map_for_append(id_map_path)
    root = _draft("root", row=1)
    append_id_map_row(writer, handle, root, 10, None)
    handle.close()

    class FakeClient:
        def __init__(self) -> None:
            self.created: list[str] = []

        def create_work_item(self, project, wit, fields, **kwargs):
            key = fields["System.Title"]
            self.created.append(key)
            return {"id": 100 + len(self.created)}

    client = FakeClient()
    drafts = [
        _draft("root", row=1),
        _draft("child", parent_key="root", row=2, title="child"),
    ]
    events: list[str] = []
    id_map = load_id_map(id_map_path)
    id_map, failures, stats = import_drafts_parent_aware(
        client,  # type: ignore[arg-type]
        drafts,
        project="Demo",
        id_map=id_map,
        id_map_path=id_map_path,
        parallel_workers=1,
        emit=lambda _s, msg: events.append(msg),
    )
    assert stats["skipped"] == 1
    assert stats["created"] == 1
    assert id_map["root"] == 10
    assert id_map["child"] == 101
    assert client.created == ["child"]
    assert failures == []
    assert any("Resume" in e for e in events)


def test_import_parallel_waits_for_parent(tmp_path: Path) -> None:
    id_map_path = tmp_path / "ado-id-map.csv"

    class FakeClient:
        def __init__(self) -> None:
            self.order: list[str] = []

        def create_work_item(self, project, wit, fields, **kwargs):
            key = fields["System.Title"]
            self.order.append(key)
            parent_id = kwargs.get("parent_id")
            if key == "child" and parent_id is None:
                raise AssertionError("child created before parent id known")
            return {"id": {"root": 1, "child": 2, "leaf": 3}[key]}

    client = FakeClient()
    drafts = [
        _draft("leaf", parent_key="child", row=3, title="leaf"),
        _draft("child", parent_key="root", row=2, title="child"),
        _draft("root", row=1, title="root"),
    ]
    id_map, failures, stats = import_drafts_parent_aware(
        client,  # type: ignore[arg-type]
        drafts,
        project="Demo",
        id_map={},
        id_map_path=id_map_path,
        parallel_workers=4,
        emit=lambda *_: None,
    )
    assert failures == []
    assert stats["created"] == 3
    assert stats["linked"] == 2
    assert id_map == {"root": 1, "child": 2, "leaf": 3}
    assert client.order[0] == "root"
