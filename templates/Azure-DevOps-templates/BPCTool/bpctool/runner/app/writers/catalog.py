"""Import catalog work items with HTML/markdown-normalized rich text."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from ..ado_client import AdoClient, AdoError
from ..catalog_changes import (
    compare_with_azure_devops,
    match_by_microsoft_id,
    summarize_changes,
    write_changes_csv,
)
from ..catalog_import import (
    SKIPPED_RETIRED_CSV,
    SkippedDraft,
    is_retired,
    load_catalog_drafts,
    split_retired_drafts,
    write_skipped_csv,
)
from ..catalog_runtime import (
    Progress,
    ShouldCancel,
    backfill_parent_links,
    clamp_parallel_workers,
    import_drafts_parent_aware,
    load_id_map,
    load_id_map_parents,
    read_id_map_rows,
)
from ..catalog_validate import (
    prevalidate_catalog_drafts,
    prevalidate_summary,
    write_prevalidate_csv,
)
from ..failure_explain import enrich_failures, summarize_failures, write_failures_csv
from ..mapping import TemplateMapping, build_mapping_from_ir
from ..run_outcome import catalog_placeholder_count, project_name_notice

Emit = Callable[[str, str], None]

CHANGES_CSV = "import-changes.csv"
CHANGES_JSON = "import-changes.json"


def apply_catalog(
    client: AdoClient,
    ir: dict[str, Any],
    *,
    dry_run: bool,
    emit: Emit,
    output_dir: Path,
    limit: int | None = None,
    convert_markdown_to_html: bool = False,
    include_deprecated_deleted: bool = False,
    parallel_workers: int | None = None,
    progress: Progress | None = None,
    should_cancel: ShouldCancel | None = None,
    run_id: str = "",
    area_root: str = "",
    change_reader: AdoClient | None = None,
) -> dict[str, Any]:
    """``change_reader`` (rehearsal only) is used for reads, never writes."""
    project = ir["targets"]["project_name"]
    catalog_dir = ir["source"].get("catalog_source_dir")
    workers = clamp_parallel_workers(parallel_workers)
    stats: dict[str, Any] = {
        "drafts": 0,
        "created": 0,
        "skipped": 0,
        "failed": 0,
        "linked": 0,
        "missing_parent": 0,
        "cancelled": 0,
        "backfill": {},
        "parallel_workers": workers,
        "prevalidate": {},
        "html_fields_normalized": 0,
        "markdown_preserved": 0,
        "markdown_converted": 0,
        "html_passthrough": 0,
        "convert_markdown_to_html": convert_markdown_to_html,
        "id_map_path": None,
    }

    if not catalog_dir or not ir["counts"].get("catalog_rows"):
        emit("catalog", "No catalog sources — skipped")
        return stats

    mapping = build_mapping_from_ir(ir)
    drafts = load_catalog_drafts(
        catalog_dir,
        mapping,
        limit=limit,
        convert_markdown_to_html=convert_markdown_to_html,
    )
    retired: list[SkippedDraft] = []
    if not include_deprecated_deleted:
        drafts, retired = split_retired_drafts(drafts)
    stats["drafts"] = len(drafts)
    stats["retired_skipped"] = len(retired)

    for draft in drafts:
        for kind in draft.content_formats.values():
            stats["html_fields_normalized"] += 1
            if kind == "markdown":
                stats["markdown_preserved"] += 1
            elif kind == "markdown→html":
                stats["markdown_converted"] += 1
            elif kind == "html":
                stats["html_passthrough"] += 1

    mode_label = (
        f"markdown→HTML {stats['markdown_converted']}"
        if convert_markdown_to_html
        else f"markdown preserved {stats['markdown_preserved']}"
    )
    emit(
        "catalog",
        f"Prepared {len(drafts)} drafts "
        f"({mode_label}, HTML passthrough {stats['html_passthrough']})",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    skipped_path = output_dir / SKIPPED_RETIRED_CSV
    if retired:
        write_skipped_csv(retired, skipped_path)
        direct = sum(1 for item in retired if is_retired(item.draft))
        below = len(retired) - direct
        emit(
            "catalog",
            f"Skipped {len(retired)} Deprecated / Deleted catalog row(s)"
            + (f" ({direct} with that Catalog status, {below} below them)" if below else "")
            + f" — not imported. List: {skipped_path.name}",
        )
    else:
        skipped_path.unlink(missing_ok=True)
        if include_deprecated_deleted:
            emit("catalog", "Including Deprecated / Deleted catalog rows (they are imported like any other row)")
    id_map_path = output_dir / "ado-id-map.csv"
    failures_path = output_dir / "import-failures.json"
    failures_csv_path = output_dir / "import-failures.csv"
    preview_path = output_dir / "import-preview.csv"

    # Always write a preview sample showing normalized rich text.
    with preview_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Key",
                "WorkItemType",
                "Title",
                "DescriptionFormat",
                "DescriptionSample",
                "SourceFile",
                "SourceRow",
            ],
        )
        writer.writeheader()
        for draft in drafts[:50]:
            description = str(draft.fields.get("System.Description") or "")
            writer.writerow(
                {
                    "Key": draft.key,
                    "WorkItemType": draft.work_item_type,
                    "Title": draft.title,
                    "DescriptionFormat": draft.content_formats.get(
                        "System.Description", ""
                    ),
                    "DescriptionSample": description[:240],
                    "SourceFile": draft.source_file,
                    "SourceRow": draft.source_row,
                }
            )

    with_parent = sum(1 for d in drafts if d.parent_key)
    emit(
        "catalog",
        f"Hierarchy: {with_parent}/{len(drafts)} drafts have a parent key "
        f"(Title 1..N outline / ADO CSV style)",
    )

    id_map_rows = read_id_map_rows(id_map_path)
    project_lookup = _rehearsal_project_lookup(change_reader, project, emit) if dry_run else {}
    context_client = (
        (change_reader if project_lookup.get("exists") else None) if dry_run else client
    )
    extra_areas, allowed_states = _live_project_context(
        context_client, project, {d.work_item_type for d in drafts if d.fields.get("System.State")}, emit
    )
    pre = prevalidate_catalog_drafts(
        drafts,
        ir,
        mapping,
        sanitize=True,
        project=project,
        extra_area_paths=extra_areas,
        allowed_states=allowed_states,
        area_root=area_root,
    )
    summary = prevalidate_summary(pre)
    stats["prevalidate"] = summary
    prevalidate_path = output_dir / "import-prevalidate.json"
    prevalidate_csv = output_dir / "import-prevalidate.csv"
    prevalidate_path.write_text(
        json.dumps({**_run_stamp(run_id), **summary}, indent=2), encoding="utf-8"
    )
    write_prevalidate_csv(pre, prevalidate_csv)
    placeholder_notice = project_name_notice(
        project, template_rows=0, catalog_values=catalog_placeholder_count(summary)
    )
    if placeholder_notice:
        emit("catalog", placeholder_notice)
    if summary["needsReviewTotal"] or summary["automaticFixesTotal"]:
        review = "; ".join(f"{g['label']}: {g['count']}" for g in summary["needsReview"]) or "none"
        emit(
            "catalog",
            f"Data checks: {summary['needsReviewTotal']} value(s) need review ({review}); "
            f"{summary['automaticFixesTotal']} fixed automatically. "
            f"Full list: {prevalidate_csv.name}",
        )
    else:
        emit("catalog", "Data checks: no issues found")

    if dry_run:
        existing = load_id_map(id_map_path)
        remaining = sum(1 for d in drafts if d.key not in existing)
        emit(
            "catalog",
            f"[dry-run] Preview written ({preview_path.name}); "
            f"would import {remaining} of {len(drafts)} work items "
            f"({len(existing)} already in id-map) with {workers} worker(s), "
            + (
                "markdown→HTML, "
                if convert_markdown_to_html
                else "preserving markdown (multilineFieldsFormat=Markdown), "
            )
            + "then parent-link backfill",
        )
        # Only workbook rows count; the map may list items no longer in the workbook.
        stats["skipped"] = len(drafts) - remaining
        stats["id_map_path"] = str(preview_path)
        stats["changes"] = _write_change_report(
            change_reader,
            drafts,
            id_map_rows,
            mapping,
            project=project,
            output_dir=output_dir,
            workers=workers,
            emit=emit,
            run_id=run_id,
            complete_workbook=limit is None,
            project_lookup=project_lookup,
            retired=[item.draft for item in retired],
        )
        return stats

    id_map = load_id_map(id_map_path)
    id_map, failures, create_stats = import_drafts_parent_aware(
        client,
        drafts,
        project=project,
        id_map=id_map,
        id_map_path=id_map_path,
        parallel_workers=workers,
        emit=emit,
        progress=progress,
        should_cancel=should_cancel,
    )
    stats.update(create_stats)
    drafts_by_key = {draft.key: draft for draft in drafts}
    enrich_failures(failures, drafts_by_key, label_for=_label_lookup(mapping))
    failure_summary = summarize_failures(failures)
    stats["failure_summary"] = failure_summary
    failures_path.write_text(
        json.dumps(
            {**_run_stamp(run_id), "summary": failure_summary, "failures": failures}, indent=2
        ),
        encoding="utf-8",
    )
    write_failures_csv(failures, failures_csv_path)
    if failures:
        emit(
            "catalog",
            f"{failure_summary['rootCauses']} row(s) failed and blocked "
            f"{failure_summary['blockedByParent']} child row(s); "
            f"see {failures_csv_path.name}",
        )
    stats["id_map_path"] = str(id_map_path)

    if should_cancel is not None and should_cancel():
        emit("catalog", "Cancelled before parent-link backfill; re-run to resume and backfill")
        stats["backfill"] = {"skipped": "cancelled"}
    else:
        backfill_stats = backfill_parent_links(
            client,
            drafts,
            id_map,
            project=project,
            output_dir=output_dir,
            emit=emit,
            recorded_parents=load_id_map_parents(id_map_path),
            parallel_workers=workers,
            progress=progress,
            should_cancel=should_cancel,
        )
        stats["backfill"] = backfill_stats
        # Count backfill links toward linked when create missed the relation.
        stats["linked"] = int(stats.get("linked") or 0) + int(
            backfill_stats.get("linked") or 0
        )

    emit(
        "catalog",
        f"Catalog import finished: created {stats['created']}, "
        f"skipped {stats['skipped']}, linked {stats['linked']}, "
        f"missing parent {stats['missing_parent']}, failed {stats['failed']}"
        + (f", cancelled {stats['cancelled']}" if stats.get("cancelled") else "")
        + (f", reconciled {stats['reconciled']}" if stats.get("reconciled") else "")
        + f", workers {workers}",
    )
    return stats


def _write_change_report(
    reader: AdoClient | None,
    drafts: list[Any],
    id_map_rows: list[dict[str, str]],
    mapping: TemplateMapping,
    *,
    project: str,
    output_dir: Path,
    workers: int,
    emit: Emit,
    run_id: str,
    complete_workbook: bool,
    project_lookup: dict[str, Any],
    retired: list[Any] = (),
) -> dict[str, Any]:
    """Rehearsal: compare the workbook with the work items already in the project.

    Items come from ado-id-map.csv, or, when there is none but the project exists,
    from matching rows to the project's work items by Microsoft ID. ``retired`` rows
    (skipped Deprecated / Deleted) are matched only to label their existing items.
    """
    csv_path = output_dir / CHANGES_CSV
    json_path = output_dir / CHANGES_JSON
    for stale in (csv_path, json_path):
        stale.unlink(missing_ok=True)
    if reader is None:
        emit("catalog", "Changes: not compared — no valid PAT to read Azure DevOps")
        return {"skipped": "no_connection"}
    exists = project_lookup.get("exists")
    if exists is None:
        error = f"could not check whether project '{project}' exists: {project_lookup.get('error')}"
        emit("catalog", f"Changes: {error}")
        return {"error": error}
    if not exists:
        if id_map_rows:
            error = (
                f"project '{project}' does not exist in Azure DevOps, but ado-id-map.csv lists "
                f"{len(id_map_rows):,} items from an earlier import — the project was deleted or renamed"
            )
            emit("catalog", f"Changes: {error}")
            return {"error": error}
        emit("catalog", f"Changes: project '{project}' doesn't exist yet and there's no earlier Catalog Import — nothing to compare")
        return {"skipped": "nothing_to_compare", "project": project}

    label_for = _label_lookup(mapping)
    try:
        if id_map_rows:
            matched_by = "id_map"
            rows, items, ambiguous = id_map_rows, None, None
        else:
            matched_by = "microsoft_id"
            emit("catalog", "Changes: no ado-id-map.csv in this output folder — matching rows to the project's work items by Microsoft ID")
            rows, items, ambiguous = match_by_microsoft_id(
                reader, [*drafts, *retired], project=project, workers=workers, emit=emit
            )
            kept = {draft.key for draft in drafts}
            ambiguous = [change for change in ambiguous if change.key in kept]
        changes = compare_with_azure_devops(
            reader,
            drafts,
            rows,
            mapping,
            project=project,
            label_for=label_for,
            workers=workers,
            emit=emit,
            complete_workbook=complete_workbook,
            items=items,
            ambiguous=ambiguous,
            retired_keys={draft.key for draft in retired},
        )
    except AdoError as exc:
        emit("catalog", f"Changes: could not read work items from Azure DevOps (report skipped): {exc}")
        return {"error": str(exc)}
    matched_keys = {str(row.get("Key") or "").strip() for row in rows}
    compared = sum(1 for draft in drafts if draft.key in matched_keys)
    summary = summarize_changes(changes, compared=compared)
    summary.update(matchedBy=matched_by, rows=len(drafts))
    if not complete_workbook:
        summary["partialWorkbook"] = True
    write_changes_csv(changes, csv_path)
    json_path.write_text(json.dumps({**_run_stamp(run_id), **summary}, indent=2), encoding="utf-8")
    duplicates = summary["byKind"]["exists_not_in_id_map"]
    emit(
        "catalog",
        f"Changes: {summary['itemsChanged']} of {compared} existing item(s) differ from the workbook "
        f"({summary['fieldsChanged']} field value(s)); "
        f"{summary['byKind']['new_row']} new row(s)"
        + (f"; {duplicates} row(s) a live run would create again (not in ado-id-map.csv)" if duplicates else "")
        + f". Full list: {csv_path.name}",
    )
    return summary


def _rehearsal_project_lookup(reader: AdoClient | None, project: str, emit: Emit) -> dict[str, Any]:
    """``exists``: True / False, or None when Azure DevOps couldn't be asked."""
    if reader is None:
        return {"exists": None, "error": "no valid PAT"}
    try:
        exists = reader.get_project_id(project) is not None
    except AdoError as exc:
        emit("catalog", f"Could not check whether project '{project}' exists: {exc}")
        return {"exists": None, "error": str(exc)}
    emit(
        "catalog",
        f"Project '{project}' exists in Azure DevOps — data checks use its area paths and states"
        if exists
        else f"Project '{project}' doesn't exist in Azure DevOps yet — data checks use the template only",
    )
    return {"exists": exists}


