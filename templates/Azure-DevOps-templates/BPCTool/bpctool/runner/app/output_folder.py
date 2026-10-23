"""Per-project results folder (`<org>_<project>`), owned by exactly one Azure DevOps project.

The folder name replaces characters outside ``A-Za-z0-9._-`` with ``_``, so distinct
projects such as ``Finance Team`` and ``Finance_Team`` map to the same name. The folder's
``ado-id-map.csv`` decides which catalog rows a re-run skips, so a folder records the
project it belongs to and a different project gets its own ``<name>-<hash>`` folder.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

from .ado_client import AdoClient, AdoError
from .catalog_runtime import read_id_map_rows
from .org_url import parse_ado_org_url
from .paths import output_root

TARGET_FILE = "bpctool-target.json"
ID_MAP_FILE = "ado-id-map.csv"
ID_MAP_SAMPLE = 20


def _safe_part(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    return slug.strip("._-") or "ado"


def _org_name(org_url: str) -> str:
    parsed = parse_ado_org_url(org_url)
    return parsed.org if parsed.ok else "org"


def default_output_dir(org_url: str, project_name: str, root: str | None = None) -> Path:
    """The folder name before ownership is checked (also what older versions used)."""
    base = Path(root).expanduser() if (root or "").strip() else output_root()
    return base / _safe_part(f"{_org_name(org_url)}_{project_name}")


def _identity(org_url: str, project_name: str) -> tuple[str, str]:
    # Azure DevOps organization and project names are case-insensitive.
    return _org_name(org_url).lower(), (project_name or "").strip().lower()


def folder_owner(folder: Path) -> tuple[str, str] | None:
    """(organization, project) recorded in the folder, or None for a new / older folder."""
    try:
        data = json.loads((folder / TARGET_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return str(data.get("organization") or "").lower(), str(data.get("project") or "").strip().lower()


def resolve_output_dir(org_url: str, project_name: str, root: str | None = None) -> Path:
    """The results folder for this project: the usual name unless another project owns it."""
    folder = default_output_dir(org_url, project_name, root)
    owner = folder_owner(folder)
    identity = _identity(org_url, project_name)
    if owner is None or owner == identity:
        return folder
    digest = hashlib.sha256("|".join(identity).encode("utf-8")).hexdigest()[:8]
    return folder.with_name(f"{folder.name}-{digest}")


def _record_owner(folder: Path, org_url: str, project_name: str) -> None:
    (folder / TARGET_FILE).write_text(
        json.dumps({"organization": _org_name(org_url), "project": (project_name or "").strip()}, indent=2),
        encoding="utf-8",
    )


def settle_output_dir(
    folder: Path,
    reader: AdoClient | None,
    org_url: str,
    project_name: str,
    *,
    root: str | None,
    catalog_runs: bool,
    emit: Callable[[str], None],
    move_allowed: bool = True,
) -> Path:
    """Check ``folder``'s ado-id-map.csv against Azure DevOps and return where this run writes.

    Resume skips every key in the map, so a map listing another project's work items
    (a folder an older version shared between "Finance Team" and "Finance_Team") or
    work items that no longer exist (project deleted and created again) would make
    Catalog Import skip rows it never created here. A folder is claimed for this
    project only once its map is known to be this project's (or it has none); a map
    of another project makes that project the owner and moves this run to its own folder.
    """
    folder.mkdir(parents=True, exist_ok=True)
    owned = folder_owner(folder) is not None
    ids: list[int] = []
    for row in read_id_map_rows(folder / ID_MAP_FILE):
        try:
            ids.append(int(str(row.get("WorkItemId") or "").strip()))
        except ValueError:
            continue
    if not ids:
        if not owned:
            _record_owner(folder, org_url, project_name)
        return folder
    if reader is None:
        return folder
    sample = sorted(set(ids[: ID_MAP_SAMPLE // 2] + ids[-(ID_MAP_SAMPLE // 2) :]))
    try:
        # Organization-level read, so items in another project aren't filtered out.
        items = reader.get_work_items_batch("", sample)
    except AdoError as exc:
        emit(f"Could not check which project {ID_MAP_FILE} in '{folder.name}' belongs to: {exc}")
        return folder
    projects = {str((item.get("fields") or {}).get("System.TeamProject") or "").strip() for item in items} - {""}
    project = (project_name or "").strip()

    def refuse(message: str) -> Path:
        if catalog_runs:
            raise AdoError(message)
        emit(f"Warning: {message}")
        return folder

    if not projects:
        return refuse(
            f"None of the {len(sample)} work items checked from {ID_MAP_FILE} in results folder "
            f"'{folder.name}' exist in Azure DevOps any more (or this PAT can't read them) — the project "
            "may have been deleted and created again. Catalog Import would skip those rows instead of "
            f"creating them. Move {ID_MAP_FILE} out of that folder (keep a copy) or choose another Run "
            "output folder, then run again."
        )
    if any(name.casefold() == project.casefold() for name in projects):
        if not owned:
            _record_owner(folder, org_url, project)
        return folder
    if not owned and len(projects) == 1 and move_allowed:
        (owner,) = projects
        _record_owner(folder, org_url, owner)
        own = resolve_output_dir(org_url, project, root)
        emit(
            f"Results folder '{folder.name}' holds the imported-items list of project '{owner}', so it now "
            f"belongs to '{owner}'; this project's results go to '{own.name}'."
        )
        return settle_output_dir(
            own, reader, org_url, project, root=root, catalog_runs=catalog_runs, emit=emit, move_allowed=False
        )
    return refuse(
        f"{ID_MAP_FILE} in results folder '{folder.name}' lists work items from project "
        f"'{', '.join(sorted(projects))}', not '{project}'. Catalog Import would skip those rows instead "
        f"of creating them in '{project}'. Choose another Run output folder for this project, or move "
        "that folder's files somewhere else, then run again."
    )


def folder_lock_key(org_url: str, project_name: str) -> str:
    """Runs sharing this key could write the same folder, so only one may run at a time."""
    return _safe_part(f"{_org_name(org_url)}_{project_name}").lower()
