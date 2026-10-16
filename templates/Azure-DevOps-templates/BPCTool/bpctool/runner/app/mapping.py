"""Map catalog Excel headers → ADO field reference names (reference-script compatible)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .excel_ir import _cell, _sheet_rows

SYSTEM_FIELD_ALIASES = {
    "title": "System.Title",
    "name": "System.Title",
    "work item title": "System.Title",
    "description": "System.Description",
    "acceptance criteria": "Microsoft.VSTS.Common.AcceptanceCriteria",
    "priority": "Microsoft.VSTS.Common.Priority",
    "state": "System.State",
    "reason": "System.Reason",
    "area path": "System.AreaPath",
    "iteration path": "System.IterationPath",
    "assigned to": "System.AssignedTo",
    "tags": "System.Tags",
}

BUILT_IN_FIELD_ALIASES = {
    "process sequence id": "MSBPC.processsequenceid",
    "alternate process sequence id": "MSBPC.alternateprocesssequenceid",
    "microsoft id": "MSBPC.microsoftid",
    "partner id": "MSBPC.partnerid",
    "mavim id": "MSBPC.mavimid",
    "catalog status": "MSBPC.catalogstatus",
    "article status": "MSBPC.articlestatus",
    "business process flow status": "MSBPC.businessprocessflowstatus",
    "scope": "MSBPC.scope",
    "fit gap status": "MSBPC.fitgapstatus",
    "gap solution approach": "MSBPC.gapsolutionapproach",
    "business process owner": "MSBPC.businessprocessowner",
    "workstream lead": "MSBPC.workstreamlead",
    "subject matter expert": "MSBPC.subjectmatterexpert",
    "workstream": "MSBPC.workstream",
    "application family": "MSBPC.applicationfamily",
    "products": "MSBPC.products",
    "industries": "MSBPC.industries",
    "module": "MSBPC.module",
    "menu path": "MSBPC.menupath",
    "menu item name": "MSBPC.menuitemname",
    "success by design phase": "MSBPC.successbydesignphase",
    "microsoft references": "MSBPC.microsoftreferences",
    "partner references": "MSBPC.partnerreferences",
    "internal references": "MSBPC.internalreferences",
    "update comments": "MSBPC.updatecomments",
    "agenda": "MSBPC.agenda",
    "key questions": "MSBPC.keyquestions",
    "steps": "Microsoft.VSTS.TCM.Steps",
    "automation status": "Microsoft.VSTS.TCM.AutomationStatus",
}


def normalize(value: Any) -> str:
    text = " ".join(str(value or "").strip().lower().replace("_", " ").split())
    if text.endswith(" ms bpc"):
        text = text[: -len(" ms bpc")].strip()
    return text


@dataclass
class FieldDef:
    label: str
    reference_name: str
    field_type: str = ""
    required: str = ""
    default_value: str = ""
    multi_select: bool = False
    page_name: str = ""
    group_name: str = ""
    group_location: str = ""
    group_sequence: str = ""
    field_sequence: str = ""
    field_name: str = ""
    custom_field: bool = False


@dataclass
class TemplateMapping:
    fields_by_label: dict[str, FieldDef] = field(default_factory=dict)
    fields_by_ref: dict[str, FieldDef] = field(default_factory=dict)
    aliases: dict[str, str] = field(
        default_factory=lambda: {**SYSTEM_FIELD_ALIASES, **BUILT_IN_FIELD_ALIASES}
    )
    # Labels on each WIT (matrix X or H); hidden_fields_by_wit holds the H subset.
    applicable_fields_by_wit: dict[str, set[str]] = field(default_factory=dict)
    hidden_fields_by_wit: dict[str, set[str]] = field(default_factory=dict)
    html_field_refs: set[str] = field(default_factory=set)

    def field_ref_for_header(self, header: str) -> str | None:
        key = normalize(header)
        if key in self.aliases:
            return self.aliases[key]
        if key.startswith("msbpc.") or key.startswith("microsoft.") or key.startswith("system."):
            return str(header).strip()
        fd = self.fields_by_label.get(key)
        if fd:
            return fd.reference_name
        return None

    def field_def(self, reference_name: str) -> FieldDef | None:
        return self.fields_by_ref.get(reference_name.lower())

    def is_html_field(self, reference_name: str) -> bool:
        if reference_name in self.html_field_refs:
            return True
        fd = self.field_def(reference_name)
        return bool(fd and "html" in (fd.field_type or "").lower())


def build_mapping_from_ir(ir: dict[str, Any]) -> TemplateMapping:
    mapping = TemplateMapping()
    for label, ref in mapping.aliases.items():
        fd = FieldDef(label=label.title(), reference_name=ref)
        mapping.fields_by_label[normalize(label)] = fd
        mapping.fields_by_ref[ref.lower()] = fd

    for item in ir.get("process", {}).get("fields", []):
        ref = item.get("reference_name") or ""
        label = item.get("label") or item.get("field_name") or ref
        if not ref:
            continue
        fd = FieldDef(
            label=label,
            reference_name=ref,
            field_type=item.get("field_type") or "",
            required=item.get("required") or "",
            default_value=item.get("default_value") or "",
            multi_select=bool(item.get("multi_select")),
            page_name=item.get("page_name") or "",
            group_name=item.get("group_name") or "",
            group_location=item.get("group_location") or "",
            group_sequence=str(item.get("group_sequence") or ""),
            field_sequence=str(item.get("field_sequence") or ""),
            field_name=item.get("field_name") or "",
            custom_field=bool(item.get("custom_field")),
        )
        mapping.fields_by_label[normalize(label)] = fd
        mapping.fields_by_ref[ref.lower()] = fd
        if "html" in fd.field_type.lower():
            mapping.html_field_refs.add(ref)

    for wit in ir.get("process", {}).get("work_item_types", []):
        name = normalize(wit.get("name"))
        hidden = {normalize(label) for label in wit.get("hidden_field_labels") or []}
        visible = {normalize(label) for label in wit.get("applicable_field_labels") or []}
        mapping.applicable_fields_by_wit[name] = visible | hidden
        mapping.hidden_fields_by_wit[name] = hidden

    # Always treat description as HTML for catalog import.
    mapping.html_field_refs.add("System.Description")
    mapping.html_field_refs.add("Microsoft.VSTS.Common.AcceptanceCriteria")
    return mapping


def load_wit_field_matrix(path: str) -> dict[str, list[str]]:
    """Return {wit_name: [field labels marked X]} from Work item types sheet (H excluded)."""
    from pathlib import Path

    rows = _sheet_rows(Path(path), "Work item types")
    if not rows:
        return {}
    headers = [_cell(v) for v in rows[0]]
    meta = {
        "work item type",
        "custom work item type",
        "inherit from",
        "reference name",
        "color",
        "icon",
        "help text",
        "purpose",
        "backlog type",
        "backlog name",
    }
    field_cols = [
        (index, name)
        for index, name in enumerate(headers)
        if name and normalize(name) not in meta
    ]
    matrix: dict[str, list[str]] = {}
    for row in rows[1:]:
        wit = _cell(row[0]) if row else ""
        if not wit:
            continue
        labels = []
        for index, name in field_cols:
            flag = _cell(row[index]).upper() if index < len(row) else ""
            if flag == "X":
                labels.append(name)
        matrix[wit] = labels
    return matrix
