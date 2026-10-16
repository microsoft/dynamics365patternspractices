"""Apply page layouts, including HtmlFieldControl groups for HTML fields."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from ..ado_client import AdoClient, AdoError

Emit = Callable[[str, str], None]


def apply_layout(
    client: AdoClient,
    ir: dict[str, Any],
    *,
    dry_run: bool,
    emit: Emit,
    process_id: str | None = None,
) -> dict[str, Any]:
    process_name = ir["targets"]["process_name"]
    stats = {
        "wits_processed": 0,
        "html_controls": 0,
        "controls": 0,
        "fields_added": 0,
        "hidden_fields": 0,
        "controls_hidden": 0,
        "controls_shown": 0,
        "warnings": 0,
    }

    html_count = ir["counts"].get("html_fields", 0)
    hidden_count = ir["counts"].get("hidden_field_placements", 0)
    if dry_run:
        emit(
            "layout",
            f"[dry-run] Would apply layouts for {len(ir['process']['work_item_types'])} WITs "
            f"including {html_count} HtmlFieldControl placements"
            + (
                f" and {hidden_count} hidden (H) fields added to WITs without a visible control"
                if hidden_count
                else ""
            ),
        )
        return stats

    process_id = process_id or client.get_process_id(process_name)
    if not process_id:
        raise AdoError(f'Process "{process_name}" not found for layout apply.')

    fields_by_label = {
        (f.get("label") or f.get("field_name") or "").strip(): f for f in ir["process"]["fields"]
    }
    process_wit_map = _index_process_wits(client.list_process_wits(process_id))

    for wit in ir["process"]["work_item_types"]:
        placements = [(label, False) for label in wit.get("applicable_field_labels") or []]
        placements += [(label, True) for label in wit.get("hidden_field_labels") or []]
        if not placements:
            continue
        if wit.get("disabled"):
            continue
        wit_name = wit["name"]
        excel_ref = (wit.get("reference_name") or "").strip()
        process_wit = _resolve_process_wit(process_wit_map, wit_name, excel_ref)
        if not process_wit:
            emit("layout", f"Skipping layout for missing WIT '{wit_name}'")
            stats["warnings"] += 1
            continue

        wit_ref = str(process_wit.get("referenceName") or excel_ref or "")
        wit_api_id = _process_api_wit_id(wit_name, wit_ref, process_wit)
        if not wit_api_id:
            emit("layout", f"Skipping layout for WIT '{wit_name}' — missing Process API id")
            stats["warnings"] += 1
            continue

        # Materialize system WITs before field/layout mutation (reference ensure_inherited_wit_customized).
        if _is_system_reference(wit_ref):
            if _materialize_system_wit(client, process_id, wit_ref, process_wit):
                process_wit_map = _index_process_wits(client.list_process_wits(process_id))
                refreshed = _resolve_process_wit(process_wit_map, wit_name, excel_ref) or process_wit
                wit_ref = str(refreshed.get("referenceName") or wit_ref)
                wit_api_id = _process_api_wit_id(wit_name, wit_ref, refreshed)

        stats["wits_processed"] += 1
        enc_wit = quote(wit_api_id, safe="")

        for label, hidden in placements:
            field = fields_by_label.get(label)
            if not field:
                continue
            ref = field.get("reference_name")
            if not ref:
                continue
            field_type = (field.get("field_type") or "").strip()
            order = (
                int(field.get("field_sequence"))
                if str(field.get("field_sequence") or "").isdigit()
                else 1
            )
            group_order = (
                int(field.get("group_sequence"))
                if str(field.get("group_sequence") or "").isdigit()
                else 1
            )

            # Add field to WIT (booleans require defaultValue — VS403099)
            field_ok = _ensure_field_on_wit(
                client, process_id, enc_wit, field, emit=emit, wit_name=wit_name
            )
            if field_ok is True:
                stats["fields_added"] += 1
            elif field_ok is False:
                stats["warnings"] += 1
                continue

            page_name = field.get("page_name") or "Details"
            group_name = field.get("group_name") or label
            section_label = field.get("group_location") or "Section1"

            try:
                layout = client.get(
                    f"/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}/layout",
                    api_version="7.1-preview.1",
                )
            except AdoError as exc:
                emit("layout", f"Layout locked/unavailable for {wit_name}: {exc}")
                stats["warnings"] += 1
                break

            group_id, control = _find_control(layout, ref)
            if hidden:
                stats["hidden_fields"] += 1
                if _parse_required(field.get("required")) and not _has_default(field):
                    emit(
                        "layout",
                        f"Hidden field {ref} on {wit_name} is required with no default value; "
                        "users cannot fill it on the form",
                    )
                    stats["warnings"] += 1
                if control is not None and control.get("visible", True):
                    if _set_control_visibility(
                        client, process_id, enc_wit, group_id, ref, visible=False, emit=emit
                    ):
                        stats["controls_hidden"] += 1
                    else:
                        stats["warnings"] += 1
                continue

            if control is not None:
                if control.get("visible", True) is False:
                    if _set_control_visibility(
                        client, process_id, enc_wit, group_id, ref, visible=True, emit=emit
                    ):
                        stats["controls_shown"] += 1
                    else:
                        stats["warnings"] += 1
                continue

            page_id, layout = _ensure_page(
                client, process_id, enc_wit, layout, page_name, group_order, emit, wit_name
            )
            if not page_id or not layout:
                stats["warnings"] += 1
                continue

            section_id = _section_id(layout, page_id, section_label)
            if not section_id:
                emit("layout", f"No section '{section_label}' on {wit_name}/{page_name}")
                stats["warnings"] += 1
                continue

            if field.get("is_html") or field_type.lower() == "html":
                ok = _add_html_control(
                    client,
                    process_id,
                    enc_wit,
                    page_id,
                    section_id,
                    ref,
                    label,
                    group_name,
                    group_order,
                    order,
                    layout,
                )
                if ok:
                    stats["html_controls"] += 1
                else:
                    emit("layout", f"HTML control {ref} on {wit_name}: failed")
                    stats["warnings"] += 1
                continue

            group_id = _ensure_group(
                client, process_id, enc_wit, page_id, section_id, layout, group_name, group_order
            )
            if not group_id:
                emit("layout", f"Could not ensure group '{group_name}' on {wit_name}")
                stats["warnings"] += 1
                continue

            # Refresh layout so the new group is present before control POST.
            try:
                layout = client.get(
                    f"/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}/layout",
                    api_version="7.1-preview.1",
                )
            except AdoError:
                pass

            if _add_control_to_group(
                client,
                process_id,
                enc_wit,
                group_id,
                field,
                label,
                order,
                emit=emit,
            ):
                stats["controls"] += 1
            else:
                stats["warnings"] += 1

    emit(
        "layout",
        f"Layout apply finished: {stats['wits_processed']} WITs, "
        f"{stats['html_controls']} HTML controls, {stats['controls']} other controls"
        + (
            f", {stats['hidden_fields']} hidden (H) fields "
            f"({stats['controls_hidden']} existing controls hidden)"
            if stats["hidden_fields"]
            else ""
        )
        + (f", {stats['controls_shown']} controls un-hidden" if stats["controls_shown"] else ""),
    )
    return stats


def _find_control(
    layout: dict[str, Any] | None, field_ref: str
) -> tuple[str | None, dict[str, Any] | None]:
    """Return (group id, control) for the field's control anywhere on the form."""
    target = field_ref.lower()
    for page in (layout or {}).get("pages") or []:
        for section in page.get("sections") or []:
            for group in section.get("groups") or []:
                for control in group.get("controls") or []:
                    if str(control.get("id") or "").lower() == target:
                        return group.get("id"), control
    return None, None


