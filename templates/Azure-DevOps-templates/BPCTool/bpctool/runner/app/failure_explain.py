"""Turn raw Azure DevOps create errors into plain-language problems and fixes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .catalog_import import WorkItemDraft
from .catalog_validate import MAX_STRING_LENGTH
from .csv_safe import SafeWriter

PARENT_PREFIX = "Parent not imported: "

CATEGORY_TEXT: dict[str, dict[str, str]] = {
    "area_path": {
        "label": "Area path does not exist in the project",
        "fix": "Add the path to the template Area paths sheet and re-run Teams & Areas, "
        "or correct the Area path column in the catalog row. Then re-run Catalog Import.",
    },
    "iteration_path": {
        "label": "Iteration path does not exist in the project",
        "fix": "Add the iteration to the template Iteration paths sheet and re-run Backlog Configuration, "
        "or correct the Iteration path column in the catalog row. Then re-run Catalog Import.",
    },
    "text_too_long": {
        "label": f"Text is longer than {MAX_STRING_LENGTH} characters",
        "fix": "Shorten the cell in the catalog workbook, then re-run Catalog Import.",
    },
    "invalid_state": {
        "label": "State is not valid for this work item type",
        "fix": "Change the State cell to a state this work item type supports, "
        "or add the state to the process. Then re-run Catalog Import.",
    },
    "invalid_value": {
        "label": "Value is not allowed for the field",
        "fix": "Correct the cell in the catalog workbook, or add the value to the "
        "template Picklists sheet and re-run Process Template. Then re-run Catalog Import.",
    },
    "required_missing": {
        "label": "Required field is empty",
        "fix": "Fill the column in the catalog workbook, or give the field a Default value "
        "in the template Fields sheet. Then re-run Catalog Import.",
    },
    "unknown_field": {
        "label": "Field is not on this work item type",
        "fix": "Mark the field for this type in the template Work item types sheet and "
        "re-run Process Template / Page Layout, or clear the column for these rows.",
    },
    "unknown_type": {
        "label": "Work item type does not exist in the process",
        "fix": "Add or enable the type in the template Work item types sheet and re-run "
        "Process Template, or correct the Work item type column.",
    },
    "permission": {
        "label": "Access denied",
        "fix": "Check the PAT has Work Items (Read & write) scope and has not expired, then re-run.",
    },
    "throttled": {
        "label": "Azure DevOps was busy (rate limited)",
        "fix": "Re-run Catalog Import — it resumes where it stopped. Use fewer Catalog workers if this repeats.",
    },
    "network": {
        "label": "Network error — outcome unknown",
        "fix": "Check Azure DevOps for a duplicate of these items before re-running Catalog Import.",
    },
    "parent_failed": {
        "label": "Not imported because its parent failed",
        "fix": "Fix the parent row (see Blocked by). These rows import automatically on the next Catalog Import run.",
    },
    "other": {
        "label": "Other Azure DevOps error",
        "fix": "See Technical detail. Fix the row, then re-run Catalog Import.",
    },
}

_STATUS_RE = re.compile(r"^ADO (\d{3})\b")
_FIELD_RE = re.compile(r"field '([^']+)'")
_VALUE_RE = re.compile(r"value '([^']*)'")


def ado_error_message(error: str) -> str:
    """Pull the human-readable message out of 'ADO 400 Bad Request: {json}'."""
    text = str(error or "")
    brace = text.find("{")
    if brace >= 0:
        try:
            payload = json.loads(text[brace:])
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            custom = payload.get("customProperties") or {}
            message = custom.get("ErrorMessage") or payload.get("message")
            if message:
                return str(message).strip()
    return re.sub(r"^ADO \d{3}[^:]*:\s*", "", text).strip() or text


def explain_failure(
    error: str,
    draft: WorkItemDraft | None,
    *,
    label_for: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Classify one failure; returns category, problem, fix, field label and attempted value."""
    text = str(error or "")
    fields = draft.fields if draft else {}
    label = label_for or (lambda ref: ref)

    if text.startswith(PARENT_PREFIX):
        parent = text[len(PARENT_PREFIX):].strip()
        return _result("parent_failed", f"Parent {parent} was not imported.", "", "")

    message = ado_error_message(text)
    status_match = _STATUS_RE.match(text)
    status = int(status_match.group(1)) if status_match else None
    lowered = message.lower()

    if ("tf401347" in lowered or "invalid tree name" in lowered) and "iterationpath" in lowered:
        value = str(fields.get("System.IterationPath") or "")
        return _result(
            "iteration_path",
            f"Iteration path '{value}' does not exist in the project." if value else message,
            "Iteration path",
            value,
        )
    if "tf401347" in lowered or ("invalid tree name" in lowered and "areapath" in lowered):
        value = str(fields.get("System.AreaPath") or "")
        return _result(
            "area_path",
            f"Area path '{value}' does not exist in the project." if value else message,
            "Area path",
            value,
        )
    if "tf401324" in lowered or "too long" in lowered:
        ref = _first(_FIELD_RE, message)
        ref_key = _ref_for(ref, fields)
        value = str(fields.get(ref_key) or "") if ref_key else ""
        name = label(ref_key) if ref_key else ref
        length = f" ({len(value)} characters)" if value else ""
        return _result(
            "text_too_long",
            f"{name} is longer than {MAX_STRING_LENGTH} characters{length}.",
            name,
            value,
        )
    if "'state'" in lowered and "not in the list of supported values" in lowered:
        value = str(fields.get("System.State") or _first(_VALUE_RE, message))
        wit = draft.work_item_type if draft else "this work item type"
        return _result(
            "invalid_state", f"State '{value}' is not valid for {wit}.", "State", value
        )
    if "not in the list of supported values" in lowered or "limitedtovalues" in lowered:
        ref = _first(_FIELD_RE, message)
        ref_key = _ref_for(ref, fields)
        name = label(ref_key) if ref_key else ref
        value = str(fields.get(ref_key) or _first(_VALUE_RE, message)) if ref_key else _first(
            _VALUE_RE, message
        )
        return _result("invalid_value", f"{name}: '{value}' is not an allowed value.", name, value)
    if "invalidempty" in lowered or "cannot be empty" in lowered or (
        "tf401320" in lowered and "required" in lowered
    ):
        ref = _first(_FIELD_RE, message)
        ref_key = _ref_for(ref, fields)
        name = label(ref_key) if ref_key else ref
        return _result("required_missing", f"{name} is required but empty.", name, "")
    if "tf51535" in lowered or "cannot find field" in lowered:
        ref = _first(re.compile(r"field ([\w.]+)", re.I), message)
        return _result("unknown_field", message, label(ref) if ref else "", "")
    if "work item type" in lowered and ("does not exist" in lowered or "not found" in lowered):
        wit = draft.work_item_type if draft else ""
        return _result("unknown_type", f"Work item type '{wit}' does not exist.", "", wit)
    if status in {401, 403} or "sign-in page" in lowered:
        return _result("permission", message, "", "")
    if status in {429, 503}:
        return _result("throttled", message, "", "")
    if "outcome unknown" in lowered or "connection" in lowered or "timed out" in lowered:
        return _result("network", message, "", "")
    return _result("other", message, "", "")


