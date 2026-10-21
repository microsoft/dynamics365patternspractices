"""Rehearsal change report: workbook vs work items an earlier import created."""

from __future__ import annotations

import csv
import json

import pytest

from app.ado_client import AdoClient, AdoError, ReadOnlyAdoClient
from app.catalog_changes import compare_with_azure_devops, summarize_changes, write_changes_csv
from app.catalog_import import WorkItemDraft
from app.mapping import FieldDef, TemplateMapping
from app.run_outcome import build_outcome
from app.writers.catalog import CHANGES_CSV, CHANGES_JSON, _write_change_report
from app.writers.report import write_run_summary


def _mapping() -> TemplateMapping:
    mapping = TemplateMapping()
    for fd in (
        FieldDef(label="Products", reference_name="MSBPC.products", field_type="PicklistString", multi_select=True),
        FieldDef(label="Sequence", reference_name="MSBPC.sequence", field_type="Integer"),
        FieldDef(label="Notes", reference_name="MSBPC.notes", field_type="HTML"),
        FieldDef(label="Continuous", reference_name="MSBPC.continuous", field_type="Boolean"),
    ):
        mapping.fields_by_label[fd.label.lower()] = fd
        mapping.fields_by_ref[fd.reference_name.lower()] = fd
    return mapping


def _draft(key: str, fields: dict, *, parent: str | None = None, wit: str = "Process") -> WorkItemDraft:
    return WorkItemDraft(
        key=key,
        parent_key=parent,
        work_item_type=wit,
        title=fields.get("System.Title", key),
        fields={"System.Title": key, **fields},
        source_file="bpc.xlsx",
        source_row=7,
    )


def _id_map(*rows: tuple[str, int]) -> list[dict[str, str]]:
    return [{"Key": key, "WorkItemId": str(wid), "WorkItemType": "Process", "Title": key} for key, wid in rows]


class FakeReader:
    def __init__(self, items: dict[int, dict]) -> None:
        self.items = items
        self.batches: list[list[int]] = []

    def get_project_id(self, _name: str) -> str:
        return "project-guid"

    def get_work_items_batch(self, _project: str, ids: list[int]) -> list[dict]:
        self.batches.append(list(ids))
        return [{"id": i, "fields": self.items[i]} for i in ids if i in self.items]

    def find_work_items_with_field(self, _project: str, wit: str, field_ref: str) -> list[int]:
        return [
            i for i, fields in self.items.items()
            if fields.get("System.WorkItemType") == wit and fields.get(field_ref)
        ]


def _compare(reader, drafts, id_map, **kwargs):
    return compare_with_azure_devops(
        reader, drafts, id_map, _mapping(), project="Proj",
        label_for=lambda ref: ref.split(".")[-1], emit=lambda *_: None, **kwargs,
    )


def test_formatting_differences_are_not_reported_as_changes() -> None:
    reader = FakeReader({
        1: {
            "System.Title": "A", "System.WorkItemType": "Process",
            "MSBPC.products": "finance; Business Central",
            "MSBPC.sequence": 3.0,
            "MSBPC.notes": "<div>Hello&nbsp;<b>world</b></div>",
            "System.AreaPath": "proj\\sales",
            "System.AssignedTo": {"displayName": "Ann", "uniqueName": "ann@contoso.com"},
            "System.Tags": "Core; Finance",
            "MSBPC.continuous": True,
        },
    })
    draft = _draft("A", {
        "System.Tags": "finance;core",
        "MSBPC.continuous": "Yes",
        "MSBPC.products": "Business Central;Finance",
        "MSBPC.sequence": "3",
        "MSBPC.notes": "<p>Hello <strong>world</strong></p>",
        "System.AreaPath": "Proj\\Sales",
        "System.AssignedTo": "ann@contoso.com",
        "MSBPC.empty": "",
    })
    assert _compare(reader, [draft], _id_map(("A", 1))) == []


