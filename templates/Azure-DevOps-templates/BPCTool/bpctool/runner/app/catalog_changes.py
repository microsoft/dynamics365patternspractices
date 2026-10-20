"""Rehearsal change report: workbook rows vs the work items an earlier import created."""

from __future__ import annotations

import csv
import html
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .ado_client import AdoClient
from .catalog_import import WorkItemDraft
from .mapping import TemplateMapping

Emit = Callable[[str, str], None]

BATCH_SIZE = 200
MAX_CSV_VALUE = 2000

# Fields people usually change in Azure DevOps after import (triage, planning, ownership).
TEAM_OWNED_FIELDS = frozenset(
    ref.lower()
    for ref in (
        "System.State",
        "System.Reason",
        "System.AssignedTo",
        "System.AreaPath",
        "System.IterationPath",
        "System.Tags",
    )
)
_PATH_FIELDS = frozenset({"system.areapath", "system.iterationpath"})

MICROSOFT_ID = "MSBPC.microsoftid"
SEQUENCE_ID = "MSBPC.processsequenceid"
_CASE_INSENSITIVE_FIELDS = _PATH_FIELDS | {MICROSOFT_ID.lower(), SEQUENCE_ID.lower()}

# kind → (CSV label, sort order)
CHANGE_KINDS: dict[str, tuple[str, int]] = {
    "exists_not_in_id_map": (
        "Already in Azure DevOps, not in ado-id-map.csv — a live run would create a duplicate",
        0,
    ),
    "ambiguous_match": ("Several work items in Azure DevOps match this row", 1),
    "field_changed": ("Field value differs", 2),
    "parent_changed": ("Parent differs", 3),
    "type_changed": ("Work item type differs", 4),
    "missing_in_ado": ("Work item not found in Azure DevOps", 5),
    "retired_in_workbook": ("Deprecated or deleted in the workbook — still in Azure DevOps", 6),
    "not_in_workbook": ("In Azure DevOps, not in the workbook", 7),
    "new_row": ("New row — a live run would create it", 8),
}

CSV_FIELDS = [
    "Change",
    "Key",
    "Work item ID",
    "Work item type",
    "Title",
    "Field",
    "Value in Azure DevOps",
    "Value in workbook",
    "Usually edited in",
    "Source file",
    "Source row",
]


@dataclass
class Change:
    kind: str
    key: str
    work_item_id: int | None
    work_item_type: str
    title: str
    field_ref: str = ""
    field_label: str = ""
    current: str = ""
    workbook: str = ""
    team_owned: bool = False
    source_file: str = ""
    source_row: int | None = None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("uniqueName") or value.get("displayName") or "")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _plain(value: Any) -> str:
    """Rich text as readable plain text; Azure DevOps rewrites HTML markup on save."""
    text = _TAG_RE.sub(" ", _text(value).replace("<br", "\n<br"))
    return _SPACE_RE.sub(" ", html.unescape(text)).strip()


def _number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


_TRUE = frozenset({"true", "yes", "1"})
_FALSE = frozenset({"false", "no", "0"})


def _comparable(ref: str, value: Any, *, rich: bool, multi: bool, boolean: bool = False) -> Any:
    lowered = ref.lower()
    if rich:
        return _plain(value)
    text = _text(value).strip()
    if multi or lowered == "system.tags":
        return frozenset(part.strip().casefold() for part in text.split(";") if part.strip())
    if boolean and text.casefold() in _TRUE | _FALSE:
        return text.casefold() in _TRUE
    if lowered in _CASE_INSENSITIVE_FIELDS:
        return text.casefold()
    number = _number(text)
    if number is not None:
        return number
    if re.match(r"^\d{4}-\d{2}-\d{2}([T ]|$)", text):
        return text[:10]
    return text


def _display(value: Any, *, rich: bool) -> str:
    text = _plain(value) if rich else _text(value).strip()
    return text if len(text) <= MAX_CSV_VALUE else text[: MAX_CSV_VALUE - 1] + "…"


def _fetch_items(
    reader: AdoClient,
    project: str,
    ids: list[int],
    *,
    workers: int,
    emit: Emit,
) -> dict[int, dict[str, Any]]:
    batches = [ids[i : i + BATCH_SIZE] for i in range(0, len(ids), BATCH_SIZE)]
    found: dict[int, dict[str, Any]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(batches) or 1))) as pool:
        for items in pool.map(lambda batch: reader.get_work_items_batch(project, batch), batches):
            for item in items:
                found[int(item["id"])] = item.get("fields") or {}
            done += 1
            if done % 10 == 0 or done == len(batches):
                emit("catalog", f"Changes: read {min(done * BATCH_SIZE, len(ids)):,} of {len(ids):,} imported work items")
    return found


def _id_text(value: Any) -> str:
    return _text(value).strip().casefold()