def _set_control_visibility(
    client: AdoClient,
    process_id: str,
    enc_wit: str,
    group_id: str | None,
    field_ref: str,
    *,
    visible: bool,
    emit: Emit,
) -> bool:
    if not group_id:
        return False
    try:
        client.patch(
            f"/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}"
            f"/layout/groups/{quote(group_id, safe='')}/controls/{quote(field_ref, safe='')}",
            json_body={"id": field_ref, "visible": visible},
            api_version="7.1-preview.1",
        )
        return True
    except AdoError as exc:
        emit(
            "layout",
            f"{'Show' if visible else 'Hide'} control {field_ref}: {exc}",
        )
        return False


def _has_default(field: dict[str, Any]) -> bool:
    if _is_boolean_field(field):
        return True
    value = str(field.get("default_value") or "").strip()
    return bool(value) and value.lower() != "none"


MULTIVALUE_CONTRIBUTION_ID = (
    "ms-devlabs.vsts-extensions-multivalue-control.multivalue-form-control"
)


def _control_type(field: dict[str, Any] | str, reference_name: str = "") -> str:
    """Reference get_control_type — default is ``Field``, not FieldControl."""
    if isinstance(field, dict):
        field_type = field.get("field_type") or ""
        reference_name = field.get("reference_name") or reference_name
        is_picklist = (field_type or "").lower().startswith("picklist")
        if field.get("multi_select") and is_picklist:
            return "MultivalueContribution"
    else:
        field_type = field
        is_picklist = (field_type or "").lower().startswith("picklist")

    ft = (field_type or "").strip().lower()
    ref = (reference_name or "").strip().lower()

    if ref in {
        "system.areaid",
        "system.area",
        "system.areapath",
        "system.iterationid",
        "system.iteration",
        "system.iterationpath",
    }:
        return "WorkItemClassificationControl"
    if ref in {
        "system.assignedto",
        "system.createdby",
        "system.changedby",
        "system.authorizedas",
        "system.owner",
        "system.requestedby",
    } or ft == "identity":
        return "IdentityControl"
    if ref in {
        "system.createddate",
        "system.changeddate",
        "system.resolveddate",
        "system.closeddate",
    } or ft in {"datetime", "date time"}:
        return "DateTimeControl"
    if ft in {"boolean", "bool"}:
        return "BooleanControl"
    if ft == "html":
        return "HtmlFieldControl"
    if is_picklist:
        if ft in {"integer", "picklistinteger"}:
            return "PickListIntegerControl"
        return "PickListStringControl"
    return "Field"


