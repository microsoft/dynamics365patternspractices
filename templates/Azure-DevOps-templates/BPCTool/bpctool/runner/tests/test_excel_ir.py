import os
from pathlib import Path

from app.excel_ir import (
    build_ir,
    find_template_workbook,
    is_catalog_source_file,
    parse_area_paths,
)
from app.paths import bpc_files_root, resolve_release_folder
from app.planner import build_dry_run_plan

CATALOG = resolve_release_folder(bpc_files_root()) or bpc_files_root()


def test_catalog_source_file_naming():
    assert is_catalog_source_file(Path("Deliverables OCT 2026.xlsx"))
    assert is_catalog_source_file(Path("Deliverables.xlsx"))
    assert is_catalog_source_file(Path("Business Process Catalog APR 2027.xlsx"))
    assert is_catalog_source_file(Path("Objectives 2026-Q4.xlsx"))
    assert is_catalog_source_file(Path("SbD Delivery Plan JAN 2027.xlsx"))
    assert not is_catalog_source_file(Path("ADO template guideline (October).xlsx"))
    assert not is_catalog_source_file(Path("ADO template guideline.xlsx"))
    assert not is_catalog_source_file(Path("Random Notes.xlsx"))
    assert not is_catalog_source_file(Path("~$Deliverables OCT 2026.xlsx"))


def test_find_template_workbook_picks_newest_release(tmp_path):
    assert find_template_workbook(tmp_path) is None
    older = tmp_path / "ADO template guideline (Q3).xlsx"
    newer = tmp_path / "ADO template guideline (Q4).xlsx"
    older.write_bytes(b"")
    newer.write_bytes(b"")
    (tmp_path / "~$ADO template guideline (Q4).xlsx").write_bytes(b"")
    (tmp_path / "Deliverables OCT 2026.xlsx").write_bytes(b"")
    os.utime(older, (1_000, 1_000))
    os.utime(newer, (2_000, 2_000))
    assert find_template_workbook(tmp_path) == newer
    assert find_template_workbook(tmp_path / "missing") is None


def test_parse_area_paths_skips_project_column_and_keeps_hierarchy(template_path):
    areas = parse_area_paths(template_path)
    assert areas
    assert all(not a["path"].startswith("Project name") for a in areas)
    assert areas[0]["path"] == "Business process catalog"
    bpc = [a for a in areas if a["team"] == "Business process catalog"]
    assert len(bpc) >= 16
    assert any(a["path"] == "Business process catalog\\Acquire to dispose" for a in bpc)
    asset = next(a for a in areas if a["team"] == "Asset financials")
    assert asset["path"] == "Functional areas\\Finance\\Accounting\\Asset financials"
    # Multi-path teams must retain every mapped row (not just the last).
    accounting = [a["path"] for a in areas if a["team"] == "Accounting"]
    assert "Functional areas\\Finance" in accounting
    assert "Functional areas\\Finance\\Accounting" in accounting


def test_build_ir_from_template_and_catalog(template_path):
    ir = build_ir(
        str(template_path),
        catalog_source_dir=str(CATALOG),
        workbook_version="2026-Q3",
        process_name="Business Process Catalog",
        project_name="Contoso-BPC",
    )

    assert ir["counts"]["work_item_types"] >= 20
    assert ir["counts"]["disabled_work_item_types"] >= 3  # Epic, Feature, User story
    disabled = {
        w["name"] for w in ir["process"]["work_item_types"] if w.get("disabled")
    }
    assert {"Epic", "Feature", "User story"} <= disabled
    assert ir["counts"]["backlogs"] == 6
    by_backlog = {b["name"]: b for b in ir["process"]["backlogs"]}
    assert by_backlog["Levels"]["rename_from"] == "Epic"
    assert by_backlog["Lowest"]["rename_from"] == "Feature"
    assert by_backlog["Deliverables"]["rename_from"] == "(rename)"
    assert by_backlog["Highest"]["rename_from"] == "(new)"
    assert ir["counts"]["fields"] >= 50
    assert ir["counts"]["teams"] >= 10
    assert ir["counts"]["catalog_files"] == 4
    assert ir["counts"]["catalog_rows"] > 1000


def test_dry_run_plan_sequence(template_path):
    ir = build_ir(
        str(template_path),
        catalog_source_dir=str(CATALOG),
        process_name="Business Process Catalog",
        project_name="Contoso-BPC",
    )
    plan = build_dry_run_plan(
        ir,
        update_policy="always-update",
        confirm_process_update=False,
        confirm_project_update=False,
        known_process_exists=False,
        known_project_exists=False,
    )

    assert plan.ok
    assert [step["id"] for step in plan.steps] == [
        "process",
        "layout",
        "project",
        "teams",
        "backlog",
        "catalog",
        "report",
    ]
    assert plan.steps[2]["depends_on"] == ["process", "layout"]
