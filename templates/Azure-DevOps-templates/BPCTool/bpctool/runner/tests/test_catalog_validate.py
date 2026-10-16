"""Catalog prevalidate + multi-select token checks."""

from __future__ import annotations

from app.catalog_import import WorkItemDraft
from app.catalog_validate import (
    join_multi_select,
    prevalidate_catalog_drafts,
    split_multi_select,
)
from app.mapping import FieldDef, TemplateMapping


def _mapping() -> TemplateMapping:
    mapping = TemplateMapping()
    for fd in (
        FieldDef(
            label="Application family",
            reference_name="MSBPC.applicationfamily",
            field_type="PicklistString",
            multi_select=True,
            custom_field=True,
        ),
        FieldDef(
            label="Products",
            reference_name="MSBPC.products",
            field_type="PicklistString",
            multi_select=True,
            custom_field=True,
        ),
        FieldDef(
            label="Job purpose",
            reference_name="MSBPC.jobpurpose",
            field_type="PicklistString",
            multi_select=False,
            custom_field=True,
            required="No",
        ),
        FieldDef(
            label="Module",
            reference_name="MSBPC.module",
            field_type="PicklistString",
            multi_select=False,
            custom_field=True,
            required="No",
        ),
        FieldDef(
            label="Data type",
            reference_name="MSBPC.datatype",
            field_type="PicklistString",
            multi_select=False,
            custom_field=True,
            required="Yes",
        ),
        FieldDef(
            label="Business process flow source",
            reference_name="MSBPC.businessprocessflowsource",
            field_type="PicklistString",
            multi_select=False,
            custom_field=True,
            required="Yes",
            default_value="Microsoft",
        ),
        FieldDef(
            label="Catalog status",
            reference_name="MSBPC.catalogstatus",
            field_type="PicklistString",
            multi_select=False,
            custom_field=True,
            required="Yes",
            default_value="10 - New",
        ),
        FieldDef(
            label="Continuous",
            reference_name="MSBPC.continuous",
            field_type="Boolean",
            multi_select=False,
            custom_field=True,
            required="Yes",
            default_value="false",
        ),
    ):
        mapping.fields_by_label[fd.label.lower()] = fd
        mapping.fields_by_ref[fd.reference_name.lower()] = fd
    mapping.applicable_fields_by_wit["migration"] = {"data type"}
    mapping.applicable_fields_by_wit["job"] = {"job purpose"}
    mapping.applicable_fields_by_wit["scenario"] = {"module"}
    mapping.applicable_fields_by_wit["process"] = {
        "application family",
        "products",
        "business process flow source",
        "catalog status",
        "continuous",
    }
    mapping.applicable_fields_by_wit["test case"] = set()
    return mapping


def _ir() -> dict:
    return {
        "process": {
            "picklists": {
                "Application family": [
                    "Business Central",
                    "Finance and Operations",
                    "Customer Engagement",
                ],
                "Products": ["Business Central", "Finance", "Field Service"],
                "Job purpose": ["Integration", "Reporting"],
                "Module": [
                    "Organization administration",
                    "General ledger",
                    "Accounts payable",
                ],
                "Data type": ["Master data", "Setup data"],
                "Business process flow source": ["Microsoft", "Partner", "Customer"],
                "Catalog status": ["10 - New", "20 - Review"],
            }
        }
    }


def test_split_join_multi_select() -> None:
    assert split_multi_select("Business Central; Finance and Operations") == [
        "Business Central",
        "Finance and Operations",
    ]
    assert join_multi_select(["A", "B"]) == "A; B"


def test_prevalidate_strips_bad_area_and_test_case_state() -> None:
    drafts = [
        WorkItemDraft(
            key="t1",
            parent_key=None,
            work_item_type="Test Case",
            title="Case",
            fields={"System.State": "New", "System.AreaPath": "Not found"},
            source_file="bpc.xlsx",
            source_row=2,
        )
    ]
    result = prevalidate_catalog_drafts(drafts, _ir(), _mapping(), sanitize=True)
    assert "System.State" not in drafts[0].fields
    assert "System.AreaPath" not in drafts[0].fields
    assert result.counts.get("invalid_state") == 1
    assert result.counts.get("invalid_area_path") == 1
    assert result.fields_stripped == 2