def test_reports_field_parent_type_missing_and_row_changes() -> None:
    reader = FakeReader({
        1: {"System.Title": "P", "System.WorkItemType": "Process"},
        2: {"System.Title": "Old title", "System.WorkItemType": "Scenario", "System.Parent": 9,
            "System.State": "Active", "MSBPC.products": "Finance"},
    })
    drafts = [
        _draft("P", {}),
        _draft("C", {"System.Title": "New title", "System.State": "New", "MSBPC.products": "Finance;Sales"},
               parent="P"),
        _draft("Gone", {}),
        _draft("Fresh", {}),
    ]
    id_map = _id_map(("P", 1), ("C", 2), ("Gone", 3), ("Dropped", 4))
    changes = _compare(reader, drafts, id_map)
    kinds = [(c.kind, c.key, c.field_label) for c in changes]
    assert ("type_changed", "C", "Work item type") in kinds
    assert ("parent_changed", "C", "Parent") in kinds
    assert ("missing_in_ado", "Gone", "") in kinds
    assert ("not_in_workbook", "Dropped", "") in kinds
    assert ("new_row", "Fresh", "") in kinds
    fields = {c.field_label: c for c in changes if c.kind == "field_changed"}
    assert set(fields) == {"Title", "State", "products"}
    assert fields["Title"].current == "Old title" and fields["Title"].workbook == "New title"
    assert fields["State"].team_owned and not fields["Title"].team_owned
    parent = next(c for c in changes if c.kind == "parent_changed")
    assert parent.current == "#9" and parent.workbook == "#1 (P)"

    summary = summarize_changes(changes, compared=3)
    assert summary["itemsChanged"] == 1 and summary["fieldsChanged"] == 3
    assert summary["byKind"]["new_row"] == 1 and summary["teamFieldsChanged"] == 1
    # Workbook-owned fields first, then fields usually edited in Azure DevOps.
    assert [e["field"] for e in summary["byField"]][-1] == "State"

    capped = _compare(reader, drafts, id_map, complete_workbook=False)
    assert not any(c.kind == "not_in_workbook" for c in capped)


def test_long_value_examples_start_near_the_difference() -> None:
    shared = "Plan and allocate budgets for asset maintenance. " * 5
    reader = FakeReader({1: {"System.Title": "A", "MSBPC.notes": shared + "Project notes added later."}})
    changes = _compare(reader, [_draft("A", {"MSBPC.notes": shared.strip()})], _id_map(("A", 1)))
    example = summarize_changes(changes, compared=1)["byField"][0]["examples"][0]
    assert example["current"].startswith("…") and "Project notes added later." in example["current"]
    assert example["current"] != example["workbook"]


def test_reads_in_batches_of_200() -> None:
    reader = FakeReader({i: {"System.Title": f"K{i}"} for i in range(1, 451)})
    drafts = [_draft(f"K{i}", {}) for i in range(1, 451)]
    _compare(reader, drafts, _id_map(*((f"K{i}", i) for i in range(1, 451))))
    assert sorted(len(batch) for batch in reader.batches) == [50, 200, 200]


