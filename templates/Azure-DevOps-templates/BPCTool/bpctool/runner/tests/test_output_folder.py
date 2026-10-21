"""Results folders belong to one Azure DevOps project; resume maps are checked against it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.ado_client import AdoError
from app.output_folder import (
    TARGET_FILE,
    default_output_dir,
    folder_lock_key,
    folder_owner,
    resolve_output_dir,
    settle_output_dir,
)

ORG = "https://dev.azure.com/contoso"


class BatchReader:
    """Work items 100–149 live in ``project``; None = none of them exist any more."""

    def __init__(self, project: str | None) -> None:
        self.project = project
        self.calls: list[tuple[str, list[int]]] = []

    def get_work_items_batch(self, project: str, ids: list[int]) -> list[dict[str, Any]]:
        self.calls.append((project, ids))
        if self.project is None:
            return []
        return [{"id": i, "fields": {"System.TeamProject": self.project}} for i in ids]


def _with_id_map(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"K{n},{100 + n}\n" for n in range(50))
    (folder / "ado-id-map.csv").write_text("Key,WorkItemId\n" + rows, encoding="utf-8")
    return folder


def _settle(folder: Path, reader: Any, project: str, root: Path, *, catalog: bool = True) -> tuple[Path, list[str]]:
    messages: list[str] = []
    settled = settle_output_dir(
        folder, reader, ORG, project, root=str(root), catalog_runs=catalog, emit=messages.append
    )
    return settled, messages


def test_projects_with_the_same_folder_name_get_separate_folders(tmp_path: Path) -> None:
    root = str(tmp_path)
    assert default_output_dir(ORG, "Finance Team", root) == default_output_dir(ORG, "Finance_Team", root)

    first, _ = _settle(resolve_output_dir(ORG, "Finance_Team", root), None, "Finance_Team", tmp_path)
    second = resolve_output_dir(ORG, "Finance Team", root)

    assert first.name == "contoso_Finance_Team"
    assert second.name.startswith("contoso_Finance_Team-") and second != first
    assert resolve_output_dir(ORG, "Finance Team", root) == second
    assert folder_owner(first) == ("contoso", "finance_team")


def test_an_older_folder_is_claimed_once_its_id_map_is_this_projects(tmp_path: Path) -> None:
    legacy = _with_id_map(default_output_dir(ORG, "Finance Team", str(tmp_path)))
    reader = BatchReader("finance team")

    settled, _ = _settle(resolve_output_dir(ORG, "Finance Team", str(tmp_path)), reader, "Finance Team", tmp_path)

    assert settled == legacy
    assert folder_owner(legacy) == ("contoso", "finance team")
    project, ids = reader.calls[0]
    assert project == "" and len(ids) <= 20


def test_an_older_folder_is_not_claimed_without_checking_its_id_map(tmp_path: Path) -> None:
    legacy = _with_id_map(default_output_dir(ORG, "Finance Team", str(tmp_path)))

    settled, _ = _settle(legacy, None, "Finance Team", tmp_path)

    assert settled == legacy
    assert not (legacy / TARGET_FILE).exists()


@pytest.mark.parametrize("catalog", [True, False])
def test_an_older_folder_with_another_projects_id_map_goes_to_that_project(tmp_path: Path, catalog: bool) -> None:
    legacy = _with_id_map(default_output_dir(ORG, "Finance Team", str(tmp_path)))

    settled, messages = _settle(legacy, BatchReader("Finance_Team"), "Finance Team", tmp_path, catalog=catalog)

    assert folder_owner(legacy) == ("contoso", "finance_team")
    assert settled == resolve_output_dir(ORG, "Finance Team", str(tmp_path)) != legacy
    assert folder_owner(settled) == ("contoso", "finance team")
    assert "now belongs to 'Finance_Team'" in messages[0]
    # The real owner keeps its folder and its map.
    assert resolve_output_dir(ORG, "Finance_Team", str(tmp_path)) == legacy


def test_this_projects_folder_with_another_projects_id_map_stops_catalog_import(tmp_path: Path) -> None:
    folder = _with_id_map(default_output_dir(ORG, "Finance Team", str(tmp_path)))
    (folder / TARGET_FILE).write_text('{"organization": "contoso", "project": "Finance Team"}', encoding="utf-8")

    with pytest.raises(AdoError, match="lists work items from project 'Payroll', not 'Finance Team'"):
        _settle(folder, BatchReader("Payroll"), "Finance Team", tmp_path)
    settled, messages = _settle(folder, BatchReader("Payroll"), "Finance Team", tmp_path, catalog=False)
    assert settled == folder and messages[0].startswith("Warning:")


def test_an_id_map_whose_items_no_longer_exist_stops_catalog_import(tmp_path: Path) -> None:
    folder = _with_id_map(default_output_dir(ORG, "Finance Team", str(tmp_path)))

    with pytest.raises(AdoError, match="exist in Azure DevOps any more"):
        _settle(folder, BatchReader(None), "Finance Team", tmp_path)
    assert not (folder / TARGET_FILE).exists()

    settled, messages = _settle(folder, BatchReader(None), "Finance Team", tmp_path, catalog=False)
    assert settled == folder and "deleted and created again" in messages[0]


def test_unreadable_azure_devops_leaves_the_folder_as_is(tmp_path: Path) -> None:
    class Failing:
        def get_work_items_batch(self, *_a: Any) -> list[dict[str, Any]]:
            raise AdoError("401 Unauthorized", status=401)

    folder = _with_id_map(default_output_dir(ORG, "Finance Team", str(tmp_path)))
    settled, messages = _settle(folder, Failing(), "Finance Team", tmp_path)
    assert settled == folder and "Could not check" in messages[0]
    assert not (folder / TARGET_FILE).exists()


def test_runs_that_share_a_folder_name_share_the_run_lock() -> None:
    assert folder_lock_key(ORG, "Finance Team") == folder_lock_key(ORG, "finance_team")
    assert folder_lock_key(ORG, "Finance Team") != folder_lock_key(ORG, "Payroll")
