"""Folder conventions: BPC Files root, quarterly release subfolders, artifact root.

Recommended layout (see USER_GUIDE §2 "Folder layout")::

    ~/BPC Files/                  BPCTOOL_CATALOG (root)
      2026-Q3/                    one release per folder
        ADO template guideline (…).xlsx
        Business Process Catalog ….xlsx
        Deliverables ….xlsx
        Objectives ….xlsx
        SbD Delivery Plan ….xlsx
      2026-Q4/
      _archive/                   ignored ("." / "_" prefixes)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .excel_ir import find_template_workbook, is_catalog_source_file

BPC_FILES_DIRNAME = "BPC Files"
RELEASE_NAME_RE = re.compile(r"^\d{4}-Q[1-4]$", re.IGNORECASE)
APP_ROOT = Path(__file__).resolve().parents[2]


def bpc_files_root() -> Path:
    env = (os.environ.get("BPCTOOL_CATALOG") or "").strip()
    return Path(env).expanduser() if env else Path.home() / BPC_FILES_DIRNAME


def output_root() -> Path:
    env = (os.environ.get("BPCTOOL_OUTPUT_DIR") or "").strip()
    return Path(env).expanduser() if env else APP_ROOT / "runner-out"


def catalog_files_in(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.glob("*.xlsx") if is_catalog_source_file(path))


def has_release_content(folder: Path) -> bool:
    return bool(catalog_files_in(folder)) or find_template_workbook(folder) is not None


def release_subfolders(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        child
        for child in root.iterdir()
        if child.is_dir()
        and not child.name.startswith((".", "_"))
        and has_release_content(child)
    ]


def _latest_xlsx_mtime(folder: Path) -> float:
    times = [path.stat().st_mtime for path in folder.glob("*.xlsx") if path.is_file()]
    return max(times, default=0.0)


def resolve_release_folder(root: Path) -> Path | None:
    """``root`` itself when it holds workbooks, else its newest release subfolder.

    ``YYYY-Qn`` names win and sort by name; other names fall back to the most
    recently modified workbook inside.
    """
    if not root.is_dir():
        return None
    if has_release_content(root):
        return root
    candidates = release_subfolders(root)
    if not candidates:
        return None

    def rank(folder: Path) -> tuple[bool, str, float]:
        named = bool(RELEASE_NAME_RE.match(folder.name))
        return (named, folder.name.upper() if named else "", _latest_xlsx_mtime(folder))

    return max(candidates, key=rank)