def test_csv_opens_in_excel_with_plain_columns(tmp_path) -> None:
    reader = FakeReader({1: {"System.Title": "Old", "System.WorkItemType": "Process"}})
    changes = _compare(reader, [_draft("A", {"System.Title": "New"})], _id_map(("A", 1)))
    path = tmp_path / "changes.csv"
    write_changes_csv(changes, path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert rows == [{
        "Change": "Field value differs", "Key": "A", "Work item ID": "1", "Work item type": "Process",
        "Title": "New", "Field": "Title", "Value in Azure DevOps": "Old", "Value in workbook": "New",
        "Usually edited in": "Workbook", "Source file": "bpc.xlsx", "Source row": "7",
    }]


def test_change_report_files_and_fallbacks(tmp_path) -> None:
    def run(reader, id_map, exists=True):
        return _write_change_report(
            reader, [_draft("A", {"System.Title": "New"})], id_map, _mapping(), project="Proj",
            output_dir=tmp_path, workers=2, emit=lambda *_: None, run_id="r1", complete_workbook=True,
            project_lookup={"exists": exists, "error": "ADO 401"},
        )

    summary = run(FakeReader({1: {"System.Title": "Old"}}), _id_map(("A", 1)))
    assert summary["itemsChanged"] == 1 and summary["matchedBy"] == "id_map"
    assert json.loads((tmp_path / CHANGES_JSON).read_text())["runId"] == "r1"
    assert (tmp_path / CHANGES_CSV).is_file()

    # Neither the project nor an earlier import: nothing to compare, and the old report is removed.
    assert run(FakeReader({}), [], exists=False) == {"skipped": "nothing_to_compare", "project": "Proj"}
    assert not (tmp_path / CHANGES_CSV).exists() and not (tmp_path / CHANGES_JSON).exists()

    deleted = run(FakeReader({}), _id_map(("A", 1)), exists=False)
    assert "does not exist in Azure DevOps, but ado-id-map.csv lists 1 items" in deleted["error"]
    assert "could not check whether project 'Proj' exists: ADO 401" in run(FakeReader({}), [], exists=None)["error"]
    assert run(None, _id_map(("A", 1))) == {"skipped": "no_connection"}

    class Failing(FakeReader):
        def get_work_items_batch(self, *_args):
            raise AdoError("ADO 401: unauthorized")

    assert run(Failing({}), _id_map(("A", 1))) == {"error": "ADO 401: unauthorized"}


def test_project_without_id_map_is_matched_by_microsoft_id(tmp_path) -> None:
    def item(microsoft_id, sequence_id, title, wit="Process"):
        return {"System.WorkItemType": wit, "System.Title": title,
                "MSBPC.microsoftid": microsoft_id, "MSBPC.processsequenceid": sequence_id}

    reader = FakeReader({
        10: item("M1", "1.1", "Same"),
        11: item("M2", "9.9", "Old title"),       # sequence ID edited in ADO: matched by Microsoft ID alone
        12: item("M3", "1.3", "Twin"),
        13: item("M3", "1.3", "Twin"),            # two items for one row: not compared
        14: item("M9", "5.5", "Only in ADO"),
        15: item("M1", "1.1", "Same", wit="Scenario"),
    })
    drafts = [
        _draft("1.1", {"System.Title": "Same", "MSBPC.microsoftid": "M1", "MSBPC.processsequenceid": "1.1"}),
        _draft("1.2", {"System.Title": "New title", "MSBPC.microsoftid": "m2", "MSBPC.processsequenceid": "1.2"}),
        _draft("1.3", {"System.Title": "Twin", "MSBPC.microsoftid": "M3", "MSBPC.processsequenceid": "1.3"}),
        _draft("1.4", {"System.Title": "Brand new", "MSBPC.microsoftid": "M4", "MSBPC.processsequenceid": "1.4"}),
    ]
    summary = _write_change_report(
        reader, drafts, [], _mapping(), project="Proj", output_dir=tmp_path, workers=2,
        emit=lambda *_: None, run_id="r1", complete_workbook=True, project_lookup={"exists": True},
    )
    assert summary["matchedBy"] == "microsoft_id" and summary["rows"] == 4 and summary["compared"] == 2
    assert summary["byKind"]["exists_not_in_id_map"] == 2
    assert summary["byKind"]["ambiguous_match"] == 1 and summary["byKind"]["new_row"] == 1
    # #14 only: types with no workbook rows (Scenario #15) aren't searched.
    assert summary["byKind"]["not_in_workbook"] == 1
    rows = list(csv.DictReader((tmp_path / CHANGES_CSV).open(encoding="utf-8-sig")))
    by_change = {}
    for row in rows:
        by_change.setdefault(row["Change"], []).append(row)
    duplicate_ids = {r["Work item ID"] for r in by_change[
        "Already in Azure DevOps, not in ado-id-map.csv — a live run would create a duplicate"]}
    assert duplicate_ids == {"10", "11"}
    assert by_change["Several work items in Azure DevOps match this row"][0]["Value in Azure DevOps"] == "#12, #13"
    changed = {(r["Field"], r["Value in Azure DevOps"], r["Value in workbook"]) for r in by_change["Field value differs"]}
    assert changed == {("Title", "Old title", "New title"), ("MSBPC.processsequenceid", "9.9", "1.2")}
    assert {r["Key"] for r in by_change["In Azure DevOps, not in the workbook"]} == {""}

    outcome = build_outcome({"catalog": {"drafts": 4, "changes": summary}}, dry_run=True, output_dir=None)
    assert outcome["changes"]["summary"].startswith(
        "No ado-id-map.csv in this output folder, so workbook rows were matched to the project's "
        "work items by Microsoft ID: 2 of 4 rows matched. 1 item differs from the workbook"
    )
    assert "creates every row" in outcome["changes"]["note"]
    warning = outcome["attention"][0]
    assert warning["title"] == "2 rows already in Azure DevOps would be created again"
    assert warning["file"] == "import-changes.csv"
    assert "2 rows would be created again" in outcome["subline"]


def test_project_lookup_is_direct_and_404_means_missing(monkeypatch) -> None:
    paths: list[str] = []

    def fake_request(self, method, path, **_kw):
        paths.append(path)
        if path.endswith("/Missing%20One"):
            raise AdoError("ADO 404 Not Found", status=404)
        return {"id": "guid-1", "name": "Contoso BPC"}

    monkeypatch.setattr(AdoClient, "request", fake_request)
    client = AdoClient("https://dev.azure.com/contoso", "x" * 52)
    assert client.get_project_id("Contoso BPC") == "guid-1"
    assert client.get_project_id("Missing One") is None
    assert paths == ["/_apis/projects/Contoso%20BPC", "/_apis/projects/Missing%20One"]


def test_rehearsal_catalog_step_compares_real_workbook(template_path, tmp_path, monkeypatch) -> None:
    from app.catalog_import import load_catalog_drafts
    from app.excel_ir import build_ir
    from app.mapping import build_mapping_from_ir
    from app.paths import bpc_files_root, resolve_release_folder
    from app.writers import catalog as catalog_writer

    catalog = resolve_release_folder(bpc_files_root()) or bpc_files_root()
    ir = build_ir(str(template_path), catalog_source_dir=str(catalog),
                  process_name="Business Process Catalog", project_name="Contoso-BPC")
    drafts = load_catalog_drafts(catalog, build_mapping_from_ir(ir), limit=40)
    imported = drafts[:30]
    with (tmp_path / "ado-id-map.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Key", "WorkItemId", "WorkItemType", "Title", "ParentKey", "ParentId"])
        writer.writeheader()
        for index, draft in enumerate(imported, start=1):
            writer.writerow({"Key": draft.key, "WorkItemId": index, "WorkItemType": draft.work_item_type,
                             "Title": draft.title, "ParentKey": "", "ParentId": ""})
        writer.writerow({"Key": "retired-row", "WorkItemId": 999, "WorkItemType": "Process",
                         "Title": "Retired", "ParentKey": "", "ParentId": ""})

    class EchoReader(FakeReader):
        """Returns what the workbook would send, with one title edited in Azure DevOps."""

        def __init__(self) -> None:
            super().__init__({})
            self.gets: list[str] = []

        def get(self, path: str, **_kw) -> dict:
            self.gets.append(path)
            return {}

        def get_work_items_batch(self, project: str, ids: list[int]) -> list[dict]:
            # "" = the organization-level check of which project ado-id-map.csv belongs to.
            assert project in {"Contoso-BPC", ""}
            return [
                {"id": i, "fields": {**sent[i], "System.WorkItemType": imported[i - 1].work_item_type,
                                     **({"System.Title": "Renamed in ADO"} if i == 1 else {})}}
                for i in ids if i in sent
            ]

    sent: dict[int, dict] = {}
    id_of = {draft.key: index for index, draft in enumerate(imported, start=1)}

    def capture(reader, checked_drafts, *args, **kwargs):
        # Echo the values after data checks, i.e. what a live run would have sent.
        for draft in checked_drafts:
            if draft.key in id_of:
                sent[id_of[draft.key]] = {**draft.fields, "System.Parent": id_of.get(draft.parent_key or "")}
        return compare_with_azure_devops(reader, checked_drafts, *args, **kwargs)

    monkeypatch.setattr(catalog_writer, "compare_with_azure_devops", capture)
    reader = EchoReader()
    stats = catalog_writer.apply_catalog(None, ir, dry_run=True, emit=lambda *_: None, output_dir=tmp_path,
                                         limit=40, change_reader=reader, run_id="r1")
    changes = stats["changes"]
    assert changes["compared"] == 30
    assert changes["itemsChanged"] == 1 and changes["fieldsChanged"] == 1
    assert "Title" in changes["byField"][0]["field"]
    assert changes["byKind"]["new_row"] == 10 and changes["byKind"]["not_in_workbook"] == 0
    assert stats["skipped"] == 30 and stats["drafts"] - stats["skipped"] == 10
    assert changes["partialWorkbook"] is True
    assert any("classificationnodes/Areas" in path for path in reader.gets)
    assert stats["retired_skipped"] == 0 and not (tmp_path / "skipped-deprecated-deleted.csv").exists()