def test_prevalidate_multi_select_tokens_and_normalize() -> None:
    drafts = [
        WorkItemDraft(
            key="10.05.080.000",
            parent_key=None,
            work_item_type="Process",
            title="Depreciation",
            fields={
                "MSBPC.applicationfamily": "Business Central;  Finance and Operations",
                "MSBPC.products": "Business Central; NotAProduct",
            },
            source_file="bpc.xlsx",
            source_row=10,
        )
    ]
    result = prevalidate_catalog_drafts(drafts, _ir(), _mapping(), sanitize=True)
    assert drafts[0].fields["MSBPC.applicationfamily"] == (
        "Business Central; Finance and Operations"
    )
    assert result.multi_select_normalized >= 1
    assert result.counts.get("invalid_multi_select_token") == 1
    # Unknown token reported but value kept (suggested multi-select storage).
    assert "MSBPC.products" in drafts[0].fields


def test_prevalidate_strips_invalid_single_picklist() -> None:
    drafts = [
        WorkItemDraft(
            key="j1",
            parent_key=None,
            work_item_type="Job",
            title="Nightly",
            fields={"MSBPC.jobpurpose": "Recurring batch"},
            source_file="deliv.xlsx",
            source_row=3,
        )
    ]
    result = prevalidate_catalog_drafts(drafts, _ir(), _mapping(), sanitize=True)
    assert "MSBPC.jobpurpose" not in drafts[0].fields
    assert result.counts.get("invalid_picklist_value") == 1


def test_prevalidate_flags_several_values_in_single_select() -> None:
    """Module is single-select in the template; 'A; B' gets its own explanation."""
    drafts = [
        WorkItemDraft(
            key="s1",
            parent_key=None,
            work_item_type="Scenario",
            title="Pay vendors",
            fields={"MSBPC.module": "Accounts payable; General ledger"},
            source_file="bpc.xlsx",
            source_row=12,
        ),
        WorkItemDraft(
            key="s2",
            parent_key=None,
            work_item_type="Scenario",
            title="Typo",
            fields={"MSBPC.module": "Acounts payable; General ledger"},
            source_file="bpc.xlsx",
            source_row=13,
        ),
    ]
    result = prevalidate_catalog_drafts(drafts, _ir(), _mapping(), sanitize=True)
    assert result.counts.get("multiple_values_single_select") == 2
    assert result.counts.get("invalid_picklist_value") is None
    assert "MSBPC.module" not in drafts[0].fields
    details = [i.detail for i in result.issues]
    assert "2 values in single-select 'Module'" in details
    assert "2 values in single-select 'Module'; not in picklist: Acounts payable" in details


def test_prevalidate_reports_repeated_key_as_automatic_fix() -> None:
    draft = WorkItemDraft(
        key="10.05.100#m3",
        parent_key=None,
        work_item_type="Process",
        title="Second row with the same ID",
        fields={"MSBPC.processsequenceid": "10.05.100"},
        source_file="bpc.xlsx",
        source_row=4,
        duplicate_of="10.05.100",
    )
    result = prevalidate_catalog_drafts([draft], _ir(), _mapping(), sanitize=True)
    assert result.counts.get("duplicate_key_renamed") == 1
    issue = result.issues[0]
    assert issue.field_label == "Tracking key (ado-id-map.csv)"
    assert issue.value == "10.05.100"
    assert issue.new_value == "10.05.100#m3"
    assert draft.fields["MSBPC.processsequenceid"] == "10.05.100"


def test_prevalidate_normalizes_picklist_casing() -> None:
    """Catalog title-case vs template sentence-case (Module)."""
    drafts = [
        WorkItemDraft(
            key="99.20.100.650",
            parent_key=None,
            work_item_type="Scenario",
            title="Org admin scenario",
            fields={"MSBPC.module": "Organization Administration"},
            source_file="bpc.xlsx",
            source_row=650,
        )
    ]
    result = prevalidate_catalog_drafts(drafts, _ir(), _mapping(), sanitize=True)
    assert drafts[0].fields["MSBPC.module"] == "Organization administration"
    assert result.counts.get("picklist_case_normalized") == 1
    assert result.counts.get("invalid_picklist_value") is None
    assert result.fields_stripped == 0


def test_prevalidate_required_empty_when_applicable() -> None:
    drafts = [
        WorkItemDraft(
            key="m1",
            parent_key=None,
            work_item_type="Migration",
            title="Customers",
            fields={},
            source_file="deliv.xlsx",
            source_row=4,
        )
    ]
    result = prevalidate_catalog_drafts(drafts, _ir(), _mapping(), sanitize=True)
    # Data type is required with no template default → still reported.
    assert result.counts.get("required_empty") == 1
    assert "MSBPC.datatype" not in drafts[0].fields


