import os
import sys
import base64
import urllib.parse
from collections import defaultdict
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth

# === CONFIGURATION ===
ADO_ORG_URL = "https://dev.azure.com/<YOUR_ORGANIZATION>"  # e.g. "https://dev.azure.com/Contoso"
ADO_PROJECT = "<YOUR_PROJECT_NAME>"                         # e.g. "Business process catalog"
PAT = "<YOUR_PERSONAL_ACCESS_TOKEN>"                        # Azure DevOps PAT with full access
EXCEL_FILE = "ADO template guideline (Preview).xlsx" # Path to the Excel template file
LOG_FILE = "3_ADO_Teams_Areas_Log.txt"
Sprints_TEAM_NAME = "Sprints"

HEADERS_JSON = {"Content-Type": "application/json"}

def log(msg: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)

def resolve_excel_path() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return EXCEL_FILE if os.path.isabs(EXCEL_FILE) else os.path.join(base_dir, EXCEL_FILE)

# ---------------------------------------------------------------------------
# Part 1: Create Teams (logic from Script 4)
# ---------------------------------------------------------------------------

def get_project_id() -> str:
    proj_url = f"{ADO_ORG_URL}/_apis/projects/{ADO_PROJECT}?api-version=7.1"
    resp = requests.get(proj_url, headers=HEADERS_JSON, auth=HTTPBasicAuth('', PAT))
    if resp.status_code != 200:
        log(f"ERROR: Could not fetch project ID for '{ADO_PROJECT}': {resp.status_code} - {resp.text}")
        sys.exit(1)
    project_id = resp.json().get("id")
    if not project_id:
        log(f"ERROR: Project ID not found in response for '{ADO_PROJECT}'")
        sys.exit(1)
    return project_id

def create_teams_from_excel(excel_path: str, project_id: str) -> list[str]:
    try:
        df = pd.read_excel(excel_path, sheet_name="Area paths")
    except Exception as e:
        log(f"ERROR: Unable to read 'Area paths' sheet for team extraction: {e}")
        sys.exit(1)

    df = df.iloc[:, 1:6]
    df.columns = ["L1", "L2", "L3", "L4", "Teams"]

    if "Teams" not in df.columns:
        log("ERROR: 'Teams' column not found in Area paths sheet")
        sys.exit(1)

    team_names = [str(x).strip() for x in df["Teams"].dropna().unique() if str(x).strip()]
    if Sprints_TEAM_NAME not in team_names:
        team_names.append(Sprints_TEAM_NAME)

    created_or_existing = []
    for team_name in team_names:
        log(f"Processing team: {team_name}")
        url = f"{ADO_ORG_URL}/_apis/projects/{project_id}/teams?api-version=7.1"
        payload = {"name": team_name}
        resp = requests.post(url, headers=HEADERS_JSON, auth=HTTPBasicAuth('', PAT), json=payload)
        if resp.status_code in [200, 201]:
            log(f"  ✔ Successfully created team '{team_name}'.")
            created_or_existing.append(team_name)
        elif resp.status_code == 409:
            log(f"  ✔ Team '{team_name}' already exists (409 conflict). Skipping create.")
            created_or_existing.append(team_name)
        else:
            log(f"  ✖ ERROR: Failed to create team '{team_name}': {resp.status_code} - {resp.text}")
    return created_or_existing

# ---------------------------------------------------------------------------
# Part 2: Create Area Paths and Assign Teams (logic from Script 5)
# ---------------------------------------------------------------------------

BASE_URL = f"https://dev.azure.com/{ADO_ORG_URL.split('/')[-1]}/{ADO_PROJECT}/_apis/wit/classificationnodes/Areas"
AUTH_HEADER = {
    "Authorization": "Basic " + base64.b64encode(f':{PAT}'.encode()).decode(),
    "Content-Type": "application/json",
}

def create_area(path_list: list[str]):
    parent = "/".join(path_list[:-1])
    new_node = path_list[-1]
    if parent == "":
        url = f"{BASE_URL}?api-version=7.1"
    else:
        url = f"{BASE_URL}/{parent}?api-version=7.1"
    body = {"name": new_node}
    r = requests.post(url, headers=AUTH_HEADER, json=body)
    if r.status_code in [200, 201]:
        log(f"  ✔ Created or exists: {parent}/{new_node}")
    elif r.status_code == 409:
        log(f"  ✔ Already exists: {parent}/{new_node}")
    else:
        log(f"  ✖ Error creating area '{parent}/{new_node}': {r.status_code} {r.text}")

def _format_area_path(relative_path: str) -> str:
    relative = relative_path.replace("/", "\\")
    return f"{ADO_PROJECT}\\{relative}" if relative else ADO_PROJECT