def _ensure_page(
    client: AdoClient,
    process_id: str,
    enc_wit: str,
    layout: dict[str, Any] | None,
    page_name: str,
    order: int,
    emit: Emit,
    wit_name: str,
) -> tuple[str | None, dict[str, Any] | None]:
    page = _find_page(layout, page_name)
    if page and page.get("id"):
        return page.get("id"), layout
    try:
        created = client.post(
            f"/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}/layout/pages",
            json_body={
                "label": page_name,
                "order": order,
                "visible": True,
                "inherited": True,
            },
            api_version="7.1-preview.1",
        )
        page_id = created.get("id") if created else None
        layout = client.get(
            f"/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}/layout",
            api_version="7.1-preview.1",
        )
        if not page_id:
            page = _find_page(layout, page_name)
            page_id = page.get("id") if page else None
        return page_id, layout
    except AdoError as exc:
        if exc.status in {400, 409}:
            try:
                layout = client.get(
                    f"/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}/layout",
                    api_version="7.1-preview.1",
                )
            except AdoError:
                return None, layout
            page = _find_page(layout, page_name)
            return (page.get("id") if page else None), layout
        emit("layout", f"Could not create page '{page_name}' on {wit_name}: {exc}")
        return None, layout


def _add_control_to_group(
    client: AdoClient,
    process_id: str,
    enc_wit: str,
    group_id: str,
    field: dict[str, Any],
    label: str,
    order: int,
    *,
    emit: Emit,
) -> bool:
    ref = field.get("reference_name")
    if not ref or not group_id:
        return False
    control_type = _control_type(field)
    bodies: list[dict[str, Any]] = []
    if control_type == "MultivalueContribution":
        # DevLabs multivalue control (reference Script 2). Extension must be installed
        # on the org; fall back to native picklist control if contribution fails.
        bodies.append(
            {
                "id": ref,
                "label": label,
                "visible": True,
                "inherited": False,
                "order": order,
                "isContribution": True,
                "contribution": {
                    "contributionId": MULTIVALUE_CONTRIBUTION_ID,
                    "inputs": {"FieldName": ref},
                },
            }
        )
        bodies.append(
            {
                "id": ref,
                "label": label,
                "controlType": "PickListStringControl",
                "visible": True,
                "inherited": True,
                "order": order,
            }
        )
    else:
        type_candidates = [control_type]
        if control_type == "Field":
            type_candidates.append("FieldControl")
        elif control_type == "FieldControl":
            type_candidates.append("Field")
        for candidate in type_candidates:
            bodies.append(
                {
                    "id": ref,
                    "label": label,
                    "controlType": candidate,
                    "visible": True,
                    "inherited": True,
                    "order": order,
                }
            )

    last_error: AdoError | None = None
    for body in bodies:
        try:
            client.post(
                f"/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}"
                f"/layout/groups/{quote(group_id, safe='')}/controls",
                json_body=body,
                api_version="7.1-preview.1",
            )
            return True
        except AdoError as exc:
            if exc.status in {409}:
                return True
            last_error = exc
            continue
    if last_error:
        emit("layout", f"Control {ref} ({control_type}): {last_error}")
    return False