def match_by_microsoft_id(
    reader: AdoClient,
    drafts: list[WorkItemDraft],
    *,
    project: str,
    workers: int = 4,
    emit: Emit,
) -> tuple[list[dict[str, str]], dict[int, dict[str, Any]], list[Change]]:
    """Without ado-id-map.csv: find the project's catalog items by Microsoft ID.

    Returns id-map-style rows (matched rows, then unmatched items keyed ``#<id>``),
    the items read, and rows that match several items.
    """
    ids: set[int] = set()
    for wit in sorted({draft.work_item_type for draft in drafts}):
        ids.update(reader.find_work_items_with_field(project, wit, MICROSOFT_ID))
    emit("catalog", f"Changes: found {len(ids):,} work item(s) with a Microsoft ID in project '{project}'")
    items = _fetch_items(reader, project, sorted(ids), workers=workers, emit=emit)

    by_both: dict[tuple[str, str, str], list[int]] = {}
    by_id: dict[tuple[str, str], list[int]] = {}
    for work_item_id, fields in items.items():
        wit = _id_text(fields.get("System.WorkItemType"))
        microsoft_id = _id_text(fields.get(MICROSOFT_ID))
        by_both.setdefault((wit, microsoft_id, _id_text(fields.get(SEQUENCE_ID))), []).append(work_item_id)
        by_id.setdefault((wit, microsoft_id), []).append(work_item_id)

    rows: list[dict[str, str]] = []
    ambiguous: list[Change] = []
    used: set[int] = set()
    for draft in drafts:
        wit = draft.work_item_type.casefold()
        microsoft_id = _id_text(draft.fields.get(MICROSOFT_ID))
        if not microsoft_id:
            continue
        # Same Microsoft ID + sequence ID first; Microsoft ID alone if the sequence ID was edited.
        candidates = by_both.get((wit, microsoft_id, _id_text(draft.fields.get(SEQUENCE_ID)))) or by_id.get(
            (wit, microsoft_id), []
        )
        candidates = [i for i in candidates if i not in used]
        if len(candidates) > 1:
            used.update(candidates)
            ambiguous.append(
                Change("ambiguous_match", draft.key, None, draft.work_item_type, draft.title,
                       field_label="Microsoft ID", current=", ".join(f"#{i}" for i in sorted(candidates)),
                       workbook=_text(draft.fields.get(MICROSOFT_ID)),
                       source_file=draft.source_file, source_row=draft.source_row)
            )
        elif candidates:
            work_item_id = candidates[0]
            used.add(work_item_id)
            fields = items[work_item_id]
            rows.append({"Key": draft.key, "WorkItemId": str(work_item_id),
                         "WorkItemType": _text(fields.get("System.WorkItemType")),
                         "Title": _text(fields.get("System.Title"))})
    for work_item_id, fields in sorted(items.items()):
        if work_item_id not in used:
            rows.append({"Key": f"#{work_item_id}", "WorkItemId": str(work_item_id),
                         "WorkItemType": _text(fields.get("System.WorkItemType")),
                         "Title": _text(fields.get("System.Title"))})
    return rows, items, ambiguous


