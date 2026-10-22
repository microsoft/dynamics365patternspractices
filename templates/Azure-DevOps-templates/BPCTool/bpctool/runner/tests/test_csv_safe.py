"""Report CSVs people open in Excel can't run workbook or Azure DevOps text as a formula."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from app.catalog_changes import Change, write_changes_csv
from app.csv_safe import SafeDictWriter, SafeWriter, spreadsheet_safe


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=HYPERLINK(\"https://example.com\",\"x\")", "'=HYPERLINK(\"https://example.com\",\"x\")"),
        ("+1+1", "'+1+1"),
        ("-2+3", "'-2+3"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\t=1", "'\t=1"),
        ("\r=1", "'\r=1"),
        ("Order to cash", "Order to cash"),
        ("", ""),
        (-5, -5),
        (None, None),
    ],
)
def test_spreadsheet_safe(value, expected) -> None:
    assert spreadsheet_safe(value) == expected


def test_writers_neutralize_every_cell() -> None:
    plain = io.StringIO()
    SafeWriter(plain).writerow(["=1+1", "ok", 3])
    assert plain.getvalue().strip() == "'=1+1,ok,3"

    keyed = io.StringIO()
    writer = SafeDictWriter(keyed, fieldnames=["Title", "Row"])
    writer.writeheader()
    writer.writerows([{"Title": "@cmd", "Row": 4}])
    assert keyed.getvalue().splitlines() == ["Title,Row", "'@cmd,4"]


def test_changes_report_neutralizes_workbook_and_azure_devops_text(tmp_path: Path) -> None:
    path = tmp_path / "import-changes.csv"
    change = Change(
        "field_changed", "BP-1", 7, "Business Process", "=cmd|' /C calc'!A0",
        field_label="Description", current="+ADO value", workbook="-workbook value",
    )
    write_changes_csv([change], path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["Title"] == "'=cmd|' /C calc'!A0"
    assert row["Value in Azure DevOps"] == "'+ADO value"
    assert row["Value in workbook"] == "'-workbook value"
    assert row["Work item ID"] == "7"