def _is_boolean_field(field: dict[str, Any]) -> bool:
    return (field.get("field_type") or "").strip().lower() in {"boolean", "bool"}


def _parse_required(value: Any) -> bool:
    return str(value or "").strip().lower() in {"yes", "true", "1", "y"}


def _wit_field_payload(field: dict[str, Any]) -> dict[str, Any]:
    ref = field["reference_name"]
    required = _parse_required(field.get("required"))
    if _is_boolean_field(field):
        # VS402851: Boolean WIT fields must default to false. ADO Process API
        # accepts the string "false" more reliably than JSON false.
        return {
            "referenceName": ref,
            "defaultValue": "false",
            "required": required,
            "requiredValue": "false",
            "visible": True,
        }
    payload: dict[str, Any] = {
        "referenceName": ref,
        "required": required,
        "visible": True,
    }
    field_type = (field.get("field_type") or "").strip().lower()
    if field_type == "identity":
        payload["allowGroups"] = True
    default_value = field.get("default_value")
    if default_value is not None and str(default_value).strip() and str(default_value).strip().lower() != "none":
        payload["defaultValue"] = default_value
    return payload


def _boolean_field_variants(ref: str) -> list[dict[str, Any]]:
    """Reference-script compatible retry payloads (VS403099 / VS402851)."""
    variants: list[dict[str, Any]] = [
        {"referenceName": ref, "defaultValue": "false", "visible": True},
        {"referenceName": ref, "defaultValue": False, "visible": True},
    ]
    for required in (False, True):
        variants.extend(
            [
                {
                    "referenceName": ref,
                    "defaultValue": "false",
                    "required": required,
                    "visible": True,
                },
                {
                    "referenceName": ref,
                    "defaultValue": "false",
                    "required": required,
                    "requiredValue": "false",
                    "visible": True,
                },
                {
                    "referenceName": ref,
                    "defaultValue": False,
                    "required": required,
                    "visible": True,
                },
                {
                    "referenceName": ref,
                    "defaultValue": False,
                    "required": required,
                    "requiredValue": False,
                    "visible": True,
                },
            ]
        )
    return variants