def compare_with_azure_devops(
    reader: AdoClient,
    drafts: list[WorkItemDraft],
    id_map_rows: list[dict[str, str]],
    mapping: TemplateMapping,
    *,
    project: str,
    label_for: Callable[[str], str],
    workers: int = 4,
    emit: Emit,
    complete_workbook: bool = True,
    items: dict[int, dict[str, Any]] | None = None,
    ambiguous: list[Change] | None = None,
    retired_keys: set[str] | frozenset[str] = frozenset(),
) -> list[Change]:
    """Differences between the workbook and the items listed in ``id_map_rows``.

    Only fields the workbook sets are compared (an empty cell is never reported).
    ``complete_workbook`` is False when drafts were capped, so missing rows aren't listed.
    ``retired_keys`` are rows skipped as Deprecated / Deleted; their items get their own kind.
    ``items`` (already read) and ``ambiguous`` come from :func:`match_by_microsoft_id`;
    then every matched row is also reported as a duplicate a live run would create.
    """
    matched_without_map = items is not None
    imported: dict[str, dict[str, str]] = {}
    for row in id_map_rows:
        key = str(row.get("Key") or "").strip()
        if key and str(row.get("WorkItemId") or "").strip().isdigit():
            imported[key] = row
    id_of = {key: int(row["WorkItemId"]) for key, row in imported.items()}

    changes: list[Change] = list(ambiguous or [])
    unresolved = {change.key for change in changes}
    drafts_by_key = {draft.key: draft for draft in drafts}
    for draft in drafts:
        if draft.key not in imported and draft.key not in unresolved:
            changes.append(
                Change("new_row", draft.key, None, draft.work_item_type, draft.title,
                       source_file=draft.source_file, source_row=draft.source_row)
            )
    for key, row in imported.items():
        if key in drafts_by_key:
            continue
        if key in retired_keys:
            kind = "retired_in_workbook"
        elif complete_workbook:
            kind = "not_in_workbook"
        else:
            continue
        changes.append(
            Change(kind, key, id_of[key], str(row.get("WorkItemType") or ""), str(row.get("Title") or ""))
        )

    compared = [draft for draft in drafts if draft.key in imported]
    if items is None:
        items = _fetch_items(reader, project, sorted({id_of[d.key] for d in compared}), workers=workers, emit=emit)

    for draft in compared:
        work_item_id = id_of[draft.key]
        where = {"source_file": draft.source_file, "source_row": draft.source_row}
        fields = items.get(work_item_id)
        if fields is None:
            changes.append(Change("missing_in_ado", draft.key, work_item_id, draft.work_item_type, draft.title, **where))
            continue
        if matched_without_map:
            changes.append(
                Change("exists_not_in_id_map", draft.key, work_item_id, draft.work_item_type, draft.title,
                       field_label="Microsoft ID", current=f"#{work_item_id}",
                       workbook=_text(draft.fields.get(MICROSOFT_ID)), **where)
            )
        current_type = str(fields.get("System.WorkItemType") or "")
        if current_type and current_type.casefold() != draft.work_item_type.casefold():
            changes.append(
                Change("type_changed", draft.key, work_item_id, draft.work_item_type, draft.title,
                       field_label="Work item type", current=current_type, workbook=draft.work_item_type, **where)
            )
        if draft.parent_key:
            expected = id_of.get(draft.parent_key)
            current_parent = fields.get("System.Parent")
            if expected is not None and current_parent != expected:
                changes.append(
                    Change("parent_changed", draft.key, work_item_id, draft.work_item_type, draft.title,
                           field_label="Parent",
                           current=f"#{current_parent}" if current_parent else "(no parent)",
                           workbook=f"#{expected} ({draft.parent_key})", **where)
                )
        for ref, value in draft.fields.items():
            if value in (None, ""):
                continue
            fd = mapping.field_def(ref)
            rich = mapping.is_html_field(ref) or ref in draft.content_formats
            kinds = {
                "rich": rich,
                "multi": bool(fd and fd.multi_select),
                "boolean": bool(fd and (fd.field_type or "").lower() == "boolean"),
            }
            current = fields.get(ref)
            if _comparable(ref, value, **kinds) == _comparable(ref, current, **kinds):
                continue
            changes.append(
                Change("field_changed", draft.key, work_item_id, draft.work_item_type, draft.title,
                       field_ref=ref, field_label=label_for(ref),
                       current=_display(current, rich=rich), workbook=_display(value, rich=rich),
                       team_owned=ref.lower() in TEAM_OWNED_FIELDS, **where)
            )
    changes.sort(key=lambda c: (CHANGE_KINDS[c.kind][1], c.team_owned, c.key, c.field_label))
    return changes


def _difference_snippets(current: str, workbook: str, width: int = 120, lead: int = 30) -> tuple[str, str]:
    """Both values cut to ``width``, starting just before the first difference."""
    same = 0
    for a, b in zip(current, workbook, strict=False):
        if a != b:
            break
        same += 1
    start = max(0, same - lead) if max(len(current), len(workbook)) > width else 0

    def cut(text: str) -> str:
        piece = text[start : start + width]
        return ("…" if start else "") + piece + ("…" if len(text) > start + width else "")

    return cut(current), cut(workbook)


def summarize_changes(changes: list[Change], *, compared: int, examples: int = 3) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    for change in changes:
        by_kind[change.kind] = by_kind.get(change.kind, 0) + 1
    field_changes = [c for c in changes if c.kind == "field_changed"]
    by_field: dict[str, dict[str, Any]] = {}
    for change in field_changes:
        entry = by_field.setdefault(
            change.field_label, {"field": change.field_label, "count": 0, "teamOwned": change.team_owned, "examples": []}
        )
        entry["count"] += 1
        if len(entry["examples"]) < examples:
            current, workbook = _difference_snippets(change.current, change.workbook)
            entry["examples"].append(
                {"key": change.key, "workItemId": change.work_item_id, "current": current, "workbook": workbook}
            )
    changed_items = {c.key for c in changes if c.kind in {"field_changed", "parent_changed", "type_changed"}}
    return {
        "compared": compared,
        "itemsChanged": len(changed_items),
        "fieldsChanged": len(field_changes),
        "workbookFieldsChanged": sum(1 for c in field_changes if not c.team_owned),
        "teamFieldsChanged": sum(1 for c in field_changes if c.team_owned),
        "byKind": {kind: by_kind.get(kind, 0) for kind in CHANGE_KINDS},
        "byField": sorted(by_field.values(), key=lambda e: (e["teamOwned"], -e["count"], e["field"])),
    }


def write_changes_csv(changes: list[Change], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for change in changes:
            owner = ""
            if change.kind == "field_changed":
                owner = "Azure DevOps (often edited after import)" if change.team_owned else "Workbook"
            writer.writerow(
                {
                    "Change": CHANGE_KINDS[change.kind][0],
                    # Unmatched Azure DevOps items have no workbook key; the ID column identifies them.
                    "Key": "" if change.kind == "not_in_workbook" and change.key.startswith("#") else change.key,
                    "Work item ID": change.work_item_id or "",
                    "Work item type": change.work_item_type,
                    "Title": change.title,
                    "Field": change.field_label,
                    "Value in Azure DevOps": change.current,
                    "Value in workbook": change.workbook,
                    "Usually edited in": owner,
                    "Source file": change.source_file,
                    "Source row": change.source_row or "",
                }
            )
