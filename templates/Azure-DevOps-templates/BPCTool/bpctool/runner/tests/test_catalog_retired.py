"""Deprecated / Deleted catalog rows are skipped by default, like the Microsoft importer."""

from __future__ import annotations

import csv

from app.catalog_changes import compare_with_azure_devops
from app.catalog_import import (
    CATALOG_STATUS,
    SKIPPED_RETIRED_CSV,
    WorkItemDraft,
    split_retired_drafts,
    write_skipped_csv,
)
from app.mapping import TemplateMapping
from app.run_outcome import build_outcome


def _draft(key: str, status: str = "40 - Published", parent: str | None = None) -> WorkItemDraft:
    return WorkItemDraft(
        key=key,
        parent_key=parent,
        work_item_type="Process",
        title=f"Title {key}",
        fields={"System.Title": f"Title {key}", CATALOG_STATUS: status},
        source_file="bpc.xlsx",
        source_row=7,
    )


def test_retired_rows_and_everything_below_them_are_skipped(tmp_path) -> None:
    drafts = [
        _draft("1"),
        _draft("1.1", "65 - Deprecated (final)", parent="1"),
        _draft("1.1.1", parent="1.1"),
        _draft("1.1.1.1", parent="1.1.1"),
        _draft("1.2", "DELETED", parent="1"),
        _draft("1.3", parent="1"),
        _draft("2", ""),
    ]
    kept, skipped = split_retired_drafts(drafts)
    assert [d.key for d in kept] == ["1", "1.3", "2"]
    reasons = {item.draft.key: item.reason for item in skipped}
    assert reasons == {
        "1.1": "Catalog status is '65 - Deprecated (final)'",
        "1.1.1": "Parent row 1.1 is skipped",
        "1.1.1.1": "Parent row 1.1.1 is skipped",
        "1.2": "Catalog status is 'DELETED'",
    }

    path = tmp_path / SKIPPED_RETIRED_CSV
    write_skipped_csv(skipped, path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0] == {
        "Key": "1.1", "Work item type": "Process", "Title": "Title 1.1",
        "Catalog status": "65 - Deprecated (final)", "Why skipped": "Catalog status is '65 - Deprecated (final)'",
        "Source file": "bpc.xlsx", "Source row": "7",
    }


def test_items_imported_before_a_row_was_retired_get_their_own_change_kind() -> None:
    class Reader:
        def get_work_items_batch(self, _project, ids):
            return [{"id": i, "fields": {"System.Title": "Title A", "System.WorkItemType": "Process"}} for i in ids]

    id_map = [
        {"Key": key, "WorkItemId": str(i), "WorkItemType": "Process", "Title": key}
        for i, key in enumerate(["A", "OLD", "GONE"], start=1)
    ]
    for complete in (True, False):
        changes = compare_with_azure_devops(
            Reader(), [_draft("A")], id_map, TemplateMapping(), project="Proj",
            label_for=str, emit=lambda *_: None, complete_workbook=complete, retired_keys={"OLD"},
        )
        kinds = {c.key: c.kind for c in changes if c.kind != "field_changed"}
        expected = {"OLD": "retired_in_workbook"} | ({"GONE": "not_in_workbook"} if complete else {})
        assert kinds == expected


def test_outcome_lists_skipped_rows_and_the_change_kind() -> None:
    catalog = {
        "drafts": 10,
        "skipped": 0,
        "retired_skipped": 700,
        "changes": {"compared": 3, "itemsChanged": 0, "byKind": {"retired_in_workbook": 2}, "byField": []},
    }
    outcome = build_outcome({"catalog": catalog}, dry_run=True, output_dir=None)
    first = outcome["automaticFixes"][0]
    assert (first["kind"], first["count"]) == ("retired_rows_skipped", 700)
    assert SKIPPED_RETIRED_CSV in first["outcome"]
    assert outcome["changes"]["items"] == [
        "2 items in Azure DevOps are Deprecated or Deleted in the workbook — close or remove them by hand if no longer needed"
    ]
