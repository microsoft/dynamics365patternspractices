from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .mapping import TemplateMapping, normalize
from .test_steps import to_test_steps_xml


DEFAULTS_BY_REF = {
    "MSBPC.catalogstatus": "10 - New",
    "MSBPC.articlestatus": "10 - Not started",
    "MSBPC.businessprocessflowstatus": "10 - Not started",
    "MSBPC.businessprocessflowsource": "Microsoft",
    "MSBPC.scope": "10 - Unspecified",
    "MSBPC.fitgapstatus": "Unspecified",
    "MSBPC.gapsolutionapproach": "10 - Unspecified",
    "MSBPC.successbydesignphase": "10 - Strategize",
}

FLOW_SOURCE_WORK_ITEM_TYPES = {"end to end", "process area", "process"}

WORK_ITEM_TYPE_ALIASES = {
    "test case": "Test Case",
    "testcase": "Test Case",
    "process area": "Process area",
    "functional area": "Functional area",
    "system process": "System process",
    "end to end": "End to end",
}


@dataclass
class WorkItemDraft:
    key: str
    parent_key: str | None
    aliases: set[str]
    hierarchy_level: int | None
    work_item_type: str
    title: str
    fields: dict[str, Any]
    source_file: str
    source_row: int
    warnings: list[str] = field(default_factory=list)


def build_drafts(rows: list[dict[str, Any]], mapping: TemplateMapping) -> list[WorkItemDraft]:
    drafts = [_row_to_draft(row, mapping) for row in rows]
    _derive_title_hierarchy_parents(drafts)
    alias_to_key = {}
    for draft in drafts:
        for alias in draft.aliases | {draft.key}:
            alias_to_key.setdefault(alias, draft.key)
    for draft in drafts:
        if draft.parent_key:
            draft.parent_key = alias_to_key.get(draft.parent_key, draft.parent_key)
    keys = {d.key for d in drafts}
    for draft in drafts:
        if draft.parent_key and draft.parent_key not in keys:
            draft.warnings.append(f"Parent key not found in source set: {draft.parent_key}")
    return sort_parent_first(drafts)


def sort_parent_first(drafts: list[WorkItemDraft]) -> list[WorkItemDraft]:
    by_key = {d.key: d for d in drafts}
    ordered: list[WorkItemDraft] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(draft: WorkItemDraft) -> None:
        if draft.key in visited:
            return
        if draft.key in visiting:
            draft.warnings.append("Cycle detected in parent relationship; parent link will be skipped if needed.")
            return
        visiting.add(draft.key)
        if draft.parent_key and draft.parent_key in by_key:
            visit(by_key[draft.parent_key])
        visiting.remove(draft.key)
        visited.add(draft.key)
        ordered.append(draft)

    for draft in drafts:
        visit(draft)
    return ordered


def _row_to_draft(row: dict[str, Any], mapping: TemplateMapping) -> WorkItemDraft:
    lookup = _build_lookup(row)
    wit = _work_item_type(lookup, row)
    hierarchy_title, hierarchy_level = _title_from_row(lookup)
    title = hierarchy_title or _first_value(
        lookup,
        "title",
        "name",
        "work item title",
        "process name",
        "business process",
        "deliverable",
        "test case",
        "description",
    )
    key = _external_key(lookup, row)
    if not title:
        title = f"{wit} {key}"
    fields = _fields(row, lookup, mapping, wit, key, title)
    return WorkItemDraft(
        key=key,
        parent_key=_parent_key(lookup),
        aliases=_identifier_aliases(lookup),
        hierarchy_level=hierarchy_level,
        work_item_type=wit,
        title=title,
        fields=fields,
        source_file=str(row.get("_source_file") or ""),
        source_row=int(row.get("_source_row") or 0),
    )


def _derive_title_hierarchy_parents(drafts: list[WorkItemDraft]) -> None:
    stack_by_source: dict[str, dict[int, str]] = {}
    keys = {draft.key for draft in drafts}
    for draft in drafts:
        if draft.hierarchy_level is None:
            continue
        stack = stack_by_source.setdefault(draft.source_file, {})
        if not draft.parent_key or draft.parent_key not in keys:
            for level in range(draft.hierarchy_level - 1, 0, -1):
                if level in stack:
                    draft.parent_key = stack[level]
                    break
        stack[draft.hierarchy_level] = draft.key
        for level in list(stack):
            if level > draft.hierarchy_level:
                del stack[level]


def _fields(
    row: dict[str, Any],
    lookup: dict[str, Any],
    mapping: TemplateMapping,
    wit: str,
    key: str,
    title: str,
) -> dict[str, Any]:
    fields: dict[str, Any] = {"System.Title": title}
    description = _first_value(lookup, "description")
    fields["System.Description"] = description or f"Imported from {row.get('_source_file')} row {row.get('_source_row')}."

    for header, value in row.items():
        if str(header).startswith("_") or value in (None, ""):
            continue
        ref = mapping.field_ref_for_header(header)
        if not ref or ref in {"System.Title", "System.Description"}:
            continue
        fields[ref] = _coerce_value(ref, value, mapping)

    if wit.lower() == "test case":
        xml = to_test_steps_xml(_first_value(lookup, "steps", "action", "test steps"), _first_value(lookup, "expected result", "expected"))
        if xml:
            fields["Microsoft.VSTS.TCM.Steps"] = xml
        fields.setdefault("Microsoft.VSTS.TCM.AutomationStatus", "Not Automated")

    fields.setdefault("MSBPC.microsoftid", _first_value(lookup, "microsoft id") or key)
    fields.setdefault("MSBPC.processsequenceid", _first_value(lookup, "process sequence id") or key)

    applicable = mapping.applicable_fields_by_wit.get(wit.lower())
    for ref in applicable or set():
        fd = mapping.field_def(ref)
        if not fd:
            continue
        required = normalize(fd.required)
        if ref not in fields and required in {"yes", "conditional"}:
            fields[ref] = _default_for_field(ref, fd.field_type, fd.default_value)

    for ref, value in DEFAULTS_BY_REF.items():
        if ref == "MSBPC.businessprocessflowsource" and wit.lower() not in FLOW_SOURCE_WORK_ITEM_TYPES:
            continue
        if ref in fields or (applicable is not None and ref not in applicable):
            continue
        fields[ref] = value

    return {ref: value for ref, value in fields.items() if value not in (None, "")}


