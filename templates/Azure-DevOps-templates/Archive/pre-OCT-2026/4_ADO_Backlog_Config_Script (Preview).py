"""
Script 4: ADO Backlog Configuration (Private Preview)

Configures backlog levels, WIT-to-backlog mappings, iteration paths,
and team settings for the Microsoft Business Process Catalog ADO template.

Run AFTER Script 1 (creation), Script 2 (page layout), and Script 3 (teams/areas).

Reads from these Excel sheets:
  - "Backlogs"          → Backlog level definitions (name, type, color, default WIT, rename from)
  - "Work item types"   → WIT-to-backlog mapping (Backlog name column)
  - "Iteration paths"   → Hierarchical iteration path definitions
  - "Teams"             → Team settings (bug behavior, include sub areas, backlog iteration)
  - "Area paths"        → Area path team assignments (for include sub areas update)
"""

import os
import sys
import base64
import json
import time
import urllib.parse
from collections import defaultdict
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth

# === USER CONFIGURATION ===
ADO_ORG_URL = "https://dev.azure.com/<YOUR_ORGANIZATION>"       # e.g. "https://dev.azure.com/Contoso"
ADO_PROJECT = "<YOUR_PROJECT_NAME>"                              # e.g. "Business process catalog"
PROCESS_NAME = "<YOUR_PROCESS_NAME>"                             # e.g. "Business process catalog"
PAT = "<YOUR_PERSONAL_ACCESS_TOKEN>"                             # Azure DevOps PAT with full access
EXCEL_FILE = "ADO template guideline (Preview).xlsx"     # Path to the Excel template file
LOG_FILE = "4_ADO_Backlog_Config_Log.txt"

# === AUTHENTICATION SETUP ===
authorization = str.encode(':' + PAT)
b64_auth = base64.b64encode(authorization).decode()
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Basic {b64_auth}"
}

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def log(msg: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)


def resolve_excel_path() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return EXCEL_FILE if os.path.isabs(EXCEL_FILE) else os.path.join(base_dir, EXCEL_FILE)


def make_request_with_retry(method: str, url: str, max_retries: int = 3, **kwargs):
    """Make an HTTP request with retry logic for transient errors (429, 503)."""
    for attempt in range(max_retries):
        resp = requests.request(method, url, **kwargs)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            log(f"  Rate limited (429). Retrying in {retry_after}s... (Attempt {attempt+1}/{max_retries})")
            time.sleep(retry_after)
            continue
        if resp.status_code == 503:
            wait = 2 ** attempt
            log(f"  Service unavailable (503). Retrying in {wait}s... (Attempt {attempt+1}/{max_retries})")
            time.sleep(wait)
            continue
        return resp
    return resp