def _result(category: str, problem: str, field_label: str, value: str) -> dict[str, Any]:
    return {
        "category": category,
        "problem": problem,
        "fix": CATEGORY_TEXT[category]["fix"],
        "fieldLabel": field_label,
        "value": value,
    }


def _first(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(1) if match else ""


def _ref_for(name: str, fields: dict[str, Any]) -> str:
    """Match an error's field name (ref or display name) to a draft field ref."""
    if not name:
        return ""
    lowered = name.lower()
    for ref in fields:
        if ref.lower() == lowered or ref.lower().split(".")[-1] == lowered.replace(" ", ""):
            return ref
    return name


def enrich_failures(
    failures: list[dict[str, Any]],
    drafts_by_key: dict[str, WorkItemDraft],
    *,
    label_for: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Add plain-language fields and the root failed ancestor (``blockedBy``) to each failure."""
    by_key = {item["key"]: item for item in failures}
    for item in failures:
        item.update(explain_failure(item.get("error", ""), drafts_by_key.get(item["key"]), label_for=label_for))
    for item in failures:
        if item["category"] != "parent_failed":
            item["blockedBy"] = ""
            continue
        root = item.get("parentKey") or ""
        seen: set[str] = set()
        while root in by_key and by_key[root].get("category") == "parent_failed" and root not in seen:
            seen.add(root)
            root = by_key[root].get("parentKey") or root
        item["blockedBy"] = root
        root_item = by_key.get(root)
        if root_item is not None:
            root_item["blockedChildren"] = int(root_item.get("blockedChildren") or 0) + 1
            item["problem"] = (
                f"Not imported because {root} failed ({CATEGORY_TEXT[root_item['category']]['label'].lower()})."
            )
    return failures


def summarize_failures(failures: list[dict[str, Any]], *, examples: int = 5) -> dict[str, Any]:
    """Group failures by cause, largest first, separating root causes from blocked children."""
    roots = [item for item in failures if item.get("category") != "parent_failed"]
    blocked = len(failures) - len(roots)
    groups: dict[str, dict[str, Any]] = {}
    for item in roots:
        category = item.get("category") or "other"
        group = groups.setdefault(
            category,
            {
                "category": category,
                "label": CATEGORY_TEXT[category]["label"],
                "fix": CATEGORY_TEXT[category]["fix"],
                "count": 0,
                "blockedChildren": 0,
                "examples": [],
            },
        )
        group["count"] += 1
        group["blockedChildren"] += int(item.get("blockedChildren") or 0)
        if len(group["examples"]) < examples:
            group["examples"].append(
                {
                    "key": item.get("key"),
                    "title": item.get("title"),
                    "workItemType": item.get("workItemType"),
                    "sourceFile": item.get("sourceFile"),
                    "sourceRow": item.get("sourceRow"),
                    "problem": item.get("problem"),
                    "value": item.get("value"),
                }
            )
    ordered = sorted(groups.values(), key=lambda g: -(g["count"] + g["blockedChildren"]))
    return {
        "total": len(failures),
        "rootCauses": len(roots),
        "blockedByParent": blocked,
        "groups": ordered,
    }


FAILURES_CSV_COLUMNS = [
    "Status",
    "Problem",
    "How to fix",
    "Source file",
    "Row",
    "Key",
    "Work item type",
    "Title",
    "Field",
    "Value tried",
    "Blocked by",
    "Children blocked",
    "Technical detail",
]


def write_failures_csv(failures: list[dict[str, Any]], path: Path) -> None:
    """Root causes first (biggest impact first), then blocked rows grouped by blocker."""
    def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        is_blocked = item.get("category") == "parent_failed"
        return (
            is_blocked,
            item.get("blockedBy") or "",
            -int(item.get("blockedChildren") or 0),
            item.get("sourceFile") or "",
            item.get("sourceRow") or 0,
        )

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = SafeWriter(handle)
        writer.writerow(FAILURES_CSV_COLUMNS)
        for item in sorted(failures, key=sort_key):
            blocked = item.get("category") == "parent_failed"
            writer.writerow(
                [
                    "Blocked by parent" if blocked else "Fix this row",
                    item.get("problem", ""),
                    item.get("fix", ""),
                    item.get("sourceFile", ""),
                    item.get("sourceRow", ""),
                    item.get("key", ""),
                    item.get("workItemType", ""),
                    item.get("title", ""),
                    item.get("fieldLabel", ""),
                    item.get("value", ""),
                    item.get("blockedBy", ""),
                    item.get("blockedChildren", "") or "",
                    "" if blocked else ado_error_message(item.get("error", "")),
                ]
            )