def _ensure_field_on_wit(
    client: AdoClient,
    process_id: str,
    enc_wit: str,
    field: dict[str, Any],
    *,
    emit: Emit,
    wit_name: str,
) -> bool | None:
    """Add field to WIT. Returns True if newly added, None if already present, False on failure."""
    ref = field.get("reference_name")
    if not ref:
        return False
    # Prefer the reference scripts' camelCase segment; ADO accepts both, but match the script path.
    path = f"/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}/fields"
    payloads = [_wit_field_payload(field)]
    if _is_boolean_field(field):
        payloads.extend(_boolean_field_variants(ref))

    last_error: AdoError | None = None
    for payload in payloads:
        try:
            client.post(path, json_body=payload, api_version="7.1-preview.2")
            return True
        except AdoError as exc:
            if exc.status in {400, 409}:
                return None
            last_error = exc
            continue

    if last_error:
        kind = "boolean field" if _is_boolean_field(field) else "field"
        emit("layout", f"Add {kind} {ref} on {wit_name}: {last_error}")
    return False


SYSTEM_WIT_PREFIX = "Microsoft.VSTS.WorkItemTypes."


def _is_system_reference(reference_name: str) -> bool:
    return str(reference_name or "").strip().startswith(SYSTEM_WIT_PREFIX)


