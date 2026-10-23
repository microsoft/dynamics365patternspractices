"""Configure backlog behaviors, iteration paths, and per-team iteration settings.

Mirrors reference Script 4: create iteration nodes, then for each Teams-sheet row set
bug behavior / backlog iteration and POST every iteration onto the team.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
from urllib.parse import quote

from ..ado_client import AdoClient, AdoError

Emit = Callable[[str, str], None]


def apply_backlog(
    client: AdoClient,
    ir: dict[str, Any],
    *,
    dry_run: bool,
    emit: Emit,
    process_id: str | None = None,
    workers: int = 1,
    process_changes: bool = True,
) -> dict[str, Any]:
    """``workers`` > 1 configures teams in parallel (each team's requests stay in order).

    ``process_changes=False`` (skip-existing on an existing process) leaves the process's
    backlog levels and WIT assignments alone and only sets up iterations and teams.
    """
    project = ir["targets"]["project_name"]
    process_name = ir["targets"]["process_name"]
    stats = {
        "behaviors": 0,
        "wit_assignments": 0,
        "default_wits": 0,
        "iterations": 0,
        "team_settings": 0,
        "team_iterations": 0,
        "warnings": 0,
    }
    enabled_wit_backlogs = sum(
        1
        for wit in ir["process"].get("work_item_types") or []
        if not wit.get("disabled")
        and (wit.get("backlog_name") or "").strip()
        and (wit.get("backlog_name") or "").strip().lower() != "no associated backlog"
    )

    if dry_run:
        process_part = (
            f"configure {ir['counts']['backlogs']} backlog levels "
            f"(rename/create from Backlogs sheet), assign {enabled_wit_backlogs} WITs, "
            if process_changes
            else "leave the existing process's backlog levels as they are (skip-existing), "
        )
        emit(
            "backlog",
            f"[dry-run] Would {process_part}"
            f"create {ir['counts']['iteration_paths']} iterations, and assign iterations "
            f"to {ir['counts']['teams']} teams. No Azure DevOps teamsettings changes.",
        )
        return {
            **stats,
            "behaviors": int(ir["counts"].get("backlogs") or 0) if process_changes else 0,
            "wit_assignments": enabled_wit_backlogs if process_changes else 0,
            "iterations": int(ir["counts"].get("iteration_paths") or 0),
            "team_settings": int(ir["counts"].get("teams") or 0),
            "dry_run": True,
        }

    if process_changes:
        process_id = process_id or client.get_process_id(process_name)
        if not process_id:
            raise AdoError(f'Process "{process_name}" not found for backlog apply.')
        backlog_refs = _configure_backlog_levels(client, ir, process_id, stats, emit)
        _assign_wits_to_backlogs(client, ir, process_id, backlog_refs, stats, emit)
        _set_default_wits(client, ir, process_id, backlog_refs, stats, emit)
    else:
        emit(
            "backlog",
            f"Process '{process_name}' already exists and the policy is skip-existing: "
            "its backlog levels and work item type assignments were left as they are",
        )
    _create_iteration_nodes(client, ir, project, stats, emit)

    tree = _fetch_iteration_tree(client, project, emit)
    if not tree:
        emit(
            "backlog",
            "WARNING: Could not load iteration classification tree; "
            "skipping team backlog/iteration assignment",
        )
        stats["warnings"] += 1
    else:
        root_id, iteration_map, child_ids = _index_iteration_tree(tree, project)
        if not root_id:
            emit(
                "backlog",
                "WARNING: Iteration root has no identifier GUID — cannot set team "
                "Backlog iteration (ADO will leave it blank and block Select iteration).",
            )
            stats["warnings"] += 1
        else:
            emit(
                "backlog",
                f"Iteration root GUID {root_id} ({len(child_ids)} child iteration(s) to assign)",
            )
            _configure_team_iterations(
                client,
                ir,
                project,
                root_id=root_id,
                iteration_map=iteration_map,
                child_ids=child_ids,
                stats=stats,
                emit=emit,
                workers=workers,
            )

    emit(
        "backlog",
        f"Backlog apply finished: {stats['behaviors']} behaviors, "
        f"{stats['wit_assignments']} WIT assignments, "
        f"{stats['default_wits']} default WITs, "
        f"{stats['iterations']} iterations created, "
        f"{stats['team_settings']} team settings, "
        f"{stats['team_iterations']} team-iteration links",
    )
    return stats


# Reference Script 4: rename-from display names / known Agile behavior refs.
KNOWN_BEHAVIOR_RENAMES = {
    "Epic": "Epics",
    "Feature": "Features",
}
KNOWN_BEHAVIOR_REFS = {
    "Epic": "Microsoft.VSTS.Agile.EpicBacklogBehavior",
    "Feature": "Microsoft.VSTS.Agile.FeatureBacklogBehavior",
}
PORTFOLIO_PARENT_BEHAVIOR = "System.PortfolioBacklogBehavior"
TYPE_RENAME_REFS = {
    "requirements backlog": "System.RequirementBacklogBehavior",
    "iteration backlog": "System.TaskBacklogBehavior",
}
BEHAVIOR_API = "7.1-preview.2"
WIT_BEHAVIOR_API = "7.1-preview.1"


def _list_behaviors(client: AdoClient, process_id: str) -> list[dict[str, Any]]:
    data = client.get(
        f"/_apis/work/processes/{process_id}/behaviors",
        api_version=BEHAVIOR_API,
    ) or {}
    return list(data.get("value") or [])


def _behavior_indexes(
    behaviors: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_name = {str(b.get("name") or "").strip(): b for b in behaviors if b.get("name")}
    by_name_ci = {k.lower(): v for k, v in by_name.items()}
    by_ref = {
        str(b.get("referenceName") or "").strip(): b
        for b in behaviors
        if b.get("referenceName")
    }
    return by_name, by_name_ci, by_ref


def _find_rename_source(
    rename_from: str,
    by_name: dict[str, dict[str, Any]],
    by_name_ci: dict[str, dict[str, Any]],
    by_ref: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    """Locate the Agile behavior that Excel Rename-from refers to."""
    old_display = KNOWN_BEHAVIOR_RENAMES.get(rename_from, rename_from)
    source = by_name.get(old_display) or by_name_ci.get(old_display.lower())
    if not source:
        source = by_name.get(rename_from) or by_name_ci.get(rename_from.lower())
    if not source:
        known_ref = KNOWN_BEHAVIOR_REFS.get(rename_from)
        if known_ref:
            source = by_ref.get(known_ref)
    if source:
        old_display = str(source.get("name") or old_display)
    return source, old_display


def _is_custom_portfolio_behavior(behavior: dict[str, Any]) -> bool:
    """True for process-created portfolio levels (safe to delete when duplicated)."""
    ref = str(behavior.get("referenceName") or "")
    if ref in KNOWN_BEHAVIOR_REFS.values():
        return False
    if ref in TYPE_RENAME_REFS.values():
        return False
    if ref.startswith("System.") or ref.startswith("Microsoft.VSTS."):
        return False
    return True


def _put_behavior_name(
    client: AdoClient,
    process_id: str,
    ref: str,
    name: str,
    color: str | None,
) -> None:
    payload: dict[str, Any] = {"name": name}
    if color:
        payload["color"] = color
    client.put(
        f"/_apis/work/processes/{process_id}/behaviors/{quote(ref, safe='')}",
        json_body=payload,
        api_version=BEHAVIOR_API,
    )


def _delete_behavior(
    client: AdoClient,
    process_id: str,
    ref: str,
    emit: Emit,
    stats: dict[str, Any],
) -> bool:
    try:
        client.delete(
            f"/_apis/work/processes/{process_id}/behaviors/{quote(ref, safe='')}",
            api_version=BEHAVIOR_API,
        )
        return True
    except AdoError as exc:
        emit("backlog", f"WARNING: Could not delete duplicate backlog '{ref}': {exc}")
        stats["warnings"] += 1
        return False


def _claim_target_name_for_source(
    client: AdoClient,
    process_id: str,
    *,
    name: str,
    color: str | None,
    source: dict[str, Any],
    old_display: str,
    by_name: dict[str, dict[str, Any]],
    by_name_ci: dict[str, dict[str, Any]],
    by_ref: dict[str, dict[str, Any]],
    emit: Emit,
    stats: dict[str, Any],
) -> str | None:
    """Ensure ``source`` is renamed to ``name``, removing a colliding custom level if needed.

    Earlier buggy applies created Levels/Lowest as *new* portfolio behaviors while leaving
    system Epics/Features in place. Prefer the Agile/system behavior and drop the duplicate.
    """
    source_ref = str(source.get("referenceName") or "").strip()
    if not source_ref:
        return None

    occupying = by_name.get(name) or by_name_ci.get(name.lower())
    occupying_ref = str((occupying or {}).get("referenceName") or "").strip()

    # Already the correct behavior under the target name.
    if occupying_ref and occupying_ref == source_ref:
        if color:
            try:
                _put_behavior_name(client, process_id, source_ref, name, color)
            except AdoError as exc:
                emit("backlog", f"WARNING: Could not update color for '{name}': {exc}")
                stats["warnings"] += 1
        return source_ref

    # Name taken by a different (usually custom) behavior — free it, then rename source.
    if occupying and occupying_ref and occupying_ref != source_ref:
        if _is_custom_portfolio_behavior(occupying):
            emit(
                "backlog",
                f"Removing duplicate custom backlog '{name}' ({occupying_ref}) so "
                f"'{old_display}' can be renamed to '{name}'",
            )
            if _delete_behavior(client, process_id, occupying_ref, emit, stats):
                by_name.pop(name, None)
                by_name_ci.pop(name.lower(), None)
                by_ref.pop(occupying_ref, None)
            else:
                # Move the duplicate aside so the rename can claim the display name.
                aside = f"_bpctool_dup_{name}"
                try:
                    _put_behavior_name(client, process_id, occupying_ref, aside, None)
                    by_name.pop(name, None)
                    by_name_ci.pop(name.lower(), None)
                    by_name[aside] = {**occupying, "name": aside}
                    by_name_ci[aside.lower()] = by_name[aside]
                    emit(
                        "backlog",
                        f"Renamed duplicate '{name}' → '{aside}' ({occupying_ref}); "
                        "delete it manually in Process → Backlog levels if it remains",
                    )
                except AdoError as exc:
                    emit(
                        "backlog",
                        f"WARNING: Could not free backlog name '{name}' "
                        f"(held by {occupying_ref}): {exc}",
                    )
                    stats["warnings"] += 1
                    return occupying_ref
        else:
            emit(
                "backlog",
                f"WARNING: Backlog name '{name}' is held by non-custom "
                f"{occupying_ref}; cannot rename '{old_display}' ({source_ref})",
            )
            stats["warnings"] += 1
            return occupying_ref

    _put_behavior_name(client, process_id, source_ref, name, color)
    updated = {**source, "name": name}
    by_name[name] = updated
    by_name_ci[name.lower()] = updated
    by_ref[source_ref] = updated
    if old_display in by_name and old_display != name:
        del by_name[old_display]
        by_name_ci.pop(old_display.lower(), None)
    emit("backlog", f"Renamed behavior '{old_display}' → '{name}' ({source_ref})")
    return source_ref


def _configure_backlog_levels(
    client: AdoClient,
    ir: dict[str, Any],
    process_id: str,
    stats: dict[str, Any],
    emit: Emit,
) -> dict[str, str]:
    """Rename/create backlog behaviors from the Backlogs sheet (reference Script 4 Part 1)."""
    existing = _list_behaviors(client, process_id)
    by_name, by_name_ci, by_ref = _behavior_indexes(existing)

    emit(
        "backlog",
        f"Configuring {len(ir['process'].get('backlogs') or [])} backlog levels; "
        f"existing behaviors: {[b.get('name') for b in existing]}",
    )

    backlog_to_ref: dict[str, str] = {}

    for backlog in ir["process"].get("backlogs") or []:
        name = str(backlog.get("name") or "").strip()
        if not name:
            continue
        backlog_type = str(backlog.get("type") or "").strip()
        color = str(backlog.get("color") or "").strip().lstrip("#") or None
        rename_from = str(backlog.get("rename_from") or "").strip() or None

        try:
            # Explicit rename: Epic → Levels, Feature → Lowest (heal duplicates too).
            if rename_from and rename_from not in {"(new)", "(rename)"}:
                source, old_display = _find_rename_source(
                    rename_from, by_name, by_name_ci, by_ref
                )
                # Prefer known Agile ref even when a custom "Levels" already exists.
                known_ref = KNOWN_BEHAVIOR_REFS.get(rename_from or "")
                if known_ref and known_ref in by_ref:
                    source = by_ref[known_ref]
                    old_display = str(source.get("name") or old_display)
                if source:
                    ref = _claim_target_name_for_source(
                        client,
                        process_id,
                        name=name,
                        color=color,
                        source=source,
                        old_display=old_display,
                        by_name=by_name,
                        by_name_ci=by_name_ci,
                        by_ref=by_ref,
                        emit=emit,
                        stats=stats,
                    )
                    if ref:
                        backlog_to_ref[name] = ref
                        stats["behaviors"] += 1
                    continue
                # No source — fall through only if target already exists.
                if name in by_name or name.lower() in by_name_ci:
                    occupying = by_name.get(name) or by_name_ci[name.lower()]
                    ref = str(occupying.get("referenceName") or "").strip()
                    if ref:
                        backlog_to_ref[name] = ref
                        stats["behaviors"] += 1
                        emit(
                            "backlog",
                            f"Behavior '{name}' already exists (ref: {ref}); "
                            f"rename source '{rename_from}' not found",
                        )
                    continue
                emit(
                    "backlog",
                    f"WARNING: Could not find behavior '{old_display}'/'{rename_from}' "
                    f"to rename to '{name}'; trying create",
                )
                stats["warnings"] += 1

            # Type-based rename: Stories → Deliverables, Tasks → Tasks
            if rename_from == "(rename)":
                target_ref = TYPE_RENAME_REFS.get(backlog_type.lower())
                source = by_ref.get(target_ref or "")
                if target_ref and source:
                    current_name = str(source.get("name") or "").strip()
                    ref = _claim_target_name_for_source(
                        client,
                        process_id,
                        name=name,
                        color=color,
                        source=source,
                        old_display=current_name,
                        by_name=by_name,
                        by_name_ci=by_name_ci,
                        by_ref=by_ref,
                        emit=emit,
                        stats=stats,
                    )
                    if ref:
                        backlog_to_ref[name] = ref
                        stats["behaviors"] += 1
                    continue
                if name in by_name or name.lower() in by_name_ci:
                    occupying = by_name.get(name) or by_name_ci[name.lower()]
                    ref = str(occupying.get("referenceName") or "").strip()
                    if ref:
                        backlog_to_ref[name] = ref
                        stats["behaviors"] += 1
                    continue
                emit(
                    "backlog",
                    f"WARNING: Could not find behavior for type '{backlog_type}' "
                    f"to rename to '{name}'",
                )
                stats["warnings"] += 1
                continue

            # Idempotent for (new) / create path when name already present.
            if name in by_name or name.lower() in by_name_ci:
                occupying = by_name.get(name) or by_name_ci[name.lower()]
                ref = str(occupying.get("referenceName") or "").strip()
                if ref:
                    backlog_to_ref[name] = ref
                    stats["behaviors"] += 1
                    emit("backlog", f"Behavior '{name}' already exists (ref: {ref})")
                continue

            # Create new portfolio level: Highest, Kanban
            if rename_from in {None, "", "(new)"}:
                payload = {
                    "name": name,
                    "inherits": PORTFOLIO_PARENT_BEHAVIOR,
                }
                if color:
                    payload["color"] = color
                created = client.post(
                    f"/_apis/work/processes/{process_id}/behaviors",
                    json_body=payload,
                    api_version=BEHAVIOR_API,
                )
                new_ref = str((created or {}).get("referenceName") or "").strip()
                if new_ref:
                    backlog_to_ref[name] = new_ref
                    by_name[name] = created or {"name": name, "referenceName": new_ref}
                    by_name_ci[name.lower()] = by_name[name]
                    by_ref[new_ref] = by_name[name]
                    stats["behaviors"] += 1
                    emit("backlog", f"Created backlog behavior '{name}' ({new_ref})")
                else:
                    # 204/empty — refresh
                    for item in _list_behaviors(client, process_id):
                        if str(item.get("name") or "").strip() == name:
                            ref = str(item.get("referenceName") or "").strip()
                            if ref:
                                backlog_to_ref[name] = ref
                                stats["behaviors"] += 1
                            break
        except AdoError as exc:
            if exc.status == 409:
                for item in _list_behaviors(client, process_id):
                    if str(item.get("name") or "").strip().lower() == name.lower():
                        ref = str(item.get("referenceName") or "").strip()
                        if ref:
                            backlog_to_ref[name] = ref
                            stats["behaviors"] += 1
                        break
            else:
                emit("backlog", f"Backlog level '{name}': {exc}")
                stats["warnings"] += 1

    emit("backlog", f"Backlog level refs: {backlog_to_ref}")
    return backlog_to_ref


def _wit_name_index(client: AdoClient, process_id: str) -> dict[str, str]:
    """Map WIT display name (and lowercase) → process referenceName."""
    result: dict[str, str] = {}
    for wit in client.list_process_wits(process_id):
        name = str(wit.get("name") or "").strip()
        ref = str(wit.get("referenceName") or "").strip()
        if not name or not ref:
            continue
        result[name] = ref
        result[name.lower()] = ref
    return result


def _list_wit_behaviors(
    client: AdoClient, process_id: str, wit_ref: str
) -> list[dict[str, Any]]:
    data = client.get(
        f"/_apis/work/processes/{process_id}/workitemtypesbehaviors/"
        f"{quote(wit_ref, safe='')}/behaviors",
        api_version=WIT_BEHAVIOR_API,
    ) or {}
    return list(data.get("value") or [])


def _assign_wits_to_backlogs(
    client: AdoClient,
    ir: dict[str, Any],
    process_id: str,
    backlog_to_ref: dict[str, str],
    stats: dict[str, Any],
    emit: Emit,
) -> None:
    """Assign each enabled WIT to its Backlog name behavior (reference Script 4 Part 2)."""
    wit_refs = _wit_name_index(client, process_id)
    emit("backlog", f"Assigning WITs to backlog levels ({len(wit_refs) // 2} types in process)")

    for wit in ir["process"].get("work_item_types") or []:
        wit_name = str(wit.get("name") or "").strip()
        backlog_name = str(wit.get("backlog_name") or "").strip()
        if not wit_name:
            continue
        if not backlog_name or backlog_name.lower() == "no associated backlog":
            continue
        if wit.get("disabled"):
            emit("backlog", f"Skipping '{wit_name}' — disabled WIT")
            continue

        behavior_ref = backlog_to_ref.get(backlog_name)
        if not behavior_ref:
            emit(
                "backlog",
                f"WARNING: No behavior for backlog '{backlog_name}' (WIT: {wit_name})",
            )
            stats["warnings"] += 1
            continue

        wit_ref = wit_refs.get(wit_name) or wit_refs.get(wit_name.lower())
        if not wit_ref:
            emit("backlog", f"WARNING: WIT '{wit_name}' not found in process")
            stats["warnings"] += 1
            continue

        try:
            current = _list_wit_behaviors(client, process_id, wit_ref)
            if any(
                str((cb.get("behavior") or {}).get("id") or "") == behavior_ref
                for cb in current
            ):
                continue

            for cb in current:
                old_ref = str((cb.get("behavior") or {}).get("id") or "").strip()
                if not old_ref:
                    continue
                try:
                    client.delete(
                        f"/_apis/work/processes/{process_id}/workitemtypesbehaviors/"
                        f"{quote(wit_ref, safe='')}/behaviors/{quote(old_ref, safe='')}",
                        api_version=WIT_BEHAVIOR_API,
                    )
                except AdoError as exc:
                    emit(
                        "backlog",
                        f"WARNING: Could not remove behavior '{old_ref}' "
                        f"from '{wit_name}': {exc}",
                    )
                    stats["warnings"] += 1

            client.post(
                f"/_apis/work/processes/{process_id}/workitemtypesbehaviors/"
                f"{quote(wit_ref, safe='')}/behaviors",
                json_body={"behavior": {"id": behavior_ref}, "isDefault": False},
                api_version=WIT_BEHAVIOR_API,
            )
            stats["wit_assignments"] += 1
            emit("backlog", f"Assigned '{wit_name}' → '{backlog_name}'")
        except AdoError as exc:
            if exc.status == 409:
                continue
            emit("backlog", f"ERROR assigning '{wit_name}' → '{backlog_name}': {exc}")
            stats["warnings"] += 1


def _set_default_wits(
    client: AdoClient,
    ir: dict[str, Any],
    process_id: str,
    backlog_to_ref: dict[str, str],
    stats: dict[str, Any],
    emit: Emit,
) -> None:
    """Set Default work item type per Backlogs sheet row (reference set_default_wits)."""
    wit_refs = _wit_name_index(client, process_id)

    for backlog in ir["process"].get("backlogs") or []:
        backlog_name = str(backlog.get("name") or "").strip()
        default_wit_name = str(backlog.get("default_wit") or "").strip()
        behavior_ref = backlog_to_ref.get(backlog_name)
        if not backlog_name or not default_wit_name or not behavior_ref:
            continue

        default_wit_ref = wit_refs.get(default_wit_name) or wit_refs.get(
            default_wit_name.lower()
        )
        if not default_wit_ref:
            emit(
                "backlog",
                f"WARNING: Default WIT '{default_wit_name}' for '{backlog_name}' "
                "not found in process",
            )
            stats["warnings"] += 1
            continue

        try:
            current = _list_wit_behaviors(client, process_id, default_wit_ref)
            if any(
                str((cb.get("behavior") or {}).get("id") or "") == behavior_ref
                and bool(cb.get("isDefault"))
                for cb in current
            ):
                continue

            for cb in current:
                if str((cb.get("behavior") or {}).get("id") or "") == behavior_ref:
                    client.delete(
                        f"/_apis/work/processes/{process_id}/workitemtypesbehaviors/"
                        f"{quote(default_wit_ref, safe='')}/behaviors/"
                        f"{quote(behavior_ref, safe='')}",
                        api_version=WIT_BEHAVIOR_API,
                    )
                    break

            client.post(
                f"/_apis/work/processes/{process_id}/workitemtypesbehaviors/"
                f"{quote(default_wit_ref, safe='')}/behaviors",
                json_body={"behavior": {"id": behavior_ref}, "isDefault": True},
                api_version=WIT_BEHAVIOR_API,
            )
            stats["default_wits"] += 1
            emit(
                "backlog",
                f"Set '{default_wit_name}' as default for '{backlog_name}'",
            )
        except AdoError as exc:
            emit(
                "backlog",
                f"ERROR setting default '{default_wit_name}' for '{backlog_name}': {exc}",
            )
            stats["warnings"] += 1


def _create_iteration_nodes(
    client: AdoClient,
    ir: dict[str, Any],
    project: str,
    stats: dict[str, Any],
    emit: Emit,
) -> None:
    for iteration in ir["project"]["iteration_paths"]:
        path = iteration["path"]
        parts = [p for p in path.split("\\") if p]
        while parts and parts[0].lower() in {project.lower(), "project name"}:
            parts = parts[1:]
        parent: list[str] = []
        for name in parts:
            current = parent + [name]
            if not _iteration_exists(client, project, current):
                try:
                    _create_iteration(client, project, parent, name)
                    stats["iterations"] += 1
                except AdoError as exc:
                    if exc.status != 409:
                        emit("backlog", f"Iteration {'/'.join(current)}: {exc}")
                        stats["warnings"] += 1
            parent = current


def _fetch_iteration_tree(
    client: AdoClient,
    project: str,
    emit: Emit,
) -> dict[str, Any] | None:
    """Load the project iteration classification tree (needs $depth for children + GUIDs)."""
    # Try literal $depth first (reference scripts), then percent-encoded — some stacks mangle `$`.
    candidates = (
        "/_apis/wit/classificationnodes/Iterations?$depth=10",
        "/_apis/wit/classificationnodes/Iterations?%24depth=10",
        "/_apis/wit/classificationNodes/Iterations?$depth=10",
    )
    last_error: AdoError | None = None
    for path in candidates:
        try:
            tree = client.get(path, project=project, api_version="7.1")
            if isinstance(tree, dict) and (tree.get("identifier") or tree.get("name")):
                return tree
        except AdoError as exc:
            last_error = exc
            continue
    if last_error:
        emit("backlog", f"Could not fetch iteration tree: {last_error}")
    return None


def _index_iteration_tree(
    tree: dict[str, Any],
    project: str,
) -> tuple[str | None, dict[str, str], list[dict[str, str]]]:
    """Return (root_guid, lookup_map, non_root_nodes).

    Root GUID always comes from the tree root ``identifier`` (not a name lookup),
    so a project rename / casing mismatch cannot blank Backlog iteration.
    """
    iteration_map: dict[str, str] = {}
    _collect_iteration_ids(tree, "", iteration_map)

    root_id = str(tree.get("identifier") or "").strip() or None
    if not root_id:
        # Fallbacks if the payload omits identifier on the root object.
        root_id = (
            iteration_map.get(project)
            or iteration_map.get(str(tree.get("name") or "").strip())
            or None
        )

    # Unique non-root GUIDs for team iteration membership (never the project root —
    # TF400494: cannot create a team iteration for the top-level node).
    seen: set[str] = set()
    child_ids: list[dict[str, str]] = []
    _walk_children_for_ids(tree, str(tree.get("name") or project), seen, child_ids)
    return root_id, iteration_map, child_ids


def _walk_children_for_ids(
    node: dict[str, Any],
    parent_path: str,
    seen: set[str],
    out: list[dict[str, str]],
) -> None:
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        name = str(child.get("name") or "").strip()
        guid = str(child.get("identifier") or "").strip()
        path = f"{parent_path}\\{name}" if parent_path and name else name
        if guid and guid not in seen:
            seen.add(guid)
            out.append({"id": guid, "path": path})
        _walk_children_for_ids(child, path, seen, out)


def _collect_iteration_ids(node: dict[str, Any], parent_path: str, result: dict[str, str]) -> None:
    name = str(node.get("name") or "").strip()
    if not name:
        return
    current_path = f"{parent_path}\\{name}" if parent_path else name
    identifier = node.get("identifier")
    if identifier:
        guid = str(identifier)
        result[current_path] = guid
        result[current_path.replace("\\", "/")] = guid
        result[name] = guid
    for child in node.get("children") or []:
        if isinstance(child, dict):
            _collect_iteration_ids(child, current_path, result)


def _configure_team_iterations(
    client: AdoClient,
    ir: dict[str, Any],
    project: str,
    *,
    root_id: str,
    iteration_map: dict[str, str],
    child_ids: list[dict[str, str]],
    stats: dict[str, Any],
    emit: Emit,
    workers: int = 1,
) -> None:
    teams = [team for team in ir["project"]["teams"] if (team.get("name") or "").strip()]
    if not teams:
        emit("backlog", "No teams in IR; skipping team iteration assignment")
        return

    # Set when a team raises (e.g. the run was cancelled from emit), so queued teams don't start.
    stop = threading.Event()

    def configure(team: dict[str, Any]) -> dict[str, int]:
        if stop.is_set():
            return {}
        try:
            return _configure_one_team(
                client,
                team,
                project,
                root_id=root_id,
                iteration_map=iteration_map,
                child_ids=child_ids,
                emit=emit,
            )
        except BaseException:
            stop.set()
            raise

    pool_size = max(1, min(workers, len(teams)))
    if pool_size == 1:
        results = [configure(team) for team in teams]
    else:
        with ThreadPoolExecutor(max_workers=pool_size) as pool:
            results = list(pool.map(configure, teams))
    for team_stats in results:
        for key, value in team_stats.items():
            stats[key] += value


def _configure_one_team(
    client: AdoClient,
    team: dict[str, Any],
    project: str,
    *,
    root_id: str,
    iteration_map: dict[str, str],
    child_ids: list[dict[str, str]],
    emit: Emit,
) -> dict[str, int]:
    """One team's settings, iterations and include-children; returns that team's counts."""
    stats = {"team_settings": 0, "team_iterations": 0, "warnings": 0}
    team_name = (team.get("name") or "").strip()
    team_project = f"{project}/{team_name}"
    try:
        settings = client.get(
            "/_apis/work/teamsettings",
            project=team_project,
            api_version="7.1",
        )
    except AdoError as exc:
        emit("backlog", f"Team settings GET '{team_name}': {exc}")
        stats["warnings"] += 1
        return stats

    payload = _team_settings_payload(team, settings or {}, root_id, iteration_map)
    backlog_ok = _current_backlog_id(settings or {}) == root_id
    if payload:
        try:
            client.patch(
                "/_apis/work/teamsettings",
                project=team_project,
                json_body=payload,
                api_version="7.1",
            )
            stats["team_settings"] += 1
            backlog_ok = True
            emit(
                "backlog",
                f"Updated team settings for '{team_name}': {sorted(payload.keys())} "
                f"(backlogIteration={payload.get('backlogIteration', root_id)})",
            )
        except AdoError as exc:
            emit("backlog", f"FAILED team settings PATCH '{team_name}': {exc}")
            stats["warnings"] += 1
            backlog_ok = False
    else:
        stats["team_settings"] += 1

    if not backlog_ok:
        emit(
            "backlog",
            f"Skipping iteration selection for '{team_name}' — backlog iteration "
            "not set (ADO requires Backlog iteration before Select iteration(s)).",
        )
        stats["warnings"] += 1
        return stats

    added = _add_iterations_to_team(client, team_project, team_name, child_ids, emit, stats)
    stats["team_iterations"] += added
    if added:
        emit("backlog", f"Added {added} iterations to team '{team_name}'")
    else:
        emit("backlog", f"Team '{team_name}' already has all {len(child_ids)} iterations")

    if _truthy(team.get("include_sub_areas")):
        try:
            _enable_include_children(client, team_project, team_name, emit)
        except AdoError as exc:
            emit("backlog", f"Include-children update '{team_name}': {exc}")
            stats["warnings"] += 1
    return stats


def _current_backlog_id(settings: dict[str, Any]) -> str:
    backlog = settings.get("backlogIteration")
    if isinstance(backlog, dict):
        return str(backlog.get("id") or "").strip()
    return str(backlog or "").strip()


def _is_unset_iteration_id(value: str) -> bool:
    return (not value) or value in {
        "00000000-0000-0000-0000-000000000000",
        "null",
    }


def _team_settings_payload(
    team: dict[str, Any],
    current: dict[str, Any],
    root_iteration_id: str | None,
    iteration_map: dict[str, str],
) -> dict[str, Any]:
    """Build PATCH body. Never set defaultIterationMacro without backlogIteration."""
    payload: dict[str, Any] = {}
    if not root_iteration_id:
        return payload

    bug_behavior = (team.get("bug_behavior") or "asRequirements").strip()
    if bug_behavior and current.get("bugsBehavior") != bug_behavior:
        payload["bugsBehavior"] = bug_behavior

    backlog_iteration_value = (team.get("backlog_iteration") or "@currentIteration").strip()
    target_backlog_id = root_iteration_id
    if backlog_iteration_value.lower() != "@currentiteration":
        target_backlog_id = (
            iteration_map.get(backlog_iteration_value)
            or iteration_map.get(backlog_iteration_value.replace("/", "\\"))
            or root_iteration_id
        )

    current_backlog = _current_backlog_id(current)
    if _is_unset_iteration_id(current_backlog) or current_backlog != target_backlog_id:
        # REST TeamSettingsPatch.backlogIteration is the GUID string (not an object).
        payload["backlogIteration"] = target_backlog_id

    # Only set the macro together with (or after) a real backlog iteration target.
    if backlog_iteration_value.lower() == "@currentiteration":
        if current.get("defaultIterationMacro") != "@CurrentIteration":
            payload["defaultIterationMacro"] = "@CurrentIteration"

    return payload


def _add_iterations_to_team(
    client: AdoClient,
    team_project: str,
    team_name: str,
    all_iteration_ids: list[dict[str, str]],
    emit: Emit,
    stats: dict[str, Any],
) -> int:
    try:
        existing = client.get(
            "/_apis/work/teamsettings/iterations",
            project=team_project,
            api_version="7.1",
        ) or {}
    except AdoError as exc:
        emit("backlog", f"Team iterations GET '{team_name}': {exc}")
        stats["warnings"] += 1
        return 0

    current_ids = {str(item.get("id") or "") for item in existing.get("value") or []}
    added = 0
    for info in all_iteration_ids:
        guid = info["id"]
        if guid in current_ids:
            continue
        try:
            client.post(
                "/_apis/work/teamsettings/iterations",
                project=team_project,
                json_body={"id": guid},
                api_version="7.1",
            )
            added += 1
            current_ids.add(guid)
        except AdoError as exc:
            if exc.status in {409}:
                continue
            emit(
                "backlog",
                f"Could not add iteration '{info['path']}' to '{team_name}': {exc}",
            )
            stats["warnings"] += 1
    return added


def _enable_include_children(
    client: AdoClient,
    team_project: str,
    team_name: str,
    emit: Emit,
) -> None:
    """When Include sub areas = Yes, set includeChildren on team area values."""
    current = client.get(
        "/_apis/work/teamsettings/teamfieldvalues",
        project=team_project,
        api_version="7.1",
    ) or {}
    values = current.get("values") or []
    if not values:
        return
    needs_update = False
    updated = []
    for row in values:
        include = bool(row.get("includeChildren"))
        if not include:
            needs_update = True
        updated.append({"value": row.get("value"), "includeChildren": True})
    if not needs_update:
        return
    client.patch(
        "/_apis/work/teamsettings/teamfieldvalues",
        project=team_project,
        json_body={
            "defaultValue": current.get("defaultValue"),
            "values": updated,
        },
        api_version="7.1",
    )
    emit("backlog", f"Enabled includeChildren on area paths for '{team_name}'")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"yes", "true", "1", "y"}


def _iteration_exists(client: AdoClient, project: str, parts: list[str]) -> bool:
    path = "/".join(quote(p, safe="") for p in parts)
    try:
        client.get(
            f"/_apis/wit/classificationnodes/Iterations/{path}",
            project=project,
            api_version="7.1",
        )
        return True
    except AdoError as exc:
        if exc.status == 404:
            return False
        raise


def _create_iteration(client: AdoClient, project: str, parent_parts: list[str], name: str) -> None:
    if parent_parts:
        parent = "/".join(quote(p, safe="") for p in parent_parts)
        path = f"/_apis/wit/classificationnodes/Iterations/{parent}"
    else:
        path = "/_apis/wit/classificationnodes/Iterations"
    client.post(path, project=project, json_body={"name": name}, api_version="7.1")