def _work_item_type(lookup: dict[str, Any], row: dict[str, Any]) -> str:
    raw = _first_value(lookup, "work item type", "type", "ado work item type")
    if raw:
        return WORK_ITEM_TYPE_ALIASES.get(normalize(raw), str(raw).strip())
    if _first_value(lookup, "steps", "test steps"):
        return "Test Case"
    file_name = normalize(row.get("_source_file"))
    if "test" in file_name:
        return "Test Case"
    if "deliver" in file_name:
        return "Deliverable"
    depth = _sequence_depth(_first_value(lookup, "process sequence id", "sequence id", "id"))
    return {1: "End to end", 2: "Process area", 3: "Process", 4: "Scenario"}.get(depth, "System process")


def _build_lookup(row: dict[str, Any]) -> dict[str, Any]:
    lookup: dict[str, Any] = {}
    for header, value in row.items():
        key = normalize(header)
        lookup[key] = value
        if key.endswith(" ms bpc"):
            lookup.setdefault(key[: -len(" ms bpc")], value)
    return lookup


def _title_from_row(lookup: dict[str, Any]) -> tuple[str | None, int | None]:
    titles: list[tuple[int, str]] = []
    for index in range(1, 11):
        value = _first_value(lookup, f"title {index}")
        if value:
            titles.append((index, value))
    if titles:
        return titles[-1][1], titles[-1][0]
    return None, None


def _external_key(lookup: dict[str, Any], row: dict[str, Any]) -> str:
    value = _first_value(
        lookup,
        "process sequence id",
        "microsoft id",
        "partner id",
        "mavim id",
        "id",
        "external id",
        "key",
    )
    if value:
        return str(value).strip()
    stem = Path(str(row.get("_source_file") or "source")).stem
    return f"{stem}:{row.get('_source_sheet') or ''}:{row.get('_source_row')}"


def _identifier_aliases(lookup: dict[str, Any]) -> set[str]:
    aliases = set()
    for key in ("process sequence id", "microsoft id", "partner id", "mavim id", "id", "external id", "key"):
        value = _first_value(lookup, key)
        if value:
            aliases.add(value)
    return aliases


def _parent_key(lookup: dict[str, Any]) -> str | None:
    explicit = _first_value(
        lookup,
        "parent key",
        "parent id",
        "parent microsoft id",
        "parent partner id",
        "parent process sequence id",
        "parent process",
    )
    if explicit:
        return str(explicit).strip()
    return _derive_parent_from_sequence(_first_value(lookup, "process sequence id", "sequence id"))


def _derive_parent_from_sequence(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    dotted = text.split(".")
    if len(dotted) > 1 and all(part.isdigit() for part in dotted):
        if len(dotted) > 4:
            return ".".join(dotted[:-1])
        segments = [int(part) for part in dotted]
        non_zero = [index for index, segment in enumerate(segments) if segment != 0]
        if not non_zero:
            return None
        parent_segments = list(segments)
        parent_segments[non_zero[-1]] = 0
        width = [len(part) for part in dotted]
        return ".".join(str(segment).zfill(width[index]) for index, segment in enumerate(parent_segments))
    for pattern in (r"^(.*)[.](\d+)$", r"^(.*)[/](.+)$", r"^(.*)[-](\d+)$"):
        match = re.match(pattern, text)
        if match:
            return match.group(1)
    return None


def _sequence_depth(value: Any) -> int:
    if not value:
        return 5
    text = str(value).strip()
    if "." in text:
        return len([p for p in text.split(".") if p])
    if "/" in text:
        return len([p for p in text.split("/") if p])
    if re.search(r"-\d+$", text):
        return len([p for p in text.split("-") if p])
    return 1


def _coerce_value(ref: str, value: Any, mapping: TemplateMapping) -> Any:
    fd = mapping.field_def(ref)
    if fd and fd.multi_select and isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[;\n,]", value) if p.strip()]
        unique_parts = list(dict.fromkeys(parts))
        return "; ".join(unique_parts)
    if fd and normalize(fd.field_type) == "boolean":
        return str(value).strip().lower() in {"true", "yes", "y", "1", "x"}
    return value


def _default_for_field(ref: str, field_type: str, default_value: str) -> Any:
    if default_value and normalize(default_value) not in {"conditional", "nan", "none"}:
        return default_value
    if ref in DEFAULTS_BY_REF:
        return DEFAULTS_BY_REF[ref]
    field_type = normalize(field_type)
    if "boolean" in field_type:
        return False
    if "integer" in field_type:
        return 0
    if "decimal" in field_type:
        return 0
    if "html" in field_type:
        return "<div>Unspecified</div>"
    if "picklist" in field_type:
        return ""
    return ""


def _first_value(lookup: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = lookup.get(normalize(key))
        if value not in (None, ""):
            return str(value).strip()
    return None