def _index_process_wits(wits: list[dict[str, Any]]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for wit in wits:
        name = str(wit.get("name") or "").strip()
        ref = str(wit.get("referenceName") or "").strip()
        for key in {
            name.lower(),
            name.replace(" ", "").lower(),
            ref.lower(),
            ref.rsplit(".", 1)[-1].lower() if ref else "",
        }:
            if key:
                index[key] = wit
    return index


def _resolve_process_wit(
    index: dict[str, Any], wit_name: str, excel_ref: str
) -> dict[str, Any] | None:
    for candidate in (
        wit_name,
        excel_ref,
        wit_name.replace(" ", ""),
        excel_ref.rsplit(".", 1)[-1] if excel_ref else "",
        f"{SYSTEM_WIT_PREFIX}{wit_name.replace(' ', '')}",
    ):
        text = str(candidate or "").strip()
        if not text:
            continue
        hit = index.get(text.lower()) or index.get(text.replace(" ", "").lower())
        if hit:
            return hit
    return None


def _process_api_wit_id(wit_name: str, wit_ref: str, process_wit: dict[str, Any]) -> str:
    """System Microsoft.VSTS.* refs often need the display name on Process APIs."""
    resolved_ref = str(process_wit.get("referenceName") or wit_ref or "").strip()
    resolved_name = str(process_wit.get("name") or wit_name or "").strip()
    if resolved_ref.startswith(SYSTEM_WIT_PREFIX):
        return resolved_name or wit_name or resolved_ref
    return resolved_ref or resolved_name or wit_name


def _materialize_system_wit(
    client: AdoClient,
    process_id: str,
    wit_ref: str,
    wit_info: dict[str, Any],
) -> bool:
    customization = str(wit_info.get("customization") or "").strip().lower()
    if customization in {"inherited", "custom"}:
        return True
    if not _is_system_reference(wit_ref):
        return True
    payload = {
        "description": wit_info.get("description"),
        "color": wit_info.get("color"),
        "icon": wit_info.get("icon"),
        "isDisabled": wit_info.get("isDisabled", False),
    }
    try:
        client.patch(
            f"/_apis/work/processes/{process_id}/workItemTypes/{quote(wit_ref, safe='')}",
            json_body=payload,
            api_version="7.1-preview.2",
        )
        wit_info["customization"] = "inherited"
        # Also try display-name path used by some tenants.
        return True
    except AdoError as exc:
        if exc.status in {400, 409}:
            wit_info["customization"] = "inherited"
            return True
        # Retry materialize using display name (reference fallback path).
        display = str(wit_info.get("name") or "").strip()
        if display and display != wit_ref:
            try:
                client.patch(
                    f"/_apis/work/processes/{process_id}/workItemTypes/{quote(display, safe='')}",
                    json_body=payload,
                    api_version="7.1-preview.2",
                )
                wit_info["customization"] = "inherited"
                return True
            except AdoError as retry_exc:
                if retry_exc.status in {400, 409}:
                    wit_info["customization"] = "inherited"
                    return True
        return False


def _find_page(layout: dict[str, Any] | None, label: str) -> dict[str, Any] | None:
    if not layout:
        return None
    target = label.strip().lower()
    for page in layout.get("pages") or []:
        if str(page.get("label") or "").strip().lower() == target:
            return page
    return None


def _section_id(layout: dict[str, Any] | None, page_id: str, section_label: str) -> str | None:
    page = None
    for candidate in (layout or {}).get("pages") or []:
        if candidate.get("id") == page_id:
            page = candidate
            break
    if not page:
        return None
    sections = page.get("sections") or []
    if not sections:
        return None
    target = section_label.strip().lower().replace(" ", "")
    for section in sections:
        sid = str(section.get("id") or "").lower().replace(" ", "")
        slabel = str(section.get("label") or "").lower().replace(" ", "")
        if sid == target or slabel == target:
            return section.get("id")
    # Do not fall back to sections[0] — that silently misplaces controls.
    return None


def _control_exists_on_page(
    layout: dict[str, Any] | None, page_id: str | None, field_ref: str
) -> bool:
    if not layout:
        return False
    for page in layout.get("pages") or []:
        if page_id and page.get("id") != page_id:
            continue
        for section in page.get("sections") or []:
            for group in section.get("groups") or []:
                for control in group.get("controls") or []:
                    if control.get("id") == field_ref:
                        return True
    return False


def _ensure_group(
    client: AdoClient,
    process_id: str,
    enc_wit: str,
    page_id: str,
    section_id: str,
    layout: dict[str, Any] | None,
    group_label: str,
    group_order: int = 1,
) -> str | None:
    for page in (layout or {}).get("pages") or []:
        if page.get("id") != page_id:
            continue
        for section in page.get("sections") or []:
            for group in section.get("groups") or []:
                if str(group.get("label") or "").strip().lower() == group_label.strip().lower():
                    return group.get("id")
    try:
        created = client.post(
            f"/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}/layout/pages/"
            f"{page_id}/sections/{section_id}/groups",
            json_body={
                "label": group_label,
                "order": group_order,
                "visible": True,
                "inherited": True,
                "controls": [],
            },
            api_version="7.1-preview.1",
        )
        return created.get("id") if created else None
    except AdoError:
        return None


def _add_html_control(
    client: AdoClient,
    process_id: str,
    enc_wit: str,
    page_id: str,
    section_id: str,
    ref: str,
    label: str,
    group_name: str,
    group_order: int,
    field_order: int,
    layout: dict[str, Any] | None,
) -> bool:
    """HTML controls must be created inside a new group payload (reference layout behavior)."""
    if _control_exists_on_page(layout, page_id, ref):
        return True
    try:
        client.post(
            f"/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}/layout/pages/"
            f"{page_id}/sections/{section_id}/groups",
            json_body={
                "label": group_name or label,
                "order": group_order,
                "visible": True,
                "inherited": True,
                "controls": [
                    {
                        "id": ref,
                        "label": label,
                        "order": field_order,
                        "controlType": "HtmlFieldControl",
                        "visible": True,
                        "readOnly": False,
                        "metadata": "",
                        "watermark": "",
                        "height": 250,
                    }
                ],
            },
            api_version="7.1-preview.1",
        )
        return True
    except AdoError as exc:
        if exc.status in {400, 409}:
            return True
        return False
