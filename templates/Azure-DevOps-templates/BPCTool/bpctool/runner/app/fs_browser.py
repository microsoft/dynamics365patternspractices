"""Local filesystem listing for the path picker (absolute paths only)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .paths import bpc_files_root, resolve_release_folder


def _home() -> Path:
    return Path.home().expanduser().resolve()


def list_roots() -> list[dict[str, str]]:
    home = _home()
    roots: list[dict[str, str]] = [
        {"label": "Home", "path": str(home)},
    ]
    catalog = bpc_files_root()
    if catalog.is_dir():
        roots.append({"label": "BPC Files", "path": str(catalog.resolve())})
        release = resolve_release_folder(catalog)
        if release and release != catalog:
            roots.append({"label": f"Latest release ({release.name})", "path": str(release.resolve())})
    if os.name == "nt":
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:/")
            if drive.exists():
                roots.append({"label": f"{letter}:", "path": str(drive.resolve())})
    else:
        roots.append({"label": "/", "path": "/"})
    # de-dupe by path
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in roots:
        if item["path"] in seen:
            continue
        seen.add(item["path"])
        unique.append(item)
    return unique


def list_directory(path_str: str | None, *, directories_only: bool = False) -> dict[str, Any]:
    if path_str and path_str.strip():
        current = Path(path_str).expanduser()
        if not current.is_absolute():
            raise ValueError(
                f'Path must be absolute (got "{path_str}"). '
                "Paste a full path or pick a folder from the list."
            )
        current = current.resolve()
    else:
        current = _home()

    if current.is_file():
        current = current.parent

    if not current.exists():
        raise FileNotFoundError(f"Path not found: {current}")
    if not current.is_dir():
        raise ValueError(f"Not a directory: {current}")

    entries: list[dict[str, Any]] = []
    try:
        children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError as exc:
        raise PermissionError(f"Permission denied: {current}") from exc

    for child in children:
        name = child.name
        if name.startswith("."):
            continue
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if not is_dir:
            if directories_only or child.suffix.lower() != ".xlsx":
                continue
        entries.append(
            {
                "name": name,
                "path": str(child.resolve()),
                "kind": "dir" if is_dir else "file",
            }
        )

    parent = current.parent if current != current.parent else None
    return {
        "path": str(current),
        "parent": str(parent) if parent and parent != current else None,
        "entries": entries,
    }