def get_process_id() -> str:
    """Retrieve the process ID by name."""
    url = f"{ADO_ORG_URL}/_apis/work/processes?api-version=7.1-preview.2"
    resp = make_request_with_retry("GET", url, headers=HEADERS)
    if resp.status_code != 200:
        log(f"ERROR: Failed to list processes: {resp.status_code} - {resp.text}")
        sys.exit(1)
    for proc in resp.json().get("value", []):
        if proc["name"] == PROCESS_NAME:
            return proc["typeId"]
    log(f"ERROR: Process '{PROCESS_NAME}' not found.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Part 1: Configure Backlog Levels (Behaviors)
# ---------------------------------------------------------------------------

# Map from spreadsheet "Backlog type" to the parent behavior ref name for new portfolio backlogs
PORTFOLIO_PARENT_BEHAVIOR = "System.PortfolioBacklogBehavior"

# Map from spreadsheet "Rename from" values to known behavior display names and ref names
KNOWN_BEHAVIOR_RENAMES = {
    "Epic": "Epics",       # ADO default name is "Epics" (plural)
    "Feature": "Features", # ADO default name is "Features" (plural)
}

# Known behavior reference names for fallback lookup when old name was already changed
KNOWN_BEHAVIOR_REFS = {
    "Epic": "Microsoft.VSTS.Agile.EpicBacklogBehavior",
    "Feature": "Microsoft.VSTS.Agile.FeatureBacklogBehavior",
}


def get_existing_behaviors(process_id: str) -> list[dict]:
    """Fetch all behaviors for the process."""
    url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/behaviors?api-version=7.1-preview.2"
    resp = make_request_with_retry("GET", url, headers=HEADERS)
    if resp.status_code != 200:
        log(f"ERROR: Failed to get behaviors: {resp.status_code} - {resp.text}")
        return []
    return resp.json().get("value", [])


def configure_backlog_levels(process_id: str, backlogs_df: pd.DataFrame) -> dict:
    """
    Configure backlog levels by renaming existing behaviors and creating new ones.
    Returns a dict mapping backlog_name -> behavior_refName for use in WIT assignment.
    """
    log("\n" + "=" * 60)
    log("PART 1: Configure Backlog Levels (Behaviors)")
    log("=" * 60)

    existing = get_existing_behaviors(process_id)
    behavior_by_name = {b["name"]: b for b in existing}
    behavior_by_ref = {b["referenceName"]: b for b in existing}

    log(f"Found {len(existing)} existing behaviors: {[b['name'] for b in existing]}")

    backlog_to_behavior_ref = {}  # backlog_name -> behavior referenceName

    for _, row in backlogs_df.iterrows():
        backlog_name = str(row["Backlog name"]).strip()
        backlog_type = str(row["Backlog type"]).strip()
        color = str(row["Color"]).strip().lstrip("#") if pd.notna(row["Color"]) else None
        rename_from = str(row["Rename from"]).strip() if pd.notna(row["Rename from"]) else None

        log(f"\nProcessing backlog level: '{backlog_name}' (type: {backlog_type}, rename_from: {rename_from})")

        # Check if a behavior with the target name already exists (idempotency)
        if backlog_name in behavior_by_name:
            ref = behavior_by_name[backlog_name]["referenceName"]
            log(f"  Behavior '{backlog_name}' already exists (ref: {ref}). Skipping.")
            backlog_to_behavior_ref[backlog_name] = ref
            continue

        # RENAME: Find the existing behavior by its old name and rename it
        if rename_from and rename_from not in ("(new)", "(rename)"):
            # Try exact match first, then the known plural form
            old_display = KNOWN_BEHAVIOR_RENAMES.get(rename_from, rename_from)
            source_behavior = behavior_by_name.get(old_display)
            if not source_behavior:
                # Try exact rename_from value
                source_behavior = behavior_by_name.get(rename_from)
            # Also try lookup by known referenceName (in case behavior was previously renamed)
            if not source_behavior:
                known_ref = KNOWN_BEHAVIOR_REFS.get(rename_from)
                if known_ref:
                    source_behavior = behavior_by_ref.get(known_ref)
                    if source_behavior:
                        old_display = source_behavior["name"]  # Use its current name for logging
            if source_behavior:
                ref = source_behavior["referenceName"]
                payload = {"name": backlog_name}
                if color:
                    payload["color"] = color.lstrip("#")
                url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/behaviors/{ref}?api-version=7.1-preview.2"
                resp = make_request_with_retry("PUT", url, headers=HEADERS, json=payload)
                if resp.status_code in [200, 204]:
                    log(f"  Renamed behavior '{old_display}' → '{backlog_name}' (ref: {ref})")
                    backlog_to_behavior_ref[backlog_name] = ref
                    # Update local cache
                    behavior_by_name[backlog_name] = source_behavior
                    behavior_by_name[backlog_name]["name"] = backlog_name
                    if old_display in behavior_by_name and old_display != backlog_name:
                        del behavior_by_name[old_display]
                else:
                    log(f"  ERROR renaming '{old_display}' → '{backlog_name}': {resp.status_code} - {resp.text}")
                continue
            else:
                log(f"  WARNING: Could not find behavior named '{old_display}' or '{rename_from}' to rename. Will try to create instead.")

        # RENAME by type: For "(rename)" entries, match by backlog type
        if rename_from == "(rename)":
            # Match by the backlog type category
            type_to_ref = {
                "Requirements backlog": "System.RequirementBacklogBehavior",
                "Iteration backlog": "System.TaskBacklogBehavior",
            }
            target_ref = type_to_ref.get(backlog_type)
            if target_ref and target_ref in behavior_by_ref:
                source_behavior = behavior_by_ref[target_ref]
                current_name = source_behavior["name"]
                if current_name == backlog_name:
                    log(f"  Behavior already named '{backlog_name}' (ref: {target_ref}). Skipping.")
                    backlog_to_behavior_ref[backlog_name] = target_ref
                    continue
                payload = {"name": backlog_name}
                if color:
                    payload["color"] = color.lstrip("#")
                url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/behaviors/{target_ref}?api-version=7.1-preview.2"
                resp = make_request_with_retry("PUT", url, headers=HEADERS, json=payload)
                if resp.status_code in [200, 204]:
                    log(f"  Renamed behavior '{current_name}' → '{backlog_name}' (ref: {target_ref})")
                    backlog_to_behavior_ref[backlog_name] = target_ref
                else:
                    log(f"  ERROR renaming '{current_name}' → '{backlog_name}': {resp.status_code} - {resp.text}")
                continue
            else:
                log(f"  WARNING: Could not find behavior for type '{backlog_type}' to rename.")

        # CREATE NEW: For "(new)" entries, create a new portfolio behavior
        if rename_from == "(new)" or rename_from is None:
            payload = {
                "name": backlog_name,
                "inherits": PORTFOLIO_PARENT_BEHAVIOR,
            }
            if color:
                payload["color"] = color.lstrip("#")
            url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/behaviors?api-version=7.1-preview.2"
            resp = make_request_with_retry("POST", url, headers=HEADERS, json=payload)
            if resp.status_code in [200, 201]:
                new_ref = resp.json().get("referenceName", "unknown")
                log(f"  Created new behavior '{backlog_name}' (ref: {new_ref})")
                backlog_to_behavior_ref[backlog_name] = new_ref
                # Update local cache
                behavior_by_name[backlog_name] = resp.json()
                behavior_by_ref[new_ref] = resp.json()
            elif resp.status_code == 409:
                log(f"  Behavior '{backlog_name}' already exists (409). Fetching ref name...")
                refreshed = get_existing_behaviors(process_id)
                for b in refreshed:
                    if b["name"] == backlog_name:
                        backlog_to_behavior_ref[backlog_name] = b["referenceName"]
                        break
            else:
                log(f"  ERROR creating behavior '{backlog_name}': {resp.status_code} - {resp.text}")
            continue

    log(f"\nBacklog level configuration complete. Mappings: {json.dumps(backlog_to_behavior_ref, indent=2)}")
    return backlog_to_behavior_ref


# ---------------------------------------------------------------------------
# Part 2: Assign WITs to Backlog Levels
# ---------------------------------------------------------------------------

def get_all_wit_refs(process_id: str) -> dict:
    """Fetch all WIT reference names from the process. Returns dict: short_name -> full_ref_name."""
    url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workitemtypes?api-version=7.1-preview.2"
    resp = make_request_with_retry("GET", url, headers=HEADERS)
    if resp.status_code != 200:
        log(f"ERROR: Failed to list WITs: {resp.status_code}")
        return {}
    result = {}
    for wit in resp.json().get("value", []):
        ref = wit["referenceName"]
        name = wit["name"]
        result[name] = ref
        # Also index by lowercase for case-insensitive matching
        result[name.lower()] = ref
    return result


def assign_wits_to_backlogs(process_id: str, wit_df: pd.DataFrame,
                             backlog_to_behavior_ref: dict):
    """Assign each WIT to its backlog level behavior based on the spreadsheet."""
    log("\n" + "=" * 60)
    log("PART 2: Assign Work Item Types to Backlog Levels")
    log("=" * 60)

    wit_refs = get_all_wit_refs(process_id)
    log(f"Found {len(wit_refs)} work item types in process.")

    # Build the default WIT lookup from Backlogs sheet (passed via backlog_to_behavior_ref context)
    # We need the backlogs_df for default WIT info — it's passed indirectly via the global scope
    
    assigned_count = 0
    skipped_count = 0
    error_count = 0

    for _, row in wit_df.iterrows():
        wit_name = str(row["Work item type"]).strip()
        backlog_name = str(row.get("Backlog name", "")).strip()
        custom_flag = str(row.get("Custom work item type", "")).strip().lower()

        # Skip WITs with no backlog or "No associated backlog"
        if not backlog_name or backlog_name == "No associated backlog" or pd.isna(row.get("Backlog name")):
            continue

        # Skip disabled WITs
        if custom_flag == "disabled":
            log(f"  Skipping '{wit_name}' — disabled WIT.")
            skipped_count += 1
            continue

        # Find the behavior ref for this backlog
        behavior_ref = backlog_to_behavior_ref.get(backlog_name)
        if not behavior_ref:
            log(f"  WARNING: No behavior found for backlog '{backlog_name}' (WIT: {wit_name}). Skipping.")
            skipped_count += 1
            continue

        # Find the WIT ref name (try exact, then case-insensitive)
        wit_ref = wit_refs.get(wit_name) or wit_refs.get(wit_name.lower())
        if not wit_ref:
            log(f"  WARNING: WIT '{wit_name}' not found in process. Skipping.")
            skipped_count += 1
            continue

        # Check current behavior assignment
        check_url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workitemtypesbehaviors/{wit_ref}/behaviors?api-version=7.1-preview.1"
        check_resp = make_request_with_retry("GET", check_url, headers=HEADERS)
        current_behaviors = []
        if check_resp.status_code == 200:
            current_behaviors = check_resp.json().get("value", [])

        already_assigned = False
        for cb in current_behaviors:
            if cb.get("behavior", {}).get("id") == behavior_ref:
                already_assigned = True
                break

        if already_assigned:
            log(f"  '{wit_name}' already assigned to '{backlog_name}'. Skipping.")
            skipped_count += 1
            continue

        # Remove existing behavior assignments before adding new one
        for cb in current_behaviors:
            old_ref = cb.get("behavior", {}).get("id")
            if old_ref:
                del_url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workitemtypesbehaviors/{wit_ref}/behaviors/{old_ref}?api-version=7.1-preview.1"
                del_resp = make_request_with_retry("DELETE", del_url, headers=HEADERS)
                if del_resp.status_code in [200, 204]:
                    log(f"  Removed old behavior '{old_ref}' from '{wit_name}'.")
                else:
                    log(f"  WARNING: Could not remove old behavior '{old_ref}' from '{wit_name}': {del_resp.status_code}")

        # Assign to new behavior
        payload = {
            "behavior": {"id": behavior_ref},
            "isDefault": False
        }
        add_url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workitemtypesbehaviors/{wit_ref}/behaviors?api-version=7.1-preview.1"
        resp = make_request_with_retry("POST", add_url, headers=HEADERS, json=payload)
        if resp.status_code in [200, 201]:
            log(f"  Assigned '{wit_name}' → '{backlog_name}' (behavior: {behavior_ref})")
            assigned_count += 1
        elif resp.status_code == 409:
            log(f"  '{wit_name}' already assigned (409). Skipping.")
            skipped_count += 1
        else:
            log(f"  ERROR assigning '{wit_name}' → '{backlog_name}': {resp.status_code} - {resp.text}")
            error_count += 1

    log(f"\nWIT assignment complete. Assigned: {assigned_count}, Skipped: {skipped_count}, Errors: {error_count}")

    # Now set default WITs for each backlog level
    log("\nSetting default work item types for backlog levels...")
    set_default_wits(process_id, backlog_to_behavior_ref, wit_refs)


def set_default_wits(process_id: str, backlog_to_behavior_ref: dict, wit_refs: dict):
    """Set the default WIT for each backlog level using the Backlogs sheet."""
    # Re-read the Backlogs sheet for default WIT info
    excel_path = resolve_excel_path()
    backlogs_df = pd.read_excel(excel_path, sheet_name="Backlogs")
    backlogs_df.columns = backlogs_df.columns.str.strip()

    for _, row in backlogs_df.iterrows():
        backlog_name = str(row["Backlog name"]).strip()
        default_wit_name = str(row["Default work item type"]).strip()
        behavior_ref = backlog_to_behavior_ref.get(backlog_name)

        if not behavior_ref:
            continue

        default_wit_ref = wit_refs.get(default_wit_name) or wit_refs.get(default_wit_name.lower())
        if not default_wit_ref:
            log(f"  WARNING: Default WIT '{default_wit_name}' for backlog '{backlog_name}' not found in process.")
            continue

        # Check if this WIT is already assigned and set isDefault
        check_url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workitemtypesbehaviors/{default_wit_ref}/behaviors?api-version=7.1-preview.1"
        check_resp = make_request_with_retry("GET", check_url, headers=HEADERS)
        if check_resp.status_code != 200:
            log(f"  WARNING: Could not check behaviors for '{default_wit_name}': {check_resp.status_code}")
            continue

        current = check_resp.json().get("value", [])
        already_default = False
        for cb in current:
            if cb.get("behavior", {}).get("id") == behavior_ref and cb.get("isDefault"):
                already_default = True
                break

        if already_default:
            log(f"  '{default_wit_name}' is already the default for '{backlog_name}'. Skipping.")
            continue

        # Remove and re-add with isDefault=True
        for cb in current:
            if cb.get("behavior", {}).get("id") == behavior_ref:
                del_url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workitemtypesbehaviors/{default_wit_ref}/behaviors/{behavior_ref}?api-version=7.1-preview.1"
                make_request_with_retry("DELETE", del_url, headers=HEADERS)
                break

        payload = {
            "behavior": {"id": behavior_ref},
            "isDefault": True
        }
        add_url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workitemtypesbehaviors/{default_wit_ref}/behaviors?api-version=7.1-preview.1"
        resp = make_request_with_retry("POST", add_url, headers=HEADERS, json=payload)
        if resp.status_code in [200, 201]:
            log(f"  Set '{default_wit_name}' as default for '{backlog_name}'")
        else:
            log(f"  ERROR setting default '{default_wit_name}' for '{backlog_name}': {resp.status_code} - {resp.text}")


# ---------------------------------------------------------------------------
# Part 3: Create Iteration Paths
# ---------------------------------------------------------------------------

def create_iteration_paths(iterations_df: pd.DataFrame) -> dict:
    """
    Create hierarchical iteration paths from the Iteration paths sheet.
    Returns a dict of iteration_path -> identifier (GUID) for team assignment.
    """
    log("\n" + "=" * 60)
    log("PART 3: Create Iteration Paths")
    log("=" * 60)

    encoded_project = urllib.parse.quote(ADO_PROJECT)
    base_url = f"{ADO_ORG_URL}/{encoded_project}/_apis/wit/classificationnodes/Iterations"

    # Parse hierarchical structure (same pattern as area paths in Script 3)
    levels = [c for c in iterations_df.columns if c.startswith("Level")]
    if not levels:
        log("WARNING: No 'Level' columns found in Iteration paths sheet. Skipping.")
        return {}

    log(f"Found {len(levels)} levels in Iteration paths sheet: {levels}")

    current_parents = {}  # level_index -> current parent name
    created_paths = []

    for _, row in iterations_df.iterrows():
        for i, level_col in enumerate(levels):
            val = row[level_col]
            if pd.isna(val):
                continue
            node_name = str(val).strip()
            if not node_name:
                continue

            # Build the path components
            path_parts = []
            for j in range(i):
                parent = current_parents.get(j)
                if parent:
                    path_parts.append(parent)
            path_parts.append(node_name)

            # Update current parent tracking
            current_parents[i] = node_name
            # Clear children levels
            for j in range(i + 1, len(levels)):
                current_parents.pop(j, None)

            # Create the iteration node
            parent_path = "/".join(path_parts[:-1])
            if parent_path:
                url = f"{base_url}/{urllib.parse.quote(parent_path, safe='/')}?api-version=7.1"
            else:
                url = f"{base_url}?api-version=7.1"

            payload = {"name": node_name}
            resp = make_request_with_retry("POST", url, headers=HEADERS, json=payload)
            full_path = "/".join(path_parts)

            if resp.status_code in [200, 201]:
                log(f"  Created iteration: {full_path}")
                created_paths.append(full_path)
            elif resp.status_code == 409:
                log(f"  Already exists: {full_path}")
                created_paths.append(full_path)
            else:
                log(f"  ERROR creating iteration '{full_path}': {resp.status_code} - {resp.text}")

    # Fetch all iteration nodes with GUIDs for team assignment
    log("\nFetching iteration node identifiers...")
    iteration_map = {}
    fetch_url = f"{base_url}?$depth=10&api-version=7.1"
    resp = make_request_with_retry("GET", fetch_url, headers=HEADERS)
    if resp.status_code == 200:
        _collect_iteration_ids(resp.json(), "", iteration_map)
        log(f"  Collected {len(iteration_map)} iteration node identifiers.")
    else:
        log(f"  WARNING: Could not fetch iteration tree: {resp.status_code}")

    log(f"\nIteration path creation complete. Created/verified: {len(created_paths)}")
    return iteration_map


def _collect_iteration_ids(node: dict, parent_path: str, result: dict):
    """Recursively collect iteration node paths and their identifiers."""
    name = node.get("name", "")
    current_path = f"{parent_path}/{name}" if parent_path else name
    identifier = node.get("identifier")
    if identifier:
        result[current_path] = identifier
        # Also store by name only for simple lookups
        result[name] = identifier
    for child in node.get("children", []):
        _collect_iteration_ids(child, current_path, result)


# ---------------------------------------------------------------------------
# Part 4: Configure Team Settings
# ---------------------------------------------------------------------------

def configure_team_settings(teams_df: pd.DataFrame, iteration_map: dict):
    """
    Configure team settings: bug behavior, backlog iteration, iterations, and include sub areas.
    """
    log("\n" + "=" * 60)
    log("PART 4: Configure Team Settings")
    log("=" * 60)

    encoded_project = urllib.parse.quote(ADO_PROJECT)

    # Get the root iteration identifier (project root)
    root_iteration_id = iteration_map.get(ADO_PROJECT)

    # Collect all iteration node IDs (non-root) for assigning all iterations to teams
    all_iteration_ids = []
    for path, guid in iteration_map.items():
        if path != ADO_PROJECT and guid != root_iteration_id:
            all_iteration_ids.append({"id": guid, "path": path})

    success_count = 0
    error_count = 0

    for _, row in teams_df.iterrows():
        team_name = str(row["Teams"]).strip()
        bug_behavior = str(row.get("Bug behavior", "asRequirements")).strip()
        include_sub_areas = str(row.get("Include sub areas", "Yes")).strip().lower() in ("yes", "true", "1")
        backlog_iteration_value = str(row.get("Backlog iteration", "@currentIteration")).strip()

        encoded_team = urllib.parse.quote(team_name)
        log(f"\nConfiguring team: '{team_name}'")

        # --- 4a: Update team settings (bug behavior, backlog iteration) ---
        settings_url = f"{ADO_ORG_URL}/{encoded_project}/{encoded_team}/_apis/work/teamsettings?api-version=7.1"

        # First GET current settings to check if team exists
        get_resp = make_request_with_retry("GET", settings_url, headers=HEADERS)
        if get_resp.status_code == 404:
            log(f"  Team '{team_name}' not found (404). Skipping.")
            error_count += 1
            continue
        elif get_resp.status_code != 200:
            log(f"  ERROR getting settings for '{team_name}': {get_resp.status_code} - {get_resp.text}")
            error_count += 1
            continue

        current_settings = get_resp.json()

        # Build PATCH payload for team settings
        settings_payload = {}

        # Bug behavior
        current_bug = current_settings.get("bugsBehavior", "")
        if current_bug != bug_behavior:
            settings_payload["bugsBehavior"] = bug_behavior

        # Backlog iteration — set to root iteration (all iterations visible)
        if backlog_iteration_value.lower() == "@currentiteration":
            # Use the root iteration node as the backlog iteration
            if root_iteration_id:
                current_backlog_iter = current_settings.get("backlogIteration", {}).get("id", "")
                if current_backlog_iter != root_iteration_id:
                    settings_payload["backlogIteration"] = root_iteration_id
            # Set default iteration macro
            current_macro = current_settings.get("defaultIterationMacro", "")
            if current_macro != "@CurrentIteration":
                settings_payload["defaultIterationMacro"] = "@CurrentIteration"
        else:
            # Use a specific iteration path
            iter_id = iteration_map.get(backlog_iteration_value)
            if iter_id:
                settings_payload["backlogIteration"] = iter_id

        if settings_payload:
            patch_resp = make_request_with_retry("PATCH", settings_url, headers=HEADERS, json=settings_payload)
            if patch_resp.status_code in [200, 204]:
                log(f"  Updated team settings: {list(settings_payload.keys())}")
            else:
                log(f"  ERROR updating settings: {patch_resp.status_code} - {patch_resp.text}")
                error_count += 1
        else:
            log(f"  Team settings already configured correctly.")

        # --- 4b: Add iterations to team ---
        iterations_url = f"{ADO_ORG_URL}/{encoded_project}/{encoded_team}/_apis/work/teamsettings/iterations?api-version=7.1"

        # Get current team iterations
        iter_resp = make_request_with_retry("GET", iterations_url, headers=HEADERS)
        current_iter_ids = set()
        if iter_resp.status_code == 200:
            for it in iter_resp.json().get("value", []):
                current_iter_ids.add(it.get("id", ""))

        added = 0
        for iter_info in all_iteration_ids:
            if iter_info["id"] in current_iter_ids:
                continue
            add_payload = {"id": iter_info["id"]}
            add_resp = make_request_with_retry("POST", iterations_url, headers=HEADERS, json=add_payload)
            if add_resp.status_code in [200, 201]:
                added += 1
            elif add_resp.status_code == 409:
                pass  # Already exists
            else:
                log(f"  WARNING: Could not add iteration '{iter_info['path']}' to team: {add_resp.status_code}")

        if added > 0:
            log(f"  Added {added} iterations to team.")
        else:
            log(f"  All iterations already assigned.")

        # --- 4c: Update area paths to include sub areas ---
        if include_sub_areas:
            _update_team_area_include_children(encoded_project, encoded_team, team_name)

        success_count += 1

    log(f"\nTeam settings configuration complete. Success: {success_count}, Errors: {error_count}")


def _update_team_area_include_children(encoded_project: str, encoded_team: str, team_name: str):
    """Update team area paths to include children."""
    areas_url = f"{ADO_ORG_URL}/{encoded_project}/{encoded_team}/_apis/work/teamsettings/teamfieldvalues?api-version=7.1"
    resp = make_request_with_retry("GET", areas_url, headers=HEADERS)
    if resp.status_code != 200:
        log(f"  WARNING: Could not get area settings for '{team_name}': {resp.status_code}")
        return

    current = resp.json()
    default_value = current.get("defaultValue", "")
    values = current.get("values", [])

    # Check if any area needs includeChildren updated
    needs_update = False
    updated_values = []
    for v in values:
        new_v = {"value": v["value"], "includeChildren": True}
        if not v.get("includeChildren", False):
            needs_update = True
        updated_values.append(new_v)

    if not needs_update:
        log(f"  Area paths already include children.")
        return

    patch_payload = {
        "defaultValue": default_value,
        "values": updated_values
    }
    patch_resp = make_request_with_retry("PATCH", areas_url, headers=HEADERS, json=patch_payload)
    if patch_resp.status_code in [200, 204]:
        log(f"  Updated area paths to include children.")
    else:
        log(f"  WARNING: Could not update area children: {patch_resp.status_code} - {patch_resp.text}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def main():
    # Reset log
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)

    start_time = time.time()
    log(f"ADO Backlog Configuration Script started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Organization: {ADO_ORG_URL}")
    log(f"Project: {ADO_PROJECT}")
    log(f"Process: {PROCESS_NAME}")

    excel_path = resolve_excel_path()
    if not os.path.exists(excel_path):
        log(f"ERROR: Excel file not found: {excel_path}")
        sys.exit(1)

    # Get process ID
    process_id = get_process_id()
    log(f"Process ID: {process_id}")

    # Read spreadsheet sheets
    try:
        backlogs_df = pd.read_excel(excel_path, sheet_name="Backlogs")
        backlogs_df.columns = backlogs_df.columns.str.strip()
        log(f"Read {len(backlogs_df)} rows from 'Backlogs' sheet.")
    except Exception as e:
        log(f"ERROR: Could not read 'Backlogs' sheet: {e}")
        sys.exit(1)

    try:
        wit_df = pd.read_excel(excel_path, sheet_name="Work item types")
        wit_df.columns = wit_df.columns.str.strip()
        log(f"Read {len(wit_df)} rows from 'Work item types' sheet.")
    except Exception as e:
        log(f"ERROR: Could not read 'Work item types' sheet: {e}")
        sys.exit(1)

    try:
        iterations_df = pd.read_excel(excel_path, sheet_name="Iteration paths")
        iterations_df.columns = iterations_df.columns.str.strip()
        log(f"Read {len(iterations_df)} rows from 'Iteration paths' sheet.")
    except Exception as e:
        log(f"WARNING: Could not read 'Iteration paths' sheet: {e}. Skipping iteration creation.")
        iterations_df = None

    try:
        teams_df = pd.read_excel(excel_path, sheet_name="Teams")
        teams_df.columns = teams_df.columns.str.strip()
        log(f"Read {len(teams_df)} rows from 'Teams' sheet.")
    except Exception as e:
        log(f"WARNING: Could not read 'Teams' sheet: {e}. Skipping team settings.")
        teams_df = None

    # Part 1: Configure backlog levels
    backlog_to_behavior_ref = configure_backlog_levels(process_id, backlogs_df)

    # Part 2: Assign WITs to backlog levels
    assign_wits_to_backlogs(process_id, wit_df, backlog_to_behavior_ref)

    # Part 3: Create iteration paths
    iteration_map = {}
    if iterations_df is not None and not iterations_df.empty:
        iteration_map = create_iteration_paths(iterations_df)
    else:
        log("\nSkipping iteration path creation (no data).")
        # Still fetch existing iterations for team settings
        encoded_project = urllib.parse.quote(ADO_PROJECT)
        fetch_url = f"{ADO_ORG_URL}/{encoded_project}/_apis/wit/classificationnodes/Iterations?$depth=10&api-version=7.1"
        resp = make_request_with_retry("GET", fetch_url, headers=HEADERS)
        if resp.status_code == 200:
            _collect_iteration_ids(resp.json(), "", iteration_map)

    # Part 4: Configure team settings
    if teams_df is not None and not teams_df.empty:
        configure_team_settings(teams_df, iteration_map)
    else:
        log("\nSkipping team settings configuration (no data).")

    # Summary
    elapsed = time.time() - start_time
    log("\n" + "=" * 60)
    log("SUMMARY")
    log("=" * 60)
    log(f"Elapsed time: {elapsed:.1f} seconds ({elapsed/60:.2f} minutes)")
    log(f"Script finished. See log file for details:")
    log(f"  {LOG_FILE}")
    log("=" * 60)


if __name__ == "__main__":
    main()
