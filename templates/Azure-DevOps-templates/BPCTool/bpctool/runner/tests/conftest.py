"""Shared pytest helpers. Template workbook is user-supplied (not shipped)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.excel_ir import find_template_workbook
from app.paths import bpc_files_root, resolve_release_folder


def resolve_template_path() -> Path | None:
    env = (os.environ.get("BPCTOOL_TEMPLATE") or "").strip()
    if env:
        path = Path(env).expanduser()
        return path if path.is_file() else None

    release = resolve_release_folder(bpc_files_root())
    return find_template_workbook(release) if release else None


@pytest.fixture
def template_path() -> Path:
    path = resolve_template_path()
    if path is None:
        pytest.skip(
            "ADO template guideline not found. Set BPCTOOL_TEMPLATE to the .xlsx path "
            "(or place it in the catalog folder)."
        )
    return path
