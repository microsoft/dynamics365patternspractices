"""Apply process shell, work item types, picklists, and custom fields."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from ..ado_client import AdoClient, AdoError

Emit = Callable[[str, str], None]


def multiselect_field_labels(ir: dict[str, Any]) -> set[str]:
    """Labels marked Multi-select on the Fields sheet (suggested picklists)."""
    return {
        str(field.get("label") or field.get("field_name") or "").strip()
        for field in ir.get("process", {}).get("fields") or []
        if field.get("multi_select") and (field.get("label") or field.get("field_name"))
    }


def apply_process(
    client: AdoClient,
    ir: dict[str, Any],
    *,
    dry_run: bool,
    emit: Emit,
) -> dict[str, Any]:
    process_name = ir["targets"]["process_name"]
    stats = {
        "process_id": None,
        "wits_created": 0,
        "wits_updated": 0,
        "wits_disabled": 0,
        "wits_skipped": 0,
        "picklists": 0,
        "fields_created": 0,
        "fields_updated": 0,
        "fields_skipped": 0,
    }
    disabled_count = int(ir["counts"].get("disabled_work_item_types") or 0)

    if dry_run:
        emit(
            "process",
            f"[dry-run] Would ensure process '{process_name}' with "
            f"{ir['counts']['work_item_types']} WITs / {disabled_count} disabled / "
            f"{ir['counts']['fields']} fields / "
            f"{ir['counts']['html_fields']} HTML fields",
        )
        return stats

    process_id = client.create_process(process_name)
    stats["process_id"] = process_id
    emit("process", f"Process ready: {process_name} ({process_id})")

    existing = _index_process_wits(client.list_process_wits(process_id))

    for wit in ir["process"]["work_item_types"]:
        name = wit["name"]
        custom = bool(wit.get("custom"))
        disabled = bool(wit.get("disabled"))
        ref_name = (wit.get("reference_name") or _build_ref(process_name, name)).strip()
        color = (wit.get("color") or "0078D4").lstrip("#")
        icon = wit.get("icon") or "icon_gear"
        description = wit.get("help_text") or ""

        existing_wit = _resolve_existing_wit(existing, name, ref_name)
        system_ref = _is_system_reference(ref_name)

        # Disabled system WITs (Epic/Feature/User Story): materialize process-local
        # inheritance then PATCH isDisabled. Layout/backlog skip disabled rows.
        if disabled:
            try:
                process_ref = _ensure_process_local_wit(
                    client,
                    process_id,
                    existing,
                    name=name,
                    ref_name=ref_name,
                    color=color,
                    icon=icon,
                    description=description,
                    custom=custom,
                    system_ref=system_ref,
                    stats=stats,
                    emit=emit,
                )
                if not process_ref:
                    stats["wits_skipped"] += 1
                    emit(
                        "process",
                        f"WIT '{name}' is Disabled in Excel but could not be "
                        "materialized for disable — set Disabled in ADO Process UI.",
                    )
                    continue
                client.patch(
                    f"/_apis/work/processes/{process_id}/workItemTypes/"
                    f"{quote(str(process_ref), safe='')}",
                    json_body={"isDisabled": True},
                    api_version="7.1-preview.2",
                )
                stats["wits_disabled"] += 1
                emit("process", f"Disabled WIT '{name}' ({process_ref})")
            except AdoError as exc:
                stats["wits_skipped"] += 1
                emit(
                    "process",
                    f"WIT '{name}' disable failed ({exc}). "
                    "Disable it manually in Organization Settings → Process.",
                )
            continue

        # Reference-script behavior:
        # - Custom=No + Microsoft.VSTS.* → create process-local WIT inheriting the OOB type
        # - Custom=Yes → create custom WIT; do NOT pass Excel Inherit from by default
        #   (avoids duplicate inherited system WIT conflicts)
        if not custom:
            if not system_ref:
                stats["wits_skipped"] += 1
                continue
            local_ref = _short_reference_name(ref_name)
            inherit_from = ref_name
            create_ref = local_ref
        else:
            inherit_from = ""
            create_ref = _short_reference_name(ref_name) or name.replace(" ", "")

        payload: dict[str, Any] = {
            "name": name,
            "description": description,
            "color": color,
            "icon": icon,
            "referenceName": create_ref,
        }
        if inherit_from:
            payload["inheritsFrom"] = inherit_from

        try:
            customization = str((existing_wit or {}).get("customization") or "").strip().lower()
            # System entries in the process list are not process-local yet — create/inherit.
            if existing_wit and customization not in {"", "system"}:
                full_ref = existing_wit.get("referenceName") or ref_name
                client.patch(
                    f"/_apis/work/processes/{process_id}/workItemTypes/{quote(str(full_ref), safe='')}",
                    json_body={
                        "description": description,
                        "color": color,
                        "icon": icon,
                    },
                    api_version="7.1-preview.2",
                )
                stats["wits_updated"] += 1
            else:
                created = client.post(
                    f"/_apis/work/processes/{process_id}/workItemTypes",
                    json_body=payload,
                    api_version="7.1-preview.2",
                )
                if created:
                    _index_one_wit(existing, created)
                stats["wits_created"] += 1
        except AdoError as exc:
            if exc.status == 409:
                stats["wits_skipped"] += 1
            else:
                emit("process", f"WIT '{name}' warning: {exc}")

    # Refresh after creates so later steps see process-local refs (Process.Bug, etc.)
    existing = _index_process_wits(client.list_process_wits(process_id))

    # Multi-select Labels (Application family, Products, Industries, …) use
    # suggested-picklist semantics so semicolon-separated values can be stored;
    # layout then binds the DevLabs multivalue control.
    multiselect_labels = multiselect_field_labels(ir)
    if multiselect_labels:
        emit(
            "process",
            "Multi-value picklists (suggested): "
            + ", ".join(sorted(multiselect_labels)),
        )

    # Picklists
    lists_data = client.get("/_apis/work/processes/lists", api_version="7.1") or {}
    existing_lists = {item.get("name"): item for item in lists_data.get("value") or []}
    for label, values in ir["process"]["picklists"].items():
        payload = {
            "name": label,
            "type": "String",
            "items": values,
            # Suggested lists accept stored values beyond a single picklist token
            # (semicolon composites for multi-select / DevLabs).
            "isSuggested": label in multiselect_labels,
        }
        try:
            if label in existing_lists:
                picklist_id = existing_lists[label]["id"]
                client.put(
                    f"/_apis/work/processes/lists/{picklist_id}",
                    json_body=payload,
                    api_version="7.1",
                )
            else:
                client.post("/_apis/work/processes/lists", json_body=payload, api_version="7.1")
            stats["picklists"] += 1
        except AdoError as exc:
            emit("process", f"Picklist '{label}' warning: {exc}")

    # Refresh picklist ids for field create
    lists_data = client.get("/_apis/work/processes/lists", api_version="7.1") or {}
    picklist_ids = {item.get("name"): item.get("id") for item in lists_data.get("value") or []}

    fields_data = client.get("/_apis/wit/fields", api_version="7.1") or {}
    existing_fields = {
        str(item.get("referenceName") or "").lower(): item for item in fields_data.get("value") or []
    }

    for field in ir["process"]["fields"]:
        if not field.get("custom_field"):
            stats["fields_skipped"] += 1
            continue
        reference = field.get("reference_name")
        if not reference:
            continue
        field_type = field.get("field_type") or "String"
        label = field.get("label") or field.get("field_name")
        name = field.get("field_name") or label
        description = field.get("description") or ""
        is_multi = bool(field.get("multi_select"))

        if field_type in {"PicklistString", "PicklistInteger"}:
            picklist_id = picklist_ids.get(label)
            if not picklist_id:
                emit("process", f"Skipping field '{label}' — missing picklist")
                stats["fields_skipped"] += 1
                continue
            payload = {
                "name": name,
                "referenceName": reference,
                "type": "String",
                "isPicklist": True,
                "isPicklistSuggested": is_multi,
                "picklistId": picklist_id,
                "description": description,
            }
        else:
            payload = {
                "name": name,
                "type": field_type,
                "referenceName": reference,
                "description": description,
            }

        try:
            if reference.lower() in existing_fields:
                client.patch(
                    f"/_apis/wit/fields/{quote(reference, safe='')}",
                    json_body=payload,
                    api_version="7.1",
                )
                stats["fields_updated"] += 1
            else:
                client.post("/_apis/wit/fields", json_body=payload, api_version="7.1")
                stats["fields_created"] += 1
        except AdoError as exc:
            emit("process", f"Field '{reference}' warning: {exc}")

    emit(
        "process",
        "Process apply finished: "
        f"WITs +{stats['wits_created']}/~{stats['wits_updated']}/"
        f"disabled {stats['wits_disabled']}, "
        f"fields +{stats['fields_created']}/~{stats['fields_updated']}, "
        f"HTML fields in template: {ir['counts'].get('html_fields', 0)}",
    )
    return stats


def _ensure_process_local_wit(
    client: AdoClient,
    process_id: str,
    existing: dict[str, Any],
    *,
    name: str,
    ref_name: str,
    color: str,
    icon: str,
    description: str,
    custom: bool,
    system_ref: bool,
    stats: dict[str, Any],
    emit: Emit,
) -> str | None:
    """Return a process-local WIT referenceName suitable for isDisabled PATCH."""
    existing_wit = _resolve_existing_wit(existing, name, ref_name)
    if existing_wit:
        customization = str(existing_wit.get("customization") or "").strip().lower()
        full_ref = str(existing_wit.get("referenceName") or "").strip()
        if full_ref and customization not in {"", "system"}:
            return full_ref

    if custom:
        create_ref = _short_reference_name(ref_name) or name.replace(" ", "")
        payload: dict[str, Any] = {
            "name": name,
            "description": description,
            "color": color,
            "icon": icon,
            "referenceName": create_ref,
        }
    elif system_ref:
        payload = {
            "name": name,
            "description": description,
            "color": color,
            "icon": icon,
            "referenceName": _short_reference_name(ref_name),
            "inheritsFrom": ref_name,
        }
    else:
        return None

    try:
        created = client.post(
            f"/_apis/work/processes/{process_id}/workItemTypes",
            json_body=payload,
            api_version="7.1-preview.2",
        )
        if created:
            _index_one_wit(existing, created)
            stats["wits_created"] += 1
            return str(created.get("referenceName") or payload["referenceName"])
    except AdoError as exc:
        if exc.status == 409:
            # Already process-local — refresh index and resolve again.
            refreshed = _index_process_wits(client.list_process_wits(process_id))
            existing.clear()
            existing.update(refreshed)
            again = _resolve_existing_wit(existing, name, ref_name)
            if again:
                ref = str(again.get("referenceName") or "").strip()
                customization = str(again.get("customization") or "").strip().lower()
                if ref and customization not in {"", "system"}:
                    return ref
        else:
            emit("process", f"WIT '{name}' materialize for disable: {exc}")
    return None


def _build_ref(process_name: str, wit_name: str) -> str:
    safe_process = process_name.replace(" ", "")
    safe_name = wit_name.replace(" ", "").replace("-", "").replace("_", "")
    return f"{safe_process}.{safe_name}"


SYSTEM_WIT_PREFIX = "Microsoft.VSTS.WorkItemTypes."


def _is_system_reference(reference_name: str) -> bool:
    return str(reference_name or "").strip().startswith(SYSTEM_WIT_PREFIX)


def _short_reference_name(reference_name: str) -> str:
    text = str(reference_name or "").strip()
    return text.rsplit(".", 1)[-1] if "." in text else text


def _index_one_wit(index: dict[str, Any], wit: dict[str, Any]) -> None:
    name = str(wit.get("name") or "").strip()
    ref = str(wit.get("referenceName") or "").strip()
    keys = set()
    if name:
        keys.add(name.lower())
        keys.add(name.replace(" ", "").lower())
    if ref:
        keys.add(ref.lower())
        keys.add(ref.rsplit(".", 1)[-1].lower())
    for key in keys:
        index[key] = wit


def _index_process_wits(wits: list[dict[str, Any]]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for wit in wits:
        _index_one_wit(index, wit)
    return index


def _resolve_existing_wit(
    index: dict[str, Any], name: str, reference_name: str
) -> dict[str, Any] | None:
    for candidate in (name, reference_name, _short_reference_name(reference_name)):
        text = str(candidate or "").strip()
        if not text:
            continue
        for key in (text.lower(), text.replace(" ", "").lower()):
            if key in index:
                return index[key]
    return None
