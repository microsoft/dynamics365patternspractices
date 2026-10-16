"""Prevalidate catalog drafts against template picklists / known hard-fail values."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .catalog_import import WorkItemDraft
from .excel_ir import replace_project_placeholder
from .mapping import TemplateMapping, normalize
from .richtext import normalize_field_value

# Test Case (and inherited TCM types) do not use Agile "New".
_TEST_CASE_INVALID_STATES = frozenset({"new"})
_INVALID_AREA_MARKERS = frozenset({"not found", "n/a", "na", "none", "#n/a"})
_PROJECT_PLACEHOLDERS = frozenset({"project name", "project", "your project name here"})
# Azure DevOps single-line string / picklist-string fields reject values over 255.
MAX_STRING_LENGTH = 255
# Not an Azure DevOps field: the row key BPCTool records in ado-id-map.csv.
TRACKING_KEY_REF = "Key"
_STRING_FIELD_TYPES = frozenset({"string", "pickliststring", "picklist string", "picklist (string)"})

# Changes the runner makes on the user's behalf that need no review.
AUTOMATIC_FIX_KINDS = (
    "defaults_applied",
    "picklist_case_normalized",
    "state_case_normalized",
    "area_path_project_renamed",
    "project_placeholder_replaced",
    "duplicate_key_renamed",
)
# Values that were dropped, shortened or are still questionable — worth a look.
REVIEW_KINDS = (
    "invalid_area_path",
    "invalid_state",
    "invalid_picklist_value",
    "multiple_values_single_select",
    "text_truncated",
    "invalid_multi_select_token",
    "required_empty",
)

ISSUE_TEXT: dict[str, dict[str, str]] = {
    "defaults_applied": {
        "label": "Required field was empty — template default used",
        "outcome": "Filled with the Default value from the template Fields sheet.",
        "fix": "Nothing to do, unless the default is wrong for these rows.",
    },
    "picklist_case_normalized": {
        "label": "Picklist value casing adjusted",
        "outcome": "Rewritten to the exact casing in the template Picklists sheet.",
        "fix": "Nothing to do.",
    },
    "state_case_normalized": {
        "label": "State casing adjusted",
        "outcome": "Rewritten to the exact casing of the work item type's state in Azure DevOps.",
        "fix": "Nothing to do.",
    },
    "project_placeholder_replaced": {
        "label": "'Your Project Name Here' replaced with the project name",
        "outcome": "The placeholder in the Area path / Iteration path was replaced with the project name from the form.",
        "fix": "Nothing to do.",
    },
    "area_path_project_renamed": {
        "label": "Area / iteration path pointed at another project name",
        "outcome": "The first part of the path was replaced with the target project name.",
        "fix": "Nothing to do.",
    },
    "duplicate_key_renamed": {
        "label": "Process sequence ID used by more than one row",
        "outcome": (
            "Each row is still imported with its Process sequence ID unchanged. BPCTool tracks "
            "the repeat under a separate key in ado-id-map.csv so it isn't skipped."
        ),
        "fix": "Nothing to do.",
    },
    "invalid_area_path": {
        "label": "Area path is not in the template",
        "outcome": "Area path removed — the item is placed at the project's root area.",
        "fix": "Add the path to the template Area paths sheet, or correct the Area path column in the catalog row.",
    },
    "invalid_state": {
        "label": "State is not valid for this work item type",
        "outcome": "State removed — the item is created in its default state.",
        "fix": "Use a state the work item type supports, or add the state to the process.",
    },
    "invalid_picklist_value": {
        "label": "Value is not in the picklist",
        "outcome": "Value removed from this field.",
        "fix": "Correct the cell in the catalog workbook, or add the value to the template Picklists sheet.",
    },
    "multiple_values_single_select": {
        "label": "Several values in a field the template marks single-select",
        "outcome": "Value removed from this field — a single-select picklist accepts one value.",
        "fix": (
            "To keep all the values, set Multi-select field = Yes for this field in the template "
            "Fields sheet, then re-run Process Template and Page Layout (adds the Multivalue control) "
            "before Catalog Import. Otherwise keep one value in the catalog cell."
        ),
    },
    "text_truncated": {
        "label": f"Text longer than {MAX_STRING_LENGTH} characters",
        "outcome": f"Shortened to fit Azure DevOps' {MAX_STRING_LENGTH}-character limit.",
        "fix": "Shorten the cell in the catalog workbook if the cut-off text matters.",
    },
    "invalid_multi_select_token": {
        "label": "Multi-select value not in the picklist",
        "outcome": "Kept as typed (multi-select fields accept suggested values).",
        "fix": "Correct the spelling, or add the value to the template Picklists sheet.",
    },
    "required_empty": {
        "label": "Required field is empty (no template default)",
        "outcome": "Left empty.",
        "fix": "Fill the column in the catalog workbook, or add a Default value in the template Fields sheet.",
    },
}


def _is_required(value: Any) -> bool:
    return str(value or "").strip().lower() in {"yes", "true", "1", "x"}


def _template_default(fd) -> Any | None:
    """Return a usable Fields-sheet default, or None when absent / placeholder."""
    raw = fd.default_value
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() == "none":
        return None
    return normalize_field_value(text, fd.field_type or "")


@dataclass
class PrevalidateIssue:
    key: str
    work_item_type: str
    field: str
    value: str
    kind: str
    action: str  # report | sanitize | normalize | default
    detail: str = ""
    source_file: str = ""
    source_row: int | None = None
    field_label: str = ""
    new_value: str = ""


@dataclass
class PrevalidateResult:
    issues: list[PrevalidateIssue] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    multi_select_normalized: int = 0
    fields_stripped: int = 0
    defaults_applied: int = 0

    def bump(self, kind: str, n: int = 1) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + n


def split_multi_select(value: str) -> list[str]:
    """Split semicolon-separated multi-select storage (DevLabs Multivalue style)."""
    return [part.strip() for part in str(value).split(";") if part.strip()]


def join_multi_select(parts: list[str]) -> str:
    return "; ".join(parts)


def _area_parts(path: str) -> list[str]:
    return [part.strip() for part in str(path).replace("/", "\\").split("\\") if part.strip()]


def known_area_paths_from_ir(ir: dict[str, Any], project: str) -> dict[str, str]:
    """Relative area paths the Teams step creates (incl. ancestors), lowercase → canonical."""
    known: dict[str, str] = {}
    lowered_project = project.strip().lower()
    for area in (ir.get("project") or {}).get("area_paths") or []:
        parts = _area_parts(area.get("path") or "")
        while parts and parts[0].lower() in {lowered_project, *_PROJECT_PLACEHOLDERS}:
            parts = parts[1:]
        for depth in range(1, len(parts) + 1):
            canonical = "\\".join(parts[:depth])
            known.setdefault(canonical.lower(), canonical)
    return known


def known_iteration_paths_from_ir(ir: dict[str, Any], project: str) -> dict[str, str]:
    """Relative iteration paths the Backlog step creates (incl. ancestors), lowercase → canonical."""
    known: dict[str, str] = {}
    lowered_project = project.strip().lower()
    for iteration in (ir.get("project") or {}).get("iteration_paths") or []:
        parts = _area_parts(iteration.get("path") or "")
        while parts and parts[0].lower() in {lowered_project, *_PROJECT_PLACEHOLDERS}:
            parts = parts[1:]
        for depth in range(1, len(parts) + 1):
            canonical = "\\".join(parts[:depth])
            known.setdefault(canonical.lower(), canonical)
    return known


def _shorten(text: str, *, multi_select: bool) -> str:
    if multi_select:
        kept: list[str] = []
        for part in split_multi_select(text):
            candidate = join_multi_select([*kept, part])
            if len(candidate) > MAX_STRING_LENGTH:
                break
            kept.append(part)
        if kept:
            return join_multi_select(kept)
    return text[: MAX_STRING_LENGTH - 1].rstrip() + "…"


def prevalidate_catalog_drafts(
    drafts: list[WorkItemDraft],
    ir: dict[str, Any],
    mapping: TemplateMapping,
    *,
    sanitize: bool = True,
    project: str | None = None,
    extra_area_paths: list[str] | None = None,
    allowed_states: dict[str, list[str]] | None = None,
) -> PrevalidateResult:
    """Validate drafts; optionally strip/normalize values that hard-fail create.

    Multi-select fields (Application family, Products, Industries, …) are checked
    token-by-token against the template Picklists sheet. With process
    ``isSuggested``/``isPicklistSuggested``, semicolon composites can be stored;
    prevalidate still flags unknown tokens for data quality.

    Single- and multi-select picklist membership is **case-insensitive**; when a
    value matches ignoring case, sanitize rewrites it to the Picklists-sheet
    canonical casing (e.g. ``Organization Administration`` →
    ``Organization administration``).

    Area paths are checked against the template Area paths sheet (plus
    ``extra_area_paths`` already in the project). A leading segment naming a
    different project is rewritten to ``project``. States are checked only when
    ``allowed_states`` (work item type → states) is supplied, i.e. on live runs.
    """
    result = PrevalidateResult()
    project = (project or (ir.get("targets") or {}).get("project_name") or "").strip()
    known_areas = known_area_paths_from_ir(ir, project) if project else {}
    for extra in extra_area_paths or []:
        parts = _area_parts(extra)
        if parts and parts[0].lower() == project.lower():
            parts = parts[1:]
        if parts:
            canonical = "\\".join(parts)
            known_areas.setdefault(canonical.lower(), canonical)
    known_iterations = known_iteration_paths_from_ir(ir, project) if project else {}
    states_by_wit = {
        normalize(wit): {str(s).casefold(): str(s) for s in states}
        for wit, states in (allowed_states or {}).items()
        if states
    }

    picklists = ir.get("process", {}).get("picklists") or {}
    # label → {lowercase value → canonical template casing}
    # Catalog workbooks often differ only by title-case vs sentence-case.
    allowed_by_label: dict[str, dict[str, str]] = {}
    for name, values in picklists.items():
        canon: dict[str, str] = {}
        for raw in values:
            text = str(raw).strip()
            if not text:
                continue
            # Prefer first-seen casing from the Picklists sheet as canonical.
            canon.setdefault(text.casefold(), text)
        allowed_by_label[normalize(name)] = canon
    # Map field ref → (label key, multi_select, required, is_picklist)
    field_meta: dict[str, dict[str, Any]] = {}
    for fd in mapping.fields_by_ref.values():
        ref = fd.reference_name
        if not ref:
            continue
        label_key = normalize(fd.label)
        field_type = (fd.field_type or "").strip().lower()
        field_meta[ref.lower()] = {
            "label_key": label_key,
            "label": fd.label,
            "multi_select": bool(fd.multi_select),
            "required": (fd.required or "").strip().lower() in {"yes", "true", "1", "x"},
            "is_picklist": "picklist" in field_type or label_key in allowed_by_label,
            "is_string": field_type in _STRING_FIELD_TYPES,
        }

    def label_of(ref: str) -> str:
        meta = field_meta.get(ref.lower())
        if meta:
            return meta["label"]
        return {
            "System.AreaPath": "Area path",
            "System.IterationPath": "Iteration path",
            "System.State": "State",
            "System.Title": "Title",
            TRACKING_KEY_REF: "Tracking key (ado-id-map.csv)",
        }.get(ref, ref)

    for draft in drafts:
        wit_norm = normalize(draft.work_item_type)
        # Refs whose value was removed above; don't report them again as "required empty".
        stripped: set[str] = set()

        def add(ref: str, value: Any, kind: str, action: str, detail: str, new_value: Any = "") -> None:
            result.issues.append(
                PrevalidateIssue(
                    key=draft.key,
                    work_item_type=draft.work_item_type,
                    field=ref,
                    value=str(value),
                    kind=kind,
                    action=action,
                    detail=detail,
                    source_file=draft.source_file,
                    source_row=draft.source_row,
                    field_label=label_of(ref),
                    new_value=str(new_value or ""),
                )
            )
            result.bump(kind)

        if draft.duplicate_of:
            add(
                TRACKING_KEY_REF,
                draft.duplicate_of,
                "duplicate_key_renamed",
                "normalize",
                f"Process sequence ID '{draft.duplicate_of}' is also on an earlier row. The work item "
                f"keeps it; ado-id-map.csv tracks this row as '{draft.key}'",
                draft.key,
            )

        for ref in ("System.AreaPath", "System.IterationPath"):
            original = draft.fields.get(ref)
            replaced = replace_project_placeholder(original, project)
            if replaced != original:
                add(
                    ref,
                    original,
                    "project_placeholder_replaced",
                    "normalize",
                    f"'Your Project Name Here' → '{project}'",
                    replaced,
                )
                if sanitize:
                    draft.fields[ref] = replaced

        # Area path
        area = draft.fields.get("System.AreaPath")
        if area is not None and str(area).strip():
            area_text = str(area).strip()
            if area_text.lower() in _INVALID_AREA_MARKERS:
                add(
                    "System.AreaPath",
                    area_text,
                    "invalid_area_path",
                    "sanitize" if sanitize else "report",
                    "Placeholder area path would fail TF401347",
                )
                if sanitize:
                    del draft.fields["System.AreaPath"]
                    result.fields_stripped += 1
            elif project and known_areas:
                parts = _area_parts(area_text)
                renamed = False
                if parts and parts[0].lower() in {project.lower(), *_PROJECT_PLACEHOLDERS}:
                    relative = parts[1:]
                elif "\\".join(parts).lower() in known_areas:
                    relative = parts
                elif len(parts) > 1 and "\\".join(parts[1:]).lower() in known_areas:
                    relative = parts[1:]
                    renamed = True
                else:
                    relative = None
                if relative is None:
                    canonical_rel = None
                elif relative:
                    canonical_rel = known_areas.get("\\".join(relative).lower())
                else:
                    canonical_rel = ""
                if canonical_rel is None:
                    add(
                        "System.AreaPath",
                        area_text,
                        "invalid_area_path",
                        "sanitize" if sanitize else "report",
                        "Not in the template Area paths sheet (would fail TF401347)",
                    )
                    if sanitize:
                        del draft.fields["System.AreaPath"]
                        result.fields_stripped += 1
                else:
                    target = f"{project}\\{canonical_rel}" if canonical_rel else project
                    if renamed:
                        add(
                            "System.AreaPath",
                            area_text,
                            "area_path_project_renamed",
                            "normalize",
                            f"'{parts[0]}' → '{project}'",
                            target,
                        )
                    if sanitize and target != area_text:
                        draft.fields["System.AreaPath"] = target

        # Iteration path: only the leading project name is fixed; values are never removed.
        iteration = draft.fields.get("System.IterationPath")
        if project and iteration is not None and str(iteration).strip():
            iteration_text = str(iteration).strip()
            parts = _area_parts(iteration_text)
            joined = "\\".join(parts).lower()
            target = None
            if parts and parts[0].lower() in {project.lower(), *_PROJECT_PLACEHOLDERS}:
                target = "\\".join([project, *parts[1:]])
            elif joined in known_iterations:
                target = f"{project}\\{known_iterations[joined]}"
            elif len(parts) == 1 or "\\".join(parts[1:]).lower() in known_iterations:
                rest = known_iterations.get("\\".join(parts[1:]).lower(), "")
                target = f"{project}\\{rest}" if rest else project
            if target and target != iteration_text:
                if parts[0].lower() not in {project.lower(), *_PROJECT_PLACEHOLDERS}:
                    add(
                        "System.IterationPath",
                        iteration_text,
                        "area_path_project_renamed",
                        "normalize",
                        f"'{parts[0]}' → '{project}'"
                        if joined not in known_iterations
                        else f"project '{project}' added",
                        target,
                    )
                if sanitize:
                    draft.fields["System.IterationPath"] = target

        # State
        state = draft.fields.get("System.State")
        if state is not None and str(state).strip():
            state_text = str(state).strip()
            allowed_states_for_wit = states_by_wit.get(wit_norm)
            invalid_detail = ""
            if wit_norm == "test case" and state_text.lower() in _TEST_CASE_INVALID_STATES:
                invalid_detail = "Test Case does not allow State 'New'"
            elif allowed_states_for_wit and state_text.casefold() not in allowed_states_for_wit:
                invalid_detail = (
                    f"'{draft.work_item_type}' supports: "
                    + ", ".join(sorted(allowed_states_for_wit.values()))
                )
            elif allowed_states_for_wit:
                canon = allowed_states_for_wit[state_text.casefold()]
                if canon != state_text:
                    add(
                        "System.State",
                        state_text,
                        "state_case_normalized",
                        "normalize",
                        f"'{state_text}' → '{canon}'",
                        canon,
                    )
                    if sanitize:
                        draft.fields["System.State"] = canon
            if invalid_detail:
                add(
                    "System.State",
                    state_text,
                    "invalid_state",
                    "sanitize" if sanitize else "report",
                    invalid_detail,
                )
                if sanitize:
                    del draft.fields["System.State"]
                    result.fields_stripped += 1

        for ref, value in list(draft.fields.items()):
            if value in (None, ""):
                continue
            meta = field_meta.get(ref.lower())
            if not meta or not meta["is_picklist"]:
                continue
            label_key = meta["label_key"]
            allowed = allowed_by_label.get(label_key)
            if not allowed:
                continue
            text = str(value).strip()
            if meta["multi_select"]:
                parts = split_multi_select(text)
                remapped: list[str] = []
                unknown: list[str] = []
                casing_fixed = False
                for part in parts:
                    canon = allowed.get(part.casefold())
                    if canon is None:
                        remapped.append(part)
                        unknown.append(part)
                    else:
                        if canon != part:
                            casing_fixed = True
                        remapped.append(canon)
                normalized = join_multi_select(remapped)
                if sanitize and (normalized != text or casing_fixed):
                    draft.fields[ref] = normalized
                    result.multi_select_normalized += 1
                    if casing_fixed:
                        add(
                            ref,
                            text,
                            "picklist_case_normalized",
                            "normalize",
                            f"Aligned multi-select token casing to picklist '{meta['label']}'",
                            normalized,
                        )
                if unknown:
                    add(
                        ref,
                        text,
                        "invalid_multi_select_token",
                        "report",
                        f"Unknown token(s): {', '.join(unknown[:5])}",
                    )
            else:
                canon = allowed.get(text.casefold())
                if canon is None:
                    parts = split_multi_select(text)
                    known_parts = [p for p in parts if p.casefold() in allowed]
                    if len(parts) > 1 and known_parts:
                        unknown_parts = [p for p in parts if p.casefold() not in allowed]
                        detail = f"{len(parts)} values in single-select '{meta['label']}'"
                        if unknown_parts:
                            detail += f"; not in picklist: {', '.join(unknown_parts[:5])}"
                        add(
                            ref,
                            text,
                            "multiple_values_single_select",
                            "sanitize" if sanitize else "report",
                            detail,
                        )
                    else:
                        add(
                            ref,
                            text,
                            "invalid_picklist_value",
                            "sanitize" if sanitize else "report",
                            f"Not in picklist '{meta['label']}'",
                        )
                    if sanitize:
                        del draft.fields[ref]
                        result.fields_stripped += 1
                        stripped.add(ref)
                elif sanitize and canon != text:
                    draft.fields[ref] = canon
                    add(
                        ref,
                        text,
                        "picklist_case_normalized",
                        "normalize",
                        f"Aligned casing to picklist '{meta['label']}': '{text}' → '{canon}'",
                        canon,
                    )

        # Single-line text limit (TF401324). Title is always a string field.
        for ref, value in list(draft.fields.items()):
            if not isinstance(value, str) or len(value) <= MAX_STRING_LENGTH:
                continue
            meta = field_meta.get(ref.lower())
            if ref != "System.Title" and not (meta and meta["is_string"]):
                continue
            shortened = _shorten(value, multi_select=bool(meta and meta["multi_select"]))
            add(
                ref,
                value,
                "text_truncated",
                "sanitize" if sanitize else "report",
                f"{len(value)} characters (limit {MAX_STRING_LENGTH})",
                shortened,
            )
            if sanitize:
                draft.fields[ref] = shortened
                if ref == "System.Title":
                    draft.title = shortened

        # Required MSBPC fields empty — fill template Default value when present;
        # only when WIT matrix marks the field applicable.
        applicable = mapping.applicable_fields_by_wit.get(wit_norm)
        if applicable:
            for fd in mapping.fields_by_ref.values():
                if not _is_required(fd.required):
                    continue
                if normalize(fd.label) not in applicable:
                    continue
                ref = fd.reference_name
                if not ref or not ref.lower().startswith("msbpc."):
                    continue
                if draft.fields.get(ref) not in (None, ""):
                    continue
                default = _template_default(fd) if sanitize else None
                if default is None and ref in stripped:
                    continue
                if default is not None:
                    draft.fields[ref] = default
                    result.defaults_applied += 1
                    add(
                        ref,
                        default,
                        "defaults_applied",
                        "default",
                        f"Required field '{fd.label}' empty in spreadsheet; applied template default",
                        default,
                    )
                    continue
                add(
                    ref,
                    "",
                    "required_empty",
                    "report",
                    f"Required field '{fd.label}' is empty (no template default)",
                )

    return result


def _group(result: PrevalidateResult, kinds: tuple[str, ...], examples: int) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for kind in kinds:
        count = result.counts.get(kind, 0)
        if not count:
            continue
        rows = [issue for issue in result.issues if issue.kind == kind]
        fields: dict[str, int] = {}
        for issue in rows:
            fields[issue.field_label] = fields.get(issue.field_label, 0) + 1
        groups.append(
            {
                "kind": kind,
                **ISSUE_TEXT.get(kind, {"label": kind, "outcome": "", "fix": ""}),
                "count": count,
                "fields": dict(sorted(fields.items(), key=lambda item: -item[1])),
                "examples": [_issue_row(issue) for issue in rows[:examples]],
            }
        )
    groups.sort(key=lambda group: -group["count"])
    return groups


def _issue_row(issue: PrevalidateIssue) -> dict[str, Any]:
    return {
        "key": issue.key,
        "workItemType": issue.work_item_type,
        "field": issue.field,
        "fieldLabel": issue.field_label,
        "value": issue.value,
        "newValue": issue.new_value,
        "action": issue.action,
        "detail": issue.detail,
        "sourceFile": issue.source_file,
        "sourceRow": issue.source_row,
    }


def prevalidate_summary(result: PrevalidateResult, *, examples: int = 5) -> dict[str, Any]:
    samples: dict[str, list[dict[str, Any]]] = {}
    for issue in result.issues:
        bucket = samples.setdefault(issue.kind, [])
        if len(bucket) >= 15:
            continue
        bucket.append(_issue_row(issue))
    needs_review = _group(result, REVIEW_KINDS, examples)
    automatic = _group(result, AUTOMATIC_FIX_KINDS, examples)
    return {
        "needsReview": needs_review,
        "needsReviewTotal": sum(group["count"] for group in needs_review),
        "automaticFixes": automatic,
        "automaticFixesTotal": sum(group["count"] for group in automatic),
        "counts": dict(sorted(result.counts.items())),
        "multiSelectNormalized": result.multi_select_normalized,
        "fieldsStripped": result.fields_stripped,
        "defaultsApplied": result.defaults_applied,
        "issueTotal": len(result.issues),
        "samples": samples,
    }


PREVALIDATE_CSV_COLUMNS = [
    "Needs review?",
    "What happened",
    "Source file",
    "Row",
    "Key",
    "Work item type",
    "Field",
    "Value in spreadsheet",
    "Value used",
    "Details",
    "How to fix",
]


def write_prevalidate_csv(result: PrevalidateResult, path: Path) -> int:
    """Every check result, review items first — opens directly in Excel."""
    order = {kind: index for index, kind in enumerate(REVIEW_KINDS + AUTOMATIC_FIX_KINDS)}
    rows = sorted(
        result.issues,
        key=lambda issue: (order.get(issue.kind, 99), issue.source_file, issue.source_row or 0),
    )
    # utf-8-sig so Excel detects UTF-8 (arrows, accented names).
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(PREVALIDATE_CSV_COLUMNS)
        for issue in rows:
            text = ISSUE_TEXT.get(issue.kind, {})
            writer.writerow(
                [
                    "Yes" if issue.kind in REVIEW_KINDS else "No",
                    text.get("label", issue.kind),
                    issue.source_file,
                    issue.source_row or "",
                    issue.key,
                    issue.work_item_type,
                    issue.field_label or issue.field,
                    issue.value,
                    issue.new_value,
                    issue.detail,
                    text.get("fix", ""),
                ]
            )
    return len(rows)