def _run_stamp(run_id: str) -> dict[str, str]:
    return {"runId": run_id, "generatedAt": datetime.now(timezone.utc).isoformat()}


def _label_lookup(mapping: TemplateMapping):
    builtin = {
        "system.areapath": "Area path",
        "system.iterationpath": "Iteration path",
        "system.state": "State",
        "system.title": "Title",
    }

    def label_for(ref: str) -> str:
        fd = mapping.field_def(ref) if ref else None
        return (fd.label if fd and fd.label else None) or builtin.get(ref.lower(), ref)

    return label_for


def _live_project_context(
    client: AdoClient | None, project: str, state_wits: set[str], emit: Emit
) -> tuple[list[str], dict[str, list[str]] | None]:
    """Area paths already in the project and allowed states per work item type."""
    if client is None:
        return [], None
    areas: list[str] = []
    try:
        root = client.get(
            "/_apis/wit/classificationnodes/Areas?$depth=14", project=project, api_version="7.1"
        ) or {}
        stack = [(root, [])]
        while stack:
            node, parents = stack.pop()
            path = [*parents, str(node.get("name") or "")] if parents or node is not root else []
            if path:
                areas.append("\\".join(path))
            for child in node.get("children") or []:
                stack.append((child, path))
    except AdoError as exc:
        emit("catalog", f"Could not read project area paths (checking against template only): {exc}")
    states: dict[str, list[str]] = {}
    for wit in sorted(state_wits):
        try:
            data = client.get(
                f"/_apis/wit/workitemtypes/{quote(wit, safe='')}/states",
                project=project,
                api_version="7.1",
            ) or {}
            names = [str(item.get("name")) for item in data.get("value") or [] if item.get("name")]
            if names:
                states[wit] = names
        except AdoError as exc:
            emit("catalog", f"Could not read states for '{wit}' (not checked): {exc}")
    return areas, states or None
