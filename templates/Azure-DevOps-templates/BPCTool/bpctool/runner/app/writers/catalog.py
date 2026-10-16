"""Import catalog work items with HTML/markdown-normalized rich text."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from ..ado_client import AdoClient, AdoError
from ..catalog_import import load_catalog_drafts
from ..catalog_runtime import (
    Progress,
    ShouldCancel,
    backfill_parent_links,
    clamp_parallel_workers,
    import_drafts_parent_aware,
    load_id_map,
    load_id_map_parents,
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


def apply_catalog(
    client: AdoClient,
    ir: dict[str, Any],
    *,
    dry_run: bool,
    emit: Emit,
    output_dir: Path,
    limit: int | None = None,
    convert_markdown_to_html: bool = False,
    parallel_workers: int | None = None,
    progress: Progress | None = None,
    should_cancel: ShouldCancel | None = None,
    run_id: str = "",
) -> dict[str, Any]:
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
    stats["drafts"] = len(drafts)

    for draft in drafts:
        for ref, kind in draft.content_formats.items():
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

    extra_areas, allowed_states = ([], None) if dry_run else _live_project_context(
        client, project, {d.work_item_type for d in drafts if d.fields.get("System.State")}, emit
    )
    pre = prevalidate_catalog_drafts(
        drafts,
        ir,
        mapping,
        sanitize=True,
        project=project,
        extra_area_paths=extra_areas,
        allowed_states=allowed_states,
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
        stats["skipped"] = len(existing)
        stats["id_map_path"] = str(preview_path)
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
