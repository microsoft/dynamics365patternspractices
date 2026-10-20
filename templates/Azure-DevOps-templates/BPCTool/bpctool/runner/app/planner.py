"""Build a deterministic dry-run plan from IR + target policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import ENGINE_STEPS, DryRunResponse, PlanAction

STEP_ORDER = list(ENGINE_STEPS)
# Backlog renames / creates / deletes the process's backlog levels and moves work item
# types between them, which changes every project on the process.
PROCESS_STEPS = frozenset({"process", "layout", "backlog"})


def _action(
    step_id: str,
    action: str,
    entity_type: str,
    entity_name: str,
    detail: str,
    count: int = 1,
) -> PlanAction:
    return PlanAction(
        step_id=step_id,
        action=action,  # type: ignore[arg-type]
        entity_type=entity_type,
        entity_name=entity_name,
        detail=detail,
        count=count,
    )


def _release_mismatch_warning(excel_file: str | None, catalog_dir: str | None) -> str | None:
    """Template and catalog in sibling folders usually means two different releases."""
    if not excel_file or not catalog_dir:
        return None
    template_dir = Path(excel_file).parent
    catalog = Path(catalog_dir)
    if template_dir == catalog or template_dir.parent != catalog.parent:
        return None
    return (
        f'Template is in "{template_dir.name}" but catalog workbooks are in "{catalog.name}". '
        "Use the template and catalog files from the same quarterly release."
    )


def build_dry_run_plan(
    ir: dict[str, Any],
    *,
    update_policy: str,
    confirm_process_update: bool,
    confirm_project_update: bool,
    known_process_exists: bool | None,
    known_project_exists: bool | None,
    step_filter: list[str] | None = None,
) -> DryRunResponse:
    errors: list[str] = []
    warnings: list[str] = []
    actions: list[PlanAction] = []

    process_name = ir["targets"]["process_name"]
    project_name = ir["targets"]["project_name"]
    counts = ir["counts"]

    process_exists = bool(known_process_exists)
    project_exists = bool(known_project_exists)
    selected = set(step_filter) if step_filter else set(STEP_ORDER)
    touches_process = bool(selected & PROCESS_STEPS)
    touches_project_create = "project" in selected

    unchecked = [
        label
        for label, known, touched in (
            ("process", known_process_exists, touches_process),
            ("project", known_project_exists, touches_project_create),
        )
        if known is None and touched
    ]
    if unchecked and update_policy != "always-update":
        warnings.append(
            f"Not known whether the {' and '.join(unchecked)} already exist"
            f"{'s' if len(unchecked) == 1 else ''} (existing list not fetched), so this plan treats "
            f"{'it as' if len(unchecked) == 1 else 'them as'} new. A live run checks Azure DevOps "
            "and applies the existing target policy then."
        )

    # Policy gates (UI also validates; runner enforces).
    # Scope confirmations to steps that will actually run so selected-step
    # re-runs (e.g. teams-only) are not blocked by process/project confirms.
    if update_policy == "require-confirmation":
        if process_exists and not confirm_process_update and touches_process:
            errors.append(
                f'Process "{process_name}" already exists. Confirm update before planning process / layout / backlog changes.'
            )
        if project_exists and not confirm_project_update and touches_project_create:
            errors.append(
                f'Project "{project_name}" already exists. Confirm update before planning project-phase applies.'
            )
    if update_policy == "create-only":
        if process_exists and touches_process:
            errors.append(f'Process "{process_name}" already exists and policy is create-only.')
        if project_exists and touches_project_create:
            errors.append(f'Project "{project_name}" already exists and policy is create-only.')

    process_action = "update" if process_exists else "create"
    project_action = "update" if project_exists else "create"
    if update_policy == "skip-existing" and process_exists:
        process_action = "skip"
    if update_policy == "skip-existing" and project_exists:
        project_action = "skip"

    steps = [
        {
            "id": "process",
            "title": "Process template apply",
            "depends_on": [],
            "planned_action": process_action,
            "summary": (
                f"{process_action} process '{process_name}' with "
                f"{counts['work_item_types']} WITs, {counts['fields']} fields "
                f"({counts.get('html_fields', 0)} HTML), "
                f"{counts['picklists']} picklists"
            ),
        },
        {
            "id": "layout",
            "title": "Page layouts",
            "depends_on": ["process"],
            "planned_action": "skip" if process_action == "skip" else "update",
            "summary": (
                f"Apply field/page layout mappings for {counts['fields']} field placements "
                f"including HtmlFieldControl for {counts.get('html_fields', 0)} HTML fields"
                + (
                    f"; {counts['hidden_field_placements']} hidden (H) field placements"
                    if counts.get("hidden_field_placements")
                    else ""
                )
            ),
        },
        {
            "id": "project",
            "title": "Project create/bind",
            "depends_on": ["process", "layout"],
            "planned_action": project_action,
            "summary": (
                f"{project_action} project '{project_name}' bound to process '{process_name}' "
                "(only after process + layout verify)"
            ),
        },
        {
            "id": "teams",
            "title": "Teams & areas",
            "depends_on": ["project"],
            "planned_action": "skip" if project_action == "skip" else "update",
            "summary": f"Upsert {counts['teams']} teams and {counts['area_paths']} area paths",
        },
        {
            "id": "backlog",
            "title": "Backlog & iterations",
            "depends_on": ["project", "teams"],
            "planned_action": "skip" if project_action == "skip" else "update",
            "summary": (
                f"Configure {counts['backlogs']} backlog levels and "
                f"{counts['iteration_paths']} iteration paths"
                if process_action != "skip"
                else f"Configure {counts['iteration_paths']} iteration paths and team settings; "
                "the existing process's backlog levels are left as they are (skip-existing)"
            ),
        },
        {
            "id": "catalog",
            "title": "Catalog import",
            "depends_on": ["backlog"],
            "planned_action": "import" if counts["catalog_rows"] else "skip",
            "summary": (
                f"Import {counts['catalog_rows']} catalog rows from {counts['catalog_files']} files"
                if counts["catalog_rows"]
                else "No catalog source files detected — step will be skipped"
            ),
        },
        {
            "id": "report",
            "title": "HTML/JSON report",
            "depends_on": ["catalog"],
            "planned_action": "report",
            "summary": "Generate setup/import summary artifacts",
        },
    ]

    if process_action != "skip":
        actions.append(
            _action(
                "process",
                process_action,
                "process",
                process_name,
                "Apply process shell, WITs, fields, picklists from workbook IR",
                counts["work_item_types"],
            )
        )
        actions.append(
            _action(
                "process",
                process_action,
                "work_item_type",
                f"{counts['work_item_types']} types",
                "Ensure work item types from Work item types sheet",
                counts["work_item_types"],
            )
        )
        actions.append(
            _action(
                "process",
                process_action,
                "field",
                f"{counts['fields']} fields",
                "Ensure fields from Fields sheet",
                counts["fields"],
            )
        )
    else:
        actions.append(
            _action("process", "skip", "process", process_name, "Skipped by skip-existing policy")
        )

    if process_action != "skip":
        actions.append(
            _action(
                "layout",
                "update",
                "layout",
                process_name,
                "Apply page/group/field layout placements before project creation",
                counts["fields"],
            )
        )
        actions.append(
            _action(
                "layout",
                "verify",
                "extension",
                "ms-devlabs.vsts-extensions-multivalue-control",
                "Require DevLabs Multivalue control extension (install/confirm before layout)",
            )
        )

    if project_action != "skip":
        actions.append(
            _action(
                "project",
                project_action,
                "project",
                project_name,
                "Create/bind project only after process + layout verification",
            )
        )
    else:
        actions.append(
            _action("project", "skip", "project", project_name, "Skipped by skip-existing policy")
        )

    if project_action != "skip":
        actions.append(
            _action(
                "teams",
                "update",
                "team",
                f"{counts['teams']} teams",
                "Upsert teams and area assignments",
                counts["teams"],
            )
        )
        actions.append(
            _action(
                "teams",
                "update",
                "area_path",
                f"{counts['area_paths']} paths",
                "Upsert area path tree from Area paths sheet",
                counts["area_paths"],
            )
        )
        actions.append(
            _action(
                "backlog",
                "update",
                "backlog",
                f"{counts['backlogs']} levels",
                "Configure backlog levels and iteration paths",
                counts["backlogs"],
            )
        )

    if counts["catalog_rows"]:
        for catalog_file in ir["catalog"]["files"]:
            actions.append(
                _action(
                    "catalog",
                    "import",
                    "catalog_file",
                    catalog_file["file_name"],
                    f"Import {catalog_file['row_count']} rows (resumable ID map)",
                    catalog_file["row_count"],
                )
            )
    else:
        warnings.append(
            "Catalog source directory missing or empty — add the current release's catalog workbooks to include import actions."
        )
    warnings.extend(ir["catalog"].get("warnings", []))
    release_warning = _release_mismatch_warning(
        ir["source"].get("excel_file"), ir["source"].get("catalog_source_dir")
    )
    if release_warning:
        warnings.append(release_warning)

    actions.append(
        _action(
            "report",
            "report",
            "artifact",
            "bpc-ado-setup-summary",
            "Emit HTML/JSON summary under runner-out/<org>_<project>/",
        )
    )

    if not process_name or not project_name:
        errors.append("Process name and project name are required for planning.")

    # Sequence reminder for UI
    if process_action != "skip" and project_action != "skip":
        warnings.append(
            "Hard sequence enforced: process → layout → verify → project → teams → backlog → catalog → report."
        )

    return DryRunResponse(
        ok=len(errors) == 0,
        ir_version=ir["ir_version"],
        excel_file=ir["source"]["excel_file"],
        catalog_source_dir=ir["source"]["catalog_source_dir"],
        workbook_fingerprint=ir["source"]["fingerprint"],
        summary={
            "process_name": process_name,
            "project_name": project_name,
            "process_exists": process_exists,
            "project_exists": project_exists,
            "process_action": process_action,
            "project_action": project_action,
            "update_policy": update_policy,
            "counts": counts,
            "step_order": STEP_ORDER,
            "sample_wits": [item["name"] for item in ir["process"]["work_item_types"][:8]],
            "sample_teams": [item["name"] for item in ir["project"]["teams"][:8]],
            "catalog_types": dict(list(ir["catalog"]["work_item_types"].items())[:12]),
        },
        steps=steps,
        actions=actions,
        errors=errors,
        warnings=warnings,
    )
