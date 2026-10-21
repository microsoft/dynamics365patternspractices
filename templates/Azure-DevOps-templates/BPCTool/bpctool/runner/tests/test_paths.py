"""Folder conventions: release folder discovery, artifact root, layout warnings."""

from __future__ import annotations

import os
from pathlib import Path

from app.output_folder import default_output_dir
from app.excel_ir import catalog_folder_warnings, catalog_kind
from app.paths import bpc_files_root, output_root, resolve_release_folder
from app.planner import _release_mismatch_warning


def _touch(path: Path, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_root_with_workbooks_is_the_release_folder(tmp_path: Path) -> None:
    _touch(tmp_path / "Deliverables OCT 2026.xlsx")
    _touch(tmp_path / "2026-Q3" / "Deliverables JAN 2026.xlsx")
    assert resolve_release_folder(tmp_path) == tmp_path


def test_named_release_subfolders_sort_by_name(tmp_path: Path) -> None:
    _touch(tmp_path / "2026-Q3" / "Objectives.xlsx", mtime=5_000)
    _touch(tmp_path / "2026-Q4" / "ADO template guideline (Q4).xlsx", mtime=1_000)
    _touch(tmp_path / "_archive" / "Objectives.xlsx", mtime=9_000)
    _touch(tmp_path / "notes" / "Random.xlsx", mtime=9_000)
    assert resolve_release_folder(tmp_path) == tmp_path / "2026-Q4"


def test_unnamed_release_subfolders_fall_back_to_newest_workbook(tmp_path: Path) -> None:
    _touch(tmp_path / "Spring" / "Objectives.xlsx", mtime=1_000)
    _touch(tmp_path / "Autumn" / "Objectives.xlsx", mtime=2_000)
    assert resolve_release_folder(tmp_path) == tmp_path / "Autumn"


def test_missing_or_empty_root(tmp_path: Path) -> None:
    assert resolve_release_folder(tmp_path / "missing") is None
    assert resolve_release_folder(tmp_path) is None


def test_env_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BPCTOOL_CATALOG", raising=False)
    monkeypatch.delenv("BPCTOOL_OUTPUT_DIR", raising=False)
    assert bpc_files_root() == Path.home() / "BPC Files"
    assert output_root().name == "runner-out"

    monkeypatch.setenv("BPCTOOL_CATALOG", str(tmp_path / "files"))
    monkeypatch.setenv("BPCTOOL_OUTPUT_DIR", str(tmp_path / "out"))
    assert bpc_files_root() == tmp_path / "files"
    assert default_output_dir("https://dev.azure.com/contoso", "BPC Proj") == (
        tmp_path / "out" / "contoso_BPC_Proj"
    )


def test_user_selected_output_root_keeps_org_project_folder(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BPCTOOL_OUTPUT_DIR", str(tmp_path / "env"))
    chosen = tmp_path / "chosen"
    assert default_output_dir("https://dev.azure.com/contoso", "BPC Proj", str(chosen)) == (
        chosen / "contoso_BPC_Proj"
    )
    assert default_output_dir("https://dev.azure.com/contoso", "BPC Proj", "") == (
        tmp_path / "env" / "contoso_BPC_Proj"
    )


def test_output_root_must_be_absolute(tmp_path) -> None:
    import pytest
    from pydantic import ValidationError

    from app.models import DryRunRequest

    base = {
        "org_url": "https://dev.azure.com/contoso",
        "process_name": "Proc",
        "project_name": "Proj",
        "excel_file": "/tmp/t.xlsx",
    }
    assert DryRunRequest(**base, output_root="  ").output_root is None
    absolute = str(tmp_path / "out")
    assert DryRunRequest(**base, output_root=absolute).output_root == absolute
    with pytest.raises(ValidationError):
        DryRunRequest(**base, output_root="relative/out")


def test_template_project_placeholder_replaced() -> None:
    from app.excel_ir import _apply_project_name, replace_project_placeholder

    assert replace_project_placeholder("Your Project Name Here\\Sprint 1", "Contoso") == "Contoso\\Sprint 1"
    assert replace_project_placeholder("[YOUR PROJECT NAME HERE]", "Contoso") == "Contoso"
    assert replace_project_placeholder("Business process catalog", "Contoso") == "Business process catalog"
    areas = [{"path": "Your Project Name Here\\Finance", "default_segment": "Finance"}]
    iterations = [{"path": "Your Project Name Here", "level": "1"}]
    teams = [{"name": "T", "backlog_iteration": "Your Project Name Here\\Phase 1"}]
    assert _apply_project_name(areas, iterations, teams, "Contoso") == 3
    assert areas[0]["path"] == "Contoso\\Finance"
    assert iterations[0]["path"] == "Contoso"
    assert teams[0]["backlog_iteration"] == "Contoso\\Phase 1"


def test_catalog_kind() -> None:
    assert catalog_kind(Path("Business Process Catalog OCT 2026.xlsx")) == "Business Process Catalog"
    assert catalog_kind(Path("SbD Delivery Plan.xlsx")) == "SbD Delivery Plan"
    assert catalog_kind(Path("SbD plan.xlsx")) == "SbD Delivery Plan"


def test_mixed_release_warning(tmp_path: Path) -> None:
    files = [
        {"file_name": "Deliverables JUN 2026.xlsx", "kind": "Deliverables"},
        {"file_name": "Deliverables SEP 2026.xlsx", "kind": "Deliverables"},
        {"file_name": "Objectives SEP 2026.xlsx", "kind": "Objectives"},
    ]
    warnings = catalog_folder_warnings(tmp_path, files)
    assert len(warnings) == 1
    assert "2 Deliverables workbooks" in warnings[0]


def test_root_folder_with_only_release_subfolders_warns(tmp_path: Path) -> None:
    _touch(tmp_path / "2026-Q3" / "Objectives.xlsx")
    warnings = catalog_folder_warnings(tmp_path, [])
    assert len(warnings) == 1
    assert "2026-Q3" in warnings[0]


def test_release_mismatch_warning(tmp_path: Path) -> None:
    root = tmp_path / "BPC Files"
    template = str(root / "2026-Q4" / "ADO template guideline.xlsx")
    assert _release_mismatch_warning(template, str(root / "2026-Q4")) is None
    assert "2026-Q3" in (_release_mismatch_warning(template, str(root / "2026-Q3")) or "")
    assert _release_mismatch_warning(str(tmp_path / "t.xlsx"), str(root / "2026-Q3")) is None
    assert _release_mismatch_warning(None, str(root)) is None