def test_removed_picklist_value_not_reported_again_as_required_empty() -> None:
    drafts = [
        WorkItemDraft(
            key="m2",
            parent_key=None,
            work_item_type="Migration",
            title="Vendors",
            fields={"MSBPC.datatype": "Data processing"},
            source_file="deliv.xlsx",
            source_row=5,
        )
    ]
    result = prevalidate_catalog_drafts(drafts, _ir(), _mapping(), sanitize=True)
    assert result.counts.get("invalid_picklist_value") == 1
    assert result.counts.get("required_empty") is None


def test_prevalidate_applies_template_defaults_for_required_empty() -> None:
    drafts = [
        WorkItemDraft(
            key="10.05.080.000",
            parent_key=None,
            work_item_type="Process",
            title="Depreciation",
            fields={},
            source_file="bpc.xlsx",
            source_row=10,
        )
    ]
    result = prevalidate_catalog_drafts(drafts, _ir(), _mapping(), sanitize=True)
    assert drafts[0].fields["MSBPC.businessprocessflowsource"] == "Microsoft"
    assert drafts[0].fields["MSBPC.catalogstatus"] == "10 - New"
    assert drafts[0].fields["MSBPC.continuous"] is False
    assert result.defaults_applied == 3
    assert result.counts.get("defaults_applied") == 3
    assert result.counts.get("required_empty") is None


def _ir_with_areas() -> dict:
    ir = _ir()
    ir["targets"] = {"project_name": "NewProj", "process_name": "P"}
    ir["project"] = {
        "area_paths": [
            {"path": "Business process catalog\\Acquire to dispose"},
            {"path": "Project name\\Functional areas\\Finance"},
        ]
    }
    return ir


def _draft(key: str, wit: str = "Scenario", **fields) -> WorkItemDraft:
    return WorkItemDraft(
        key=key,
        parent_key=None,
        work_item_type=wit,
        title=key,
        fields=dict(fields),
        source_file="bpc.xlsx",
        source_row=7,
    )


def test_project_name_placeholder_replaced_in_area_and_iteration_paths() -> None:
    draft = _draft(
        "a",
        **{
            "System.AreaPath": "Your Project Name Here\\Business process catalog",
            "System.IterationPath": "<your project name here>\\Phase 1",
        },
    )
    result = prevalidate_catalog_drafts([draft], _ir_with_areas(), _mapping())
    assert draft.fields["System.AreaPath"] == "NewProj\\Business process catalog"
    assert draft.fields["System.IterationPath"] == "NewProj\\Phase 1"
    assert result.counts == {"project_placeholder_replaced": 2}
    from app.catalog_validate import prevalidate_summary

    kinds = [g["kind"] for g in prevalidate_summary(result)["automaticFixes"]]
    assert kinds == ["project_placeholder_replaced"]


def test_iteration_path_project_prefix_is_fixed_never_removed() -> None:
    ir = _ir_with_areas()
    ir["project"]["iteration_paths"] = [
        {"path": "Phase 1 - Initiate"},
        {"path": "Phase 1 - Initiate\\Sprint 1"},
    ]
    root_only = _draft("a", **{"System.IterationPath": "MSBPCProj"})
    nested = _draft("b", **{"System.IterationPath": "MSBPCProj\\phase 1 - initiate\\Sprint 1"})
    relative = _draft("c", **{"System.IterationPath": "Phase 1 - Initiate"})
    already = _draft("d", **{"System.IterationPath": "NewProj\\Unknown sprint"})
    result = prevalidate_catalog_drafts([root_only, nested, relative, already], ir, _mapping())
    assert root_only.fields["System.IterationPath"] == "NewProj"
    assert nested.fields["System.IterationPath"] == "NewProj\\Phase 1 - Initiate\\Sprint 1"
    assert relative.fields["System.IterationPath"] == "NewProj\\Phase 1 - Initiate"
    assert already.fields["System.IterationPath"] == "NewProj\\Unknown sprint"
    assert result.counts == {"area_path_project_renamed": 3}


