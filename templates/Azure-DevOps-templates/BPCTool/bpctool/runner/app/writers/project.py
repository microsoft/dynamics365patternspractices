"""Create/bind Azure DevOps project after process + layout."""

from __future__ import annotations

from typing import Any, Callable

from ..ado_client import AdoClient, AdoError

Emit = Callable[[str, str], None]


def apply_project(
    client: AdoClient,
    ir: dict[str, Any],
    *,
    dry_run: bool,
    emit: Emit,
    process_id: str | None = None,
) -> dict[str, Any]:
    project_name = ir["targets"]["project_name"]
    process_name = ir["targets"]["process_name"]
    description = str(ir["targets"].get("project_description") or "").strip()
    stats = {
        "project_id": None,
        "created": False,
        "existed": False,
        "description_updated": False,
    }

    if dry_run:
        desc_note = f" with description ({len(description)} chars)" if description else ""
        emit(
            "project",
            f"[dry-run] Would create/bind project '{project_name}' to process "
            f"'{process_name}'{desc_note}",
        )
        return stats

    process_id = process_id or client.get_process_id(process_name)
    if not process_id:
        raise AdoError(f'Process "{process_name}" must exist before project creation.')

    existing = client.get_project_id(project_name)
    if existing:
        _require_project_on_process(client, existing, project_name, process_id, process_name, emit)
        stats["project_id"] = existing
        stats["existed"] = True
        emit("project", f"Project already exists: {project_name} ({existing})")
        if description:
            try:
                client.update_project_description(existing, description)
                stats["description_updated"] = True
                emit("project", f"Updated project description ({len(description)} chars)")
            except AdoError as exc:
                # A warning, not a failure: Teams, Backlog and Catalog Import don't depend on it.
                stats["description_error"] = str(exc)
                stats["warnings"] = 1
                emit("project", f"WARNING: Could not update project description: {exc}")
        return stats

    project_id = client.create_project(
        project_name, process_id, description=description
    )
    if not project_id:
        raise AdoError(f'Project "{project_name}" creation did not complete in time.')
    stats["project_id"] = project_id
    stats["created"] = True
    emit(
        "project",
        f"Project created: {project_name} ({project_id})"
        + (f" — description set ({len(description)} chars)" if description else ""),
    )
    return stats


def _require_project_on_process(
    client: AdoClient,
    project_id: str,
    project_name: str,
    process_id: str,
    process_name: str,
    emit: Emit,
) -> None:
    """Later steps change the selected process, so an existing project must use it."""
    try:
        actual = client.get_project_process_id(project_id)
    except AdoError as exc:
        emit("project", f"WARNING: Could not read the process of project '{project_name}': {exc}")
        return
    if not actual:
        emit("project", f"WARNING: Azure DevOps did not report the process of project '{project_name}'")
        return
    if actual.lower() == process_id.lower():
        return
    try:
        processes = client.list_processes()
    except AdoError:
        processes = []
    actual_name = next(
        (
            str(proc.get("name"))
            for proc in processes
            if str(proc.get("typeId") or "").lower() == actual.lower()
        ),
        actual,
    )
    raise AdoError(
        f'Project "{project_name}" already exists but uses process "{actual_name}", not '
        f'"{process_name}". Layouts, backlogs and catalog work item types from this run would '
        "not apply to it. Use a different project name, or change the project's process to "
        f'"{process_name}" in Azure DevOps (Organization settings → Boards → Process) and re-run.'
    )