def test_rehearsal_skips_a_deprecated_row_and_labels_its_earlier_item(template_path, tmp_path, monkeypatch) -> None:
    from app.catalog_import import CATALOG_STATUS, SKIPPED_RETIRED_CSV, load_catalog_drafts
    from app.excel_ir import build_ir
    from app.paths import bpc_files_root, resolve_release_folder
    from app.writers import catalog as catalog_writer

    catalog = resolve_release_folder(bpc_files_root()) or bpc_files_root()
    ir = build_ir(str(template_path), catalog_source_dir=str(catalog),
                  process_name="Business Process Catalog", project_name="Contoso-BPC")

    def load_with_one_deprecated(*args, **kwargs):
        drafts = load_catalog_drafts(*args, **kwargs)
        parents = {d.parent_key for d in drafts}
        leaf = next(d for d in reversed(drafts) if d.key not in parents)
        leaf.fields[CATALOG_STATUS] = "65 - Deprecated (final)"
        load_with_one_deprecated.key = leaf.key
        return drafts

    monkeypatch.setattr(catalog_writer, "load_catalog_drafts", load_with_one_deprecated)
    first = load_with_one_deprecated(catalog, catalog_writer.build_mapping_from_ir(ir), limit=20)
    with (tmp_path / "ado-id-map.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Key", "WorkItemId", "WorkItemType", "Title"])
        writer.writeheader()
        for index, draft in enumerate(first, start=1):
            writer.writerow({"Key": draft.key, "WorkItemId": index, "WorkItemType": draft.work_item_type,
                             "Title": draft.title})

    class Reader(FakeReader):
        def get(self, _path, **_kw):
            return {}

    reader = Reader({i: {"System.WorkItemType": d.work_item_type} for i, d in enumerate(first, start=1)})
    stats = catalog_writer.apply_catalog(None, ir, dry_run=True, emit=lambda *_: None, output_dir=tmp_path,
                                         limit=20, change_reader=reader, run_id="r1")
    assert (stats["drafts"], stats["retired_skipped"]) == (19, 1)
    assert load_with_one_deprecated.key in (tmp_path / SKIPPED_RETIRED_CSV).read_text(encoding="utf-8-sig")
    assert stats["changes"]["byKind"]["retired_in_workbook"] == 1

    stats = catalog_writer.apply_catalog(None, ir, dry_run=True, emit=lambda *_: None, output_dir=tmp_path,
                                         limit=20, change_reader=reader, run_id="r2",
                                         include_deprecated_deleted=True)
    assert (stats["drafts"], stats["retired_skipped"]) == (20, 0)
    assert not (tmp_path / SKIPPED_RETIRED_CSV).exists()


