"""Catalog draft field construction."""

from __future__ import annotations

from app.catalog_import import _row_to_draft
from app.mapping import TemplateMapping


def test_row_without_description_omits_system_description() -> None:
    mapping = TemplateMapping()
    draft = _row_to_draft(
        {
            "Work item type": "Scenario",
            "Title 1": "Root scenario",
            "Process sequence ID": "99.20.100.650",
            "_source_file": "Business Process Catalog.xlsx",
            "_source_row": 3,
        },
        mapping,
    )
    assert "System.Description" not in draft.fields
    assert draft.content_formats.get("System.Description") is None
    assert draft.fields["System.Title"] == "Root scenario"


def test_row_with_description_keeps_system_description() -> None:
    mapping = TemplateMapping()
    draft = _row_to_draft(
        {
            "Work item type": "Scenario",
            "Title 1": "Root scenario",
            "Description": "Real spreadsheet text",
            "Process sequence ID": "99.20.100.650",
            "_source_file": "Business Process Catalog.xlsx",
            "_source_row": 3,
        },
        mapping,
    )
    assert draft.fields["System.Description"] == "Real spreadsheet text"
    assert "Imported from" not in str(draft.fields.get("System.Description", ""))
