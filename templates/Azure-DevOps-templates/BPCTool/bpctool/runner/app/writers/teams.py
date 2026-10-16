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

    # Create area nodes and collect per-team path sets (do not PATCH per row).
    team_assignments: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"default": None, "paths": set()}
    )

    for area in ir["project"]["area_paths"]:
        parts = _relative_area_parts(area.get("path") or "", project)
        if not parts:
            continue
        parent: list[str] = []
        for name in parts:
            current = parent + [name]
            if not _area_exists(client, project, current):
                try:
                    _create_area(client, project, parent, name)
                    stats["areas"] += 1
                except AdoError as exc:
                    if exc.status not in {409}:
                        emit("teams", f"Area {'/'.join(current)}: {exc}")
                        stats["warnings"] += 1
            parent = current

        team_name = (area.get("team") or "").strip()
        if not team_name:
            continue
        if team_name.lower() not in allowed:
            emit("teams", f"Skipping area assignment for unknown team '{team_name}'")
            stats["warnings"] += 1
            continue

        relative = "\\".join(parts)
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
            _assign_team_areas(client, project, team_name, default_path, paths)
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

    unassigned = [name for name in team_names if name not in team_assignments]
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
) -> None:
    """Reference set_team_area: default + full values list, includeChildren=false."""
    default_formatted = _format_area_path(project, default_relative)
    values = [{"value": default_formatted, "includeChildren": False}]
    for path in sorted(paths):
        formatted = _format_area_path(project, path)
        if formatted == default_formatted:
            continue
        values.append({"value": formatted, "includeChildren": False})
    client.patch(
        "/_apis/work/teamsettings/teamfieldvalues",
        project=f"{project}/{team_name}",
        json_body={"defaultValue": default_formatted, "values": values},
        api_version="7.1",
    )