def test_read_only_client_refuses_writes(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(AdoClient, "request", lambda self, method, path, **_kw: calls.append(method) or {})
    client = ReadOnlyAdoClient("https://dev.azure.com/contoso", "x" * 52)
    client.get("/_apis/projects")
    client.get_work_items_batch("Proj", [1, 2])
    client.find_work_items_with_field("Proj", "Process", "MSBPC.microsoftid")
    assert calls == ["GET", "POST", "POST"]
    for method, path in [
        ("POST", "/_apis/wit/workitems/$Process"),
        ("PATCH", "/_apis/wit/workitems/1"),
        ("DELETE", "/_apis/wit/workitems/1"),
        ("POST", "/_apis/wiql"),
    ]:
        with pytest.raises(AdoError, match="read-only"):
            client.request(method, path, project="Proj")
    assert calls == ["GET", "POST", "POST"]


def test_microsoft_id_search_pages_past_the_wiql_result_cap(monkeypatch) -> None:
    all_ids = list(range(1, 26))
    queries: list[tuple[str, str]] = []

    def fake_request(self, method, path, json_body=None, **_kw):
        query = json_body["query"]
        queries.append((path, query))
        after = int(query.split("[System.Id] > ")[1].split()[0])
        page = [i for i in all_ids if i > after][: self.WIQL_PAGE]
        return {"workItems": [{"id": i} for i in page]}

    monkeypatch.setattr(AdoClient, "request", fake_request)
    monkeypatch.setattr(AdoClient, "WIQL_PAGE", 10)
    client = ReadOnlyAdoClient("https://dev.azure.com/contoso", "x" * 52)
    assert client.find_work_items_with_field("Proj", "Process", "MSBPC.microsoftid") == all_ids
    assert [path for path, _query in queries] == ["/_apis/wit/wiql?$top=10"] * 3
    assert "ORDER BY [System.Id]" in queries[0][1]


def test_rehearsal_outcome_and_html_show_changes(tmp_path) -> None:
    raw = summarize_changes(
        _compare(
            FakeReader({1: {"System.Title": "Old", "System.State": "Active"}}),
            [_draft("A", {"System.Title": "New", "System.State": "New"}), _draft("B", {})],
            _id_map(("A", 1)),
        ),
        compared=1,
    )
    catalog = {"drafts": 2, "skipped": 1, "changes": raw}
    outcome = build_outcome({"catalog": catalog}, dry_run=True, output_dir=None)
    changes = outcome["changes"]
    assert changes["summary"] == "1 item of 1 imported earlier differs from the workbook (2 field values)."
    assert changes["items"] == ["1 new row — a live run would create it"]
    assert [f["field"] for f in changes["fields"]] == ["Title", "State"]
    assert "1 item already in Azure DevOps differs from the workbook." in outcome["subline"]
    assert build_outcome({"catalog": catalog}, dry_run=False, output_dir=None)["changes"] is None

    none_yet = build_outcome(
        {"catalog": {"changes": {"skipped": "nothing_to_compare", "project": "Proj"}}}, dry_run=True, output_dir=None
    )
    assert none_yet["changes"]["summary"] == (
        "Project 'Proj' doesn't exist in Azure DevOps yet and there's no earlier Catalog Import "
        "in this output folder, so there is nothing to compare."
    )

    (tmp_path / CHANGES_CSV).write_text("x", encoding="utf-8")
    ir = {"targets": {"process_name": "P", "project_name": "Proj"}, "source": {"fingerprint": "f"}, "counts": {}}
    rehearsal = write_run_summary(
        ir, step_results={"catalog": catalog}, output_dir=tmp_path, org_url="o", dry_run=True, run_id="r"
    )
    assert CHANGES_CSV in {f["name"] for f in rehearsal["files"]}
    html_text = (tmp_path / "rehearsal-summary.html").read_text(encoding="utf-8")
    assert "Changes since the last import" in html_text and "Old" in html_text
    live = write_run_summary(ir, step_results={}, output_dir=tmp_path, org_url="o", dry_run=False, run_id="r2")
    assert CHANGES_CSV not in {f["name"] for f in live["files"]}
