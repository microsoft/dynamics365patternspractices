"""Upsert teams and area paths (reference Script 3 semantics)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable
from urllib.parse import quote

from ..ado_client import AdoClient, AdoError

Emit = Callable[[str, str], None]


def apply_teams(
    client: AdoClient,
    ir: dict[str, Any],
    *,
    dry_run: bool,
    emit: Emit,
    root_area_path: str = "",
) -> dict[str, Any]:
    project = ir["targets"]["project_name"]
    stats = {"teams": 0, "areas": 0, "assignments": 0, "warnings": 0}
    root = (root_area_path or project).strip()

    if dry_run:
        planned_teams = int(ir["counts"].get("teams") or 0)
        planned_areas = int(ir["counts"].get("area_paths") or 0)
        planned_assignments = len(
            {
                (area.get("team") or "").strip()
                for area in ir["project"]["area_paths"]
                if (area.get("team") or "").strip()
            }
        )
        emit(
            "teams",
            f"[dry-run] Would upsert {planned_teams} teams and "
            f"{planned_areas} area paths under project root '{root}' "
            f"({planned_assignments} team area assignments). "
            "No Azure DevOps teamfieldvalues were changed.",
        )
        return {
            **stats,
            "teams": planned_teams,
            "areas": planned_areas,
            "assignments": planned_assignments,
            "dry_run": True,
        }

    project_id = client.get_project_id(project)
    if not project_id:
        raise AdoError(f'Project "{project}" not found for teams apply.')

    # Teams from Teams sheet + any team names referenced on Area paths.
    team_names: list[str] = []
    seen: set[str] = set()
    for team in ir["project"]["teams"]:
        name = (team.get("name") or "").strip()
        if name and name.lower() not in seen:
            team_names.append(name)
            seen.add(name.lower())
    for area in ir["project"]["area_paths"]:
        name = (area.get("team") or "").strip()
        if name and name.lower() not in seen:
            team_names.append(name)
            seen.add(name.lower())

    existing_teams: dict[str, Any] = {}
    try:
        data = client.get(f"/_apis/projects/{quote(project_id, safe='')}/teams", api_version="7.1") or {}
        for team in data.get("value") or []:
            existing_teams[str(team.get("name") or "").strip().lower()] = team
    except AdoError as exc:
        emit("teams", f"Could not list teams: {exc}")
        stats["warnings"] += 1

    for name in team_names:
        if name.lower() in existing_teams:
            stats["teams"] += 1
            continue
        try:
            created = client.post(
                f"/_apis/projects/{quote(project_id, safe='')}/teams",
                json_body={"name": name},
                api_version="7.1",
            )
            if created:
                existing_teams[name.lower()] = created
            stats["teams"] += 1
        except AdoError as exc:
            if exc.status == 409:
                stats["teams"] += 1
            else:
                emit("teams", f"Team '{name}': {exc}")
                stats["warnings"] += 1

    allowed = set(existing_teams.keys()) | seen
    canonical_team = {name.lower(): name for name in team_names}
    include_sub_areas = {
        (team.get("name") or "").strip().lower()
        for team in ir["project"]["teams"]
        if str(team.get("include_sub_areas") or "").strip().lower() in {"yes", "true", "1", "y"}
    }

    existing_areas = _read_area_tree(client, project)

    # A Root area path below the project (e.g. "Proj\Imported") holds the workbook's area tree.
    root_parts = _relative_area_parts(root, project)
    if root_parts:
        _ensure_area_chain(client, project, root_parts, stats, emit, existing_areas)

    # Create area nodes and collect per-team path sets (do not PATCH per row).
    team_assignments: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"default": None, "paths": set()}
    )

    for area in ir["project"]["area_paths"]:
        relative_parts = _relative_area_parts(area.get("path") or "", project)
        if not relative_parts:
            continue
        parts = root_parts + relative_parts
        _ensure_area_chain(client, project, parts, stats, emit, existing_areas)

        team_name = (area.get("team") or "").strip()
        if not team_name:
            continue
        if team_name.lower() not in allowed:
            emit("teams", f"Skipping area assignment for unknown team '{team_name}'")
            stats["warnings"] += 1
            continue

        relative = "\\".join(parts)
        # Azure DevOps team names ignore case: one entry (and one PATCH) per team.
        team_name = canonical_team.get(team_name.lower(), team_name)
        entry = team_assignments[team_name]
        # First row for a team becomes its default area (reference track_team).
        if entry["default"] is None:
            entry["default"] = relative
        entry["paths"].add(relative)

    # One teamsettings PATCH per team with the full path set.
    for team_name, data in sorted(team_assignments.items(), key=lambda item: item[0].lower()):
        default_path = data["default"]
        paths: set[str] = set(data["paths"])
        if not default_path or not paths:
            emit("teams", f"Team '{team_name}' has no area paths to assign")
            stats["warnings"] += 1
            continue
        paths.add(default_path)
        try:
            _assign_team_areas(
                client,
                project,
                team_name,
                default_path,
                paths,
                include_children=team_name.lower() in include_sub_areas,
            )
            stats["assignments"] += 1
            emit(
                "teams",
                f"Assigned team '{team_name}' → {project}\\{default_path} "
                f"({len(paths)} path{'s' if len(paths) != 1 else ''})",
            )
        except AdoError as exc:
            emit(
                "teams",
                f"FAILED assign {team_name} → {project}\\{default_path} "
                f"(+{max(0, len(paths) - 1)} more): {exc}",
            )
            stats["warnings"] += 1

    assigned = {name.lower() for name in team_assignments}
    unassigned = [name for name in team_names if name.lower() not in assigned]
    if unassigned:
        emit(
            "teams",
            "Teams with no Area paths row/Teams mapping: " + ", ".join(unassigned[:12])
            + ("…" if len(unassigned) > 12 else ""),
        )
        stats["warnings"] += 1

    emit(
        "teams",
        f"Teams/areas finished: {stats['teams']} teams, {stats['areas']} areas, "
        f"{stats['assignments']} team area assignments",
    )
    return stats


def _relative_area_parts(path: str, project: str) -> list[str]:
    parts = [p for p in path.split("\\") if p]
    if not parts:
        return []
    # Strip project root / Excel placeholder so nodes are created under the project.
    while parts and parts[0].lower() in {project.lower(), "project name"}:
        parts = parts[1:]
    return parts


def _read_area_tree(client: AdoClient, project: str) -> set[str] | None:
    """Every area path under the project (lowercase, relative), or None if unreadable."""
    try:
        root = client.get(
            "/_apis/wit/classificationnodes/Areas?$depth=14", project=project, api_version="7.1"
        ) or {}
    except AdoError:
        return None
    paths: set[str] = set()
    stack: list[tuple[dict[str, Any], str]] = [(child, "") for child in root.get("children") or []]
    while stack:
        node, parent = stack.pop()
        path = f"{parent}\\{node.get('name') or ''}" if parent else str(node.get("name") or "")
        paths.add(path.lower())
        stack.extend((child, path) for child in node.get("children") or [])
    return paths


def _ensure_area_chain(
    client: AdoClient,
    project: str,
    parts: list[str],
    stats: dict[str, Any],
    emit: Emit,
    existing: set[str] | None = None,
) -> None:
    """Create each missing node of ``parts``; ``existing`` (from the tree) avoids a GET per node."""
    parent: list[str] = []
    for name in parts:
        current = parent + [name]
        key = "\\".join(current).lower()
        if existing is not None:
            missing = key not in existing
        else:
            missing = not _area_exists(client, project, current)
        if missing:
            try:
                _create_area(client, project, parent, name)
                stats["areas"] += 1
            except AdoError as exc:
                if exc.status not in {409}:
                    emit("teams", f"Area {'/'.join(current)}: {exc}")
                    stats["warnings"] += 1
            if existing is not None:
                existing.add(key)
        parent = current


def _area_exists(client: AdoClient, project: str, parts: list[str]) -> bool:
    path = "/".join(quote(p, safe="") for p in parts)
    try:
        client.get(f"/_apis/wit/classificationnodes/Areas/{path}", project=project, api_version="7.1")
        return True
    except AdoError as exc:
        if exc.status == 404:
            return False
        raise


def _create_area(client: AdoClient, project: str, parent_parts: list[str], name: str) -> None:
    if parent_parts:
        parent = "/".join(quote(p, safe="") for p in parent_parts)
        path = f"/_apis/wit/classificationnodes/Areas/{parent}"
    else:
        path = "/_apis/wit/classificationnodes/Areas"
    client.post(path, project=project, json_body={"name": name}, api_version="7.1")


def _format_area_path(project: str, relative_path: str) -> str:
    relative = relative_path.replace("/", "\\").strip("\\")
    return f"{project}\\{relative}" if relative else project


def _assign_team_areas(
    client: AdoClient,
    project: str,
    team_name: str,
    default_relative: str,
    paths: set[str],
    *,
    include_children: bool = False,
) -> None:
    """Reference set_team_area: default + full values list.

    ``include_children`` comes from the Teams sheet's Include sub areas column; every
    PATCH replaces the whole list, so it must be sent here, not only by the Backlog step.
    """
    default_formatted = _format_area_path(project, default_relative)
    values = [{"value": default_formatted, "includeChildren": include_children}]
    for path in sorted(paths):
        formatted = _format_area_path(project, path)
        if formatted == default_formatted:
            continue
        values.append({"value": formatted, "includeChildren": include_children})
    client.patch(
        "/_apis/work/teamsettings/teamfieldvalues",
        project=f"{project}/{team_name}",
        json_body={"defaultValue": default_formatted, "values": values},
        api_version="7.1",
    )