def _build_team_payload(default_path: str, all_paths: set[str]) -> dict:
    default_formatted = _format_area_path(default_path)
    values = [{"value": default_formatted, "includeChildren": False}]
    for path in sorted(all_paths):
        if path == default_path:
            continue
        values.append({"value": _format_area_path(path), "includeChildren": False})
    return {"defaultValue": default_formatted, "values": values}

def set_team_area(team_name: str, default_path: str, paths: set[str]) -> None:
    encoded_team = urllib.parse.quote(team_name)
    org = ADO_ORG_URL.split("/")[-1]
    url = f"https://dev.azure.com/{org}/{ADO_PROJECT}/{encoded_team}/_apis/work/teamsettings/teamfieldvalues?api-version=7.1"
    payload = _build_team_payload(default_path, paths)
    response = requests.patch(url, json=payload, headers={"Content-Type": "application/json"}, auth=HTTPBasicAuth("", PAT))
    if response.status_code in [200, 204]:
        log(f"  ✔ Assigned Team '{team_name}' → {payload['defaultValue']} with {len(payload['values'])} entries")
    else:
        log(f"  ✖ FAILED to assign team '{team_name}': {response.status_code} - {response.text}")

def create_areas_and_assign_teams_from_excel(excel_path: str, allowed_teams: set[str]):
    try:
        df = pd.read_excel(excel_path, sheet_name="Area paths")
    except Exception as e:
        log(f"ERROR: Unable to read 'Area paths' sheet: {e}")
        return

    # Expect columns B..F => L1, L2, L3, L4, Teams
    df = df.iloc[:, 1:6]
    df.columns = ["L1", "L2", "L3", "L4", "Teams"]

    current_L1 = None
    current_L2 = None
    current_L3 = None

    team_assignments: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"default": None, "paths": set()})

    def track_team(team_name: str | None, path_list: list[str], default_value: str | None = None):
        if not team_name or not path_list:
            return
        team_name = str(team_name).strip()
        if team_name == "":
            return
        if team_name not in allowed_teams and team_name != Sprints_TEAM_NAME:
            log(f"  • Skipping team assignment for unknown team '{team_name}'")
            return
        entry = team_assignments[team_name]
        if entry["default"] is None:
            entry["default"] = default_value if default_value else path_list[0]
        entry["paths"].add("/".join(path_list))

    # Create areas and gather team-area relations
    for _, row in df.iterrows():
        L1, L2, L3, L4 = row["L1"], row["L2"], row["L3"], row["L4"]
        team = row["Teams"] if pd.notna(row["Teams"]) else None

        if pd.notna(L1):
            current_L1 = str(L1).strip()
            path = [current_L1]
            create_area(path)
            track_team(team, path, current_L1)
            current_L2 = None
            current_L3 = None
            continue

        if pd.notna(L2) and current_L1:
            current_L2 = str(L2).strip()
            path = [current_L1, current_L2]
            create_area(path)
            track_team(team, path, current_L2)
            current_L3 = None
            continue

        if pd.notna(L3) and current_L2:
            current_L3 = str(L3).strip()
            path = [current_L1, current_L2, current_L3]
            create_area(path)
            track_team(team, path, current_L3)
            continue

        if pd.notna(L4) and current_L3:
            child_L4 = str(L4).strip()
            path = [current_L1, current_L2, current_L3, child_L4]
            create_area(path)
            track_team(team, path, child_L4)
            continue

    # Assign teams to area paths
    for team_name, data in team_assignments.items():
        default_path = data["default"]
        paths = data["paths"]
        if not default_path or not paths:
            continue
        if default_path not in paths:
            paths.add(default_path)
        set_team_area(team_name, default_path, paths)

    # Ensure Sprints team gets access to every area path
    if Sprints_TEAM_NAME in allowed_teams:
        all_paths = set()
        for entry in team_assignments.values():
            all_paths.update(entry["paths"])
        if all_paths:
            default_for_sprints = next(iter(sorted(all_paths)))
            set_team_area(Sprints_TEAM_NAME, default_for_sprints, all_paths)
        else:
            log("WARNING: No area paths collected; unable to assign Sprints team")

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def main():
    # Reset log
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)

    excel_path = resolve_excel_path()
    if not os.path.exists(excel_path):
        log(f"Error: Excel file not found: {excel_path}")
        sys.exit(1)

    # 1) Create Teams from Area Paths sheet
    project_id = get_project_id()
    teams = create_teams_from_excel(excel_path, project_id)
    allowed_teams = set(teams)

    # 2) Create Areas and Assign Teams
    create_areas_and_assign_teams_from_excel(excel_path, allowed_teams)

if __name__ == "__main__":
    main()