def test_area_path_from_another_project_is_rewritten() -> None:
    draft = _draft("a", **{"System.AreaPath": "OldProj\\Business process catalog\\Acquire to dispose"})
    result = prevalidate_catalog_drafts([draft], _ir_with_areas(), _mapping())
    assert draft.fields["System.AreaPath"] == "NewProj\\Business process catalog\\Acquire to dispose"
    assert result.counts == {"area_path_project_renamed": 1}


def test_area_path_ancestor_and_project_root_are_valid() -> None:
    ancestor = _draft("a", **{"System.AreaPath": "NewProj\\functional areas"})
    root = _draft("b", **{"System.AreaPath": "NewProj"})
    result = prevalidate_catalog_drafts([ancestor, root], _ir_with_areas(), _mapping())
    assert ancestor.fields["System.AreaPath"] == "NewProj\\Functional areas"
    assert root.fields["System.AreaPath"] == "NewProj"
    assert not result.issues


def test_unknown_area_path_is_removed_and_reported_with_row() -> None:
    draft = _draft("a", **{"System.AreaPath": "NewProj\\Supply chain\\Warehouse"})
    result = prevalidate_catalog_drafts([draft], _ir_with_areas(), _mapping())
    assert "System.AreaPath" not in draft.fields
    issue = result.issues[0]
    assert (issue.kind, issue.source_file, issue.source_row) == ("invalid_area_path", "bpc.xlsx", 7)


def test_existing_project_area_is_accepted() -> None:
    draft = _draft("a", **{"System.AreaPath": "NewProj\\Manual area"})
    result = prevalidate_catalog_drafts(
        [draft], _ir_with_areas(), _mapping(), extra_area_paths=["Manual area"]
    )
    assert draft.fields["System.AreaPath"] == "NewProj\\Manual area"
    assert not result.issues


def test_state_checked_against_live_states() -> None:
    bad = _draft("a", **{"System.State": "Deprecated"})
    good = _draft("b", **{"System.State": "active"})
    result = prevalidate_catalog_drafts(
        [bad, good], _ir(), _mapping(), allowed_states={"Scenario": ["New", "Active", "Closed"]}
    )
    assert "System.State" not in bad.fields
    assert good.fields["System.State"] == "Active"
    assert result.counts == {"invalid_state": 1, "state_case_normalized": 1}
    from app.catalog_validate import prevalidate_summary

    summary = prevalidate_summary(result)
    assert [g["kind"] for g in summary["automaticFixes"]] == ["state_case_normalized"]


def test_long_text_is_shortened() -> None:
    from app.catalog_validate import MAX_STRING_LENGTH

    mapping = _mapping()
    menu = FieldDef(label="Menu path", reference_name="MSBPC.menupath", field_type="String")
    mapping.fields_by_ref["msbpc.menupath"] = menu
    long_products = "; ".join(["Business Central"] * 30)
    draft = _draft(
        "a", **{"MSBPC.menupath": "x" * 300, "MSBPC.products": long_products, "System.Title": "t" * 260}
    )
    result = prevalidate_catalog_drafts([draft], _ir(), mapping)
    assert len(draft.fields["MSBPC.menupath"]) == MAX_STRING_LENGTH
    assert draft.fields["MSBPC.menupath"].endswith("…")
    products = draft.fields["MSBPC.products"]
    assert len(products) <= MAX_STRING_LENGTH and products.endswith("Business Central")
    assert len(draft.title) == MAX_STRING_LENGTH
    assert result.counts["text_truncated"] == 3


def test_summary_splits_review_and_automatic_and_csv(tmp_path) -> None:
    from app.catalog_validate import prevalidate_summary, write_prevalidate_csv

    drafts = [
        _draft("a", **{"System.AreaPath": "OldProj\\Business process catalog"}),
        _draft("b", **{"MSBPC.module": "Not a module"}),
    ]
    result = prevalidate_catalog_drafts(drafts, _ir_with_areas(), _mapping())
    summary = prevalidate_summary(result)
    assert [g["kind"] for g in summary["needsReview"]] == ["invalid_picklist_value"]
    assert [g["kind"] for g in summary["automaticFixes"]] == ["area_path_project_renamed"]
    assert summary["needsReviewTotal"] == 1
    path = tmp_path / "checks.csv"
    assert write_prevalidate_csv(result, path) == 2
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("Needs review?,What happened,Source file,Row")
    assert lines[1].startswith("Yes,Value is not in the picklist,bpc.xlsx,7,b")
