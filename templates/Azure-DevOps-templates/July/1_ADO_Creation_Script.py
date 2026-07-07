import pandas as pd
import requests
import base64
import json
import time
import urllib.parse
import datetime
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from ado_setup_config import load_config

# === USER CONFIGURATION ===
# Values can be provided through prompts, command-line arguments, or environment variables.
config = load_config(default_log_file="1_ADO_Creation_Script_Log.txt", require_process=True)
ADO_ORG_URL = config.ado_org_url
ADO_PROJECT = config.ado_project
PROCESS_NAME = config.process_name
PAT = config.pat
EXCEL_FILE = config.excel_file
LOG_FILE = config.log_file
if os.path.basename(LOG_FILE) == "1_ADO_Creation_Script_Log.txt":
    run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_FILE = os.path.join(os.path.dirname(LOG_FILE), f"1_ADO_Creation_Script_Log_{run_id}.txt")
MAX_WORKERS = int(os.getenv("BPC_ADO_MAX_WORKERS", "8"))
ALLOW_CUSTOM_WIT_INHERITANCE = os.getenv("BPC_ADO_ALLOW_CUSTOM_WIT_INHERITANCE", "false").strip().lower() in ("1", "true", "yes")
log_lock = threading.Lock()

# === AUTHENTICATION SETUP ===
# Prepare HTTP headers for Azure DevOps REST API calls.
authorization = str.encode(':' + PAT)
b64_auth = base64.b64encode(authorization).decode()
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Basic {b64_auth}"
}

# Resolve relative path to the script directory and check existence
base_dir = os.path.dirname(os.path.abspath(__file__))
excel_path = EXCEL_FILE if os.path.isabs(EXCEL_FILE) else os.path.join(base_dir, EXCEL_FILE)
if not os.path.exists(excel_path):
    print(f"Error: Excel file not found: {excel_path}")
    print(f"Script directory: {base_dir}")
    print("Files in script directory:")
    for f in sorted(os.listdir(base_dir)):
        print("  ", f)
    sys.exit(1)

def append_log_text(text):
    global LOG_FILE
    with log_lock:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(text)
        except PermissionError:
            fallback = os.path.join(
                os.path.dirname(LOG_FILE),
                f"{os.path.splitext(os.path.basename(LOG_FILE))[0]}_fallback_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.txt"
            )
            print(f"WARNING: Could not write to log file '{LOG_FILE}'. Writing to fallback log '{fallback}'.")
            LOG_FILE = fallback
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(text)


def log_api_call(url, payload, response):
    """
    Logs details of an API call to the log file.
    Args:
        url (str): The API endpoint URL.
        payload (dict): The request payload.
        response (requests.Response): The HTTP response object.
    """
    append_log_text(
        f"\n[{datetime.datetime.now()}]\n"
        f"URL: {url}\n"
        f"Payload: {json.dumps(payload, indent=2)}\n"
        f"Response [{response.status_code}]: {response.text}\n"
        f"{'-' * 60}\n"
    )

def log(msg):
    """
    Writes a message to the log file.
    Args:
        msg (str): The message to log.
    """
    append_log_text(msg + "\n")


def response_json(response, context):
    try:
        return response.json()
    except ValueError as exc:
        body_preview = (response.text or "").strip().replace("\n", " ")[:1000]
        raise RuntimeError(
            f"{context} returned non-JSON response. Status={response.status_code}. "
            f"Content-Type={response.headers.get('Content-Type')}. Body preview: {body_preview}"
        ) from exc


def run_parallel_batch(name, items, worker, max_workers=MAX_WORKERS):
    items = list(items)
    if not items:
        return []
    log(f"Starting parallel batch '{name}' with {len(items)} item(s), max_workers={max_workers}.")
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(worker, item): item for item in items}
        completed = 0
        for future in as_completed(future_to_item):
            completed += 1
            item = future_to_item[future]
            try:
                results.append(future.result())
            except Exception as exc:
                log(f"ERROR: Parallel batch '{name}' item failed: {item} - {exc}")
                results.append(None)
            log(f"Progress '{name}': {completed}/{len(items)}")
    log(f"Finished parallel batch '{name}'.")
    return results

def url_encode(name):
    """
    URL-encodes a string for safe use in API endpoints.
    Args:
        name (str): The string to encode.
    Returns:
        str: The URL-encoded string.
    """
    return urllib.parse.quote(name)


def _wit_lookup_keys(value):
    value = "" if value is None else str(value).strip()
    if not value:
        return []
    keys = [value, value.lower()]
    compact = value.replace(" ", "")
    keys.extend([compact, compact.lower()])
    return list(dict.fromkeys(keys))


def index_work_item_type(existing_wits, wit):
    reference_name = str(wit.get("referenceName", "")).strip()
    display_name = str(wit.get("name", "")).strip()
    short_name = reference_name.rsplit(".", 1)[-1] if "." in reference_name else reference_name
    for key in _wit_lookup_keys(reference_name) + _wit_lookup_keys(short_name) + _wit_lookup_keys(display_name):
        existing_wits[key] = wit


def resolve_existing_work_item_type(existing_wits, *candidates):
    for candidate in candidates:
        for key in _wit_lookup_keys(candidate):
            if key in existing_wits:
                return existing_wits[key]
    return None


def is_system_reference(reference_name):
    return str(reference_name or "").strip().startswith("Microsoft.VSTS.WorkItemTypes.")


def short_reference_name(reference_name):
    reference_name = str(reference_name or "").strip()
    return reference_name.rsplit(".", 1)[-1] if "." in reference_name else reference_name


def create_or_update_process_wit(wit_name, description, ref_name, color, icon, inherit_from, existing_wit):
    payload = {
        "name": wit_name,
        "description": description,
        "referenceName": ref_name,
        "color": color,
        "icon": icon
    }
    if inherit_from:
        payload["inheritsFrom"] = inherit_from

    if existing_wit and str(existing_wit.get("customization", "")).strip().lower() != "system":
        full_ref = existing_wit["referenceName"]
        update_url = f"{ADO_ORG_URL}/_apis/work/processes/{ADO_PROCESS_ID}/workitemtypes/{url_encode(full_ref)}?api-version=7.1-preview.2"
        response = requests.patch(update_url, json=payload, headers=headers)
        log_api_call(update_url, payload, response)
        print(f"Updated: {wit_name}")
        return {"wit": wit_name, "status": "updated", "status_code": response.status_code}

    create_url = f"{ADO_ORG_URL}/_apis/work/processes/{ADO_PROCESS_ID}/workitemtypes?api-version=7.1-preview.2"
    response = requests.post(create_url, json=payload, headers=headers)
    log_api_call(create_url, payload, response)
    if response.status_code == 409 and existing_wit:
        print(f"Already exists or inherited: {wit_name}")
        return {"wit": wit_name, "status": "already-exists", "status_code": response.status_code}
    print(f"Created: {wit_name}")
    return {"wit": wit_name, "status": "created", "status_code": response.status_code}


def refresh_work_item_types(process_id):
    wit_url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workitemtypes?api-version=7.1-preview.2"
    response = requests.get(wit_url, headers=headers)
    log_api_call(wit_url, {}, response)
    response.raise_for_status()
    refreshed = {}
    for wit in response_json(response, "Refresh work item types").get("value", []):
        index_work_item_type(refreshed, wit)
    return refreshed


def ensure_work_item_state(wit_reference_name, state_name, color="B2B2B2", state_category="Proposed", *, required=True):
    states_url = (
        f"{ADO_ORG_URL}/_apis/work/processes/{ADO_PROCESS_ID}/workItemTypes/"
        f"{url_encode(wit_reference_name)}/states?api-version=7.1-preview.1"
    )
    response = requests.get(states_url, headers=headers)
    log_api_call(states_url, {}, response)
    if response.status_code == 404:
        log(f"WARNING: Could not read states for {wit_reference_name}; skipping state '{state_name}'.")
        return False
    response.raise_for_status()
    states = response_json(response, f"List states for {wit_reference_name}").get("value", [])
    if any(str(state.get("name", "")).strip().lower() == state_name.lower() for state in states):
        print(f"State already exists for {wit_reference_name}: {state_name}")
        log(f"State already exists for {wit_reference_name}: {state_name}")
        return True

    payload = {
        "name": state_name,
        "color": color,
        "stateCategory": state_category,
    }
    create_response = requests.post(states_url, headers=headers, json=payload)
    log_api_call(states_url, payload, create_response)
    if create_response.status_code in (200, 201):
        print(f"Created state '{state_name}' for {wit_reference_name}")
        log(f"Created state '{state_name}' for {wit_reference_name}")
        return True
    elif create_response.status_code == 409:
        print(f"State already exists for {wit_reference_name}: {state_name}")
        log(f"State already exists for {wit_reference_name}: {state_name}")
        return True
    else:
        message = (
            f"Failed to create state '{state_name}' for {wit_reference_name}: "
            f"{create_response.status_code} - {create_response.text}"
        )
        if required:
            raise RuntimeError(message)
        log(f"WARNING: {message}")
        return False


def test_case_state_references(existing_wits):
    refs = []
    for wit in existing_wits.values():
        name = str(wit.get("name", "")).strip().lower()
        reference_name = str(wit.get("referenceName", "")).strip()
        if not reference_name:
            continue
        if name in {"test case", "testcase", "test case ms bpc"} or reference_name.lower().endswith(".testcase"):
            refs.append(reference_name)
    refs.append("Microsoft.VSTS.WorkItemTypes.TestCase")
    return list(dict.fromkeys(refs))


def get_agile_process_id():
    """
    Retrieves the process type ID for the built-in Agile process.
    Returns:
        str: The Agile process type ID.
    Raises:
        Exception: If Agile process is not found.
    """
    url = f"{ADO_ORG_URL}/_apis/work/processes?api-version=7.1-preview.2"
    resp = requests.get(url, headers=headers)
    log_api_call(url, {}, resp)
    resp.raise_for_status()
    for proc in response_json(resp, "List processes for Agile lookup").get("value", []):
        if proc["name"].lower() == "agile":
            return proc["typeId"]
    raise Exception("Agile process not found.")

def get_process_id_by_name(process_name):
    """
    Gets the process type ID for a given process name.
    Args:
        process_name (str): The name of the process.
    Returns:
        str or None: The process type ID, or None if not found.
    """
    url = f"{ADO_ORG_URL}/_apis/work/processes?api-version=7.1-preview.2"
    resp = requests.get(url, headers=headers)
    log_api_call(url, {}, resp)
    resp.raise_for_status()
    for proc in response_json(resp, "List processes by name").get("value", []):
        if proc["name"].strip().lower() == process_name.strip().lower():
            return proc["typeId"]
    return None

def create_process(process_name):
    """
    Creates a new custom process based on Agile if it does not exist.
    Args:
        process_name (str): The name of the process to create.
    Returns:
        str: The process type ID.
    """
    agile_id = get_agile_process_id()
    url = f"{ADO_ORG_URL}/_apis/work/processes?api-version=7.1-preview.2"
    payload = {
        "name": process_name,
        "description": f"Custom process based on Agile: {process_name}",
        "parentProcessTypeId": agile_id
    }
    resp = requests.post(url, headers=headers, json=payload)
    log_api_call(url, payload, resp)
    if resp.status_code in [200, 201]:
        print(f"Created process: {process_name}")
        return resp.json().get("typeId")
    elif resp.status_code == 409:
        print(f"Process already exists: {process_name}")
        return get_process_id_by_name(process_name)
    else:
        print(f"Failed to create process: {resp.status_code} - {resp.text}")
        raise Exception("Process creation failed.")

def get_project_id_by_name(project_name):
    """
    Gets the project ID for a given project name.
    Args:
        project_name (str): The name of the project.
    Returns:
        str or None: The project ID, or None if not found.
    """
    url = f"{ADO_ORG_URL}/_apis/projects?api-version=7.1-preview.4"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    for proj in resp.json().get("value", []):
        if proj["name"].strip().lower() == project_name.strip().lower():
            return proj["id"]
    return None

def create_project(project_name, process_id):
    """
    Creates a new Azure DevOps project using the specified process.
    Args:
        project_name (str): The name of the project.
        process_id (str): The process type ID to use.
    Returns:
        str or None: The project ID, or None if creation is asynchronous.
    """
    url = f"{ADO_ORG_URL}/_apis/projects?api-version=7.1-preview.4"
    payload = {
        "name": project_name,
        "description": f"Project for process {process_id}",
        "capabilities": {
            "versioncontrol": {"sourceControlType": "Git"},
            "processTemplate": {"templateTypeId": process_id}
        }
    }
    resp = requests.post(url, headers=headers, json=payload)
    log_api_call(url, payload, resp)
    if resp.status_code in [202]:  # Project creation is async
        print(f"Project creation started: {project_name}")
        return None
    elif resp.status_code == 409:
        print(f"Project already exists: {project_name}")
        return get_project_id_by_name(project_name)
    else:
        print(f"Failed to create project: {resp.status_code} - {resp.text}")
        raise Exception("Project creation failed.")

def build_reference_name(wit_name):
    """
    Builds a reference name for a work item type by removing spaces and special characters.
    Args:
        wit_name (str): The work item type name.
    Returns:
        str: The reference name.
    """
    safe_process = PROCESS_NAME.replace(" ", "")  # Remove spaces from process name
    safe_name = wit_name.replace(" ", "").replace("-", "").replace("_", "")
    return f"{safe_process}.{safe_name}"

def safe_json_value(val, default=""):
    """
    Safely converts a value to string, handling NaN and None.
    Args:
        val: The value to convert.
        default: The default value if val is NaN or None.
    Returns:
        str: The safe string value.
    """
    if pd.isna(val) or val is None:
        return default
    if isinstance(val, float) and (val != val):
        return default
    return str(val)
# Clear the log file
log(f"Starting Script 1. Log file: {LOG_FILE}")

# === PROCESS AND PROJECT CREATION ===
# Ensure the process and project exist before proceeding.
process_id = get_process_id_by_name(PROCESS_NAME)
if not process_id:
    process_id = create_process(PROCESS_NAME)

project_id = get_project_id_by_name(ADO_PROJECT)
if not project_id:
    create_project(ADO_PROJECT, process_id)
    print("Waiting 30 seconds for project creation to complete...")
    time.sleep(30)
else:
    print(f"Project already exists: {ADO_PROJECT}")

ADO_PROCESS_ID = process_id

# === WORK ITEM TYPES CREATION/UPDATE ===
print("Starting work item type creation...")
df = pd.read_excel(excel_path, sheet_name="Work item types")
df.columns = df.columns.str.strip()
df = df.drop_duplicates(subset=["Work item type"])
for col, default in [("Description", ""), ("Color", "0078D4"), ("Icon", "icon_gear")]:
    if col in df.columns:
        df[col] = df[col].fillna(default)

# Fetch all existing work item types in one call to avoid per-item 500 errors
wit_list_url = f"{ADO_ORG_URL}/_apis/work/processes/{ADO_PROCESS_ID}/workitemtypes?api-version=7.1-preview.2"
wit_list_response = requests.get(wit_list_url, headers=headers)
log_api_call(wit_list_url, {}, wit_list_response)
existing_wits = {}
if wit_list_response.status_code == 200:
    for wit in wit_list_response.json().get("value", []):
        index_work_item_type(existing_wits, wit)

def process_work_item_type_row(row):
    wit_name = row["Work item type"]
    description = row["Help text"] if "Help text" in row and pd.notna(row["Help text"]) else ""
    inherit_from = row.get("Inherit from", None)
    color = row["Color"]
    icon = row["Icon"] if pd.notna(row["Icon"]) and str(row["Icon"]).strip() != "" else "icon_test_case"
    custom_flag = str(row.get("Custom work item type", "")).strip().lower()
    ref_name = row.get("Reference name", build_reference_name(wit_name)).strip()

    # Check if work item type already exists using the pre-fetched list
    existing_wit = resolve_existing_work_item_type(existing_wits, ref_name, wit_name)
    exists = existing_wit is not None

    if custom_flag == "no":
        if is_system_reference(ref_name):
            # Create a process-specific WIT that inherits from the OOB type.
            # The process API uses the short final segment (Bug, TestCase, etc.)
            # as the local reference name, then prefixes it with the process name.
            local_ref_name = short_reference_name(ref_name)
            return create_or_update_process_wit(
                wit_name, description, local_ref_name, color, icon,
                ref_name, existing_wit
            )
        print(f"Skipped: {wit_name} (Standard work item, no changes)")
        return {"wit": wit_name, "status": "skipped"}

    # Inherited system work item types marked as disabled are skipped here.
    # Azure DevOps exposes them in the UI, but the public Process API returns
    # 404 for disabling them in inherited processes.
    if custom_flag == "disabled":
        print(f"Skipped: {wit_name} (marked disabled; disable manually in Azure DevOps if needed)")
        log(f"Skipped disabled WIT '{wit_name}' ({ref_name}); public Process API disable is not reliable for inherited system WITs.")
        return {"wit": wit_name, "status": "skipped-disabled"}

    # Create or update custom work item type
    if custom_flag == "yes":
        inherit_ref = ""
        source_inherit_ref = str(inherit_from).strip() if pd.notna(inherit_from) and str(inherit_from).strip() != "" else ""
        if source_inherit_ref:
            if ALLOW_CUSTOM_WIT_INHERITANCE:
                inherit_ref = source_inherit_ref
            else:
                log(
                    f"Ignoring Inherit from '{source_inherit_ref}' for custom WIT '{wit_name}'. "
                    "Custom WIT inheritance is disabled by default to avoid duplicate inherited system WIT conflicts."
                )
        return create_or_update_process_wit(
            wit_name, description, ref_name, color, icon,
            inherit_ref, existing_wit
        )

    return {"wit": wit_name, "status": "ignored"}


run_parallel_batch("work item types", [row for _, row in df.iterrows()], process_work_item_type_row)

print("Work item type creation complete.")

existing_wits = refresh_work_item_types(ADO_PROCESS_ID)
test_case_refs = test_case_state_references(existing_wits)
if test_case_refs:
    ensured_refs = [
        ref for ref in test_case_refs
        if ensure_work_item_state(ref, "New", color="B2B2B2", state_category="Proposed", required=False)
    ]
    if not ensured_refs:
        raise RuntimeError("Could not confirm or create the New state on any Test Case work item type reference.")
    log(f"Confirmed Test Case New state on: {', '.join(ensured_refs)}")
else:
    log("WARNING: Could not find Test Case work item type to add the New state.")

# === FIELD AND PICKLIST CREATION/UPDATE ===
print("Starting Azure DevOps field creation script...")
print(f"Reading spreadsheet: {EXCEL_FILE}")

# Load fields from Excel
df_fields = pd.read_excel(excel_path, sheet_name="Fields")
df_fields.columns = df_fields.columns.str.strip()
df_fields = df_fields.drop_duplicates(subset=["Reference name"])
df_fields = df_fields.fillna("")

print(f"Loaded {len(df_fields)} fields from spreadsheet.")

multiselect_field_labels = set()
if "Multi-select field" in df_fields.columns:
    multiselect_mask = df_fields["Multi-select field"].astype(str).str.strip().str.lower().isin(["yes", "true", "1", "x"])
    multiselect_field_labels = set(df_fields.loc[multiselect_mask, "Label"].astype(str).str.strip())
    if multiselect_field_labels:
        log(
            "Multi-select backing fields detected. Their picklists will be marked suggested "
            f"to allow semicolon-separated stored values: {', '.join(sorted(multiselect_field_labels))}"
        )

# Load picklists from Excel
picklist_df = pd.read_excel(excel_path, sheet_name="Picklists")
picklist_df.columns = picklist_df.columns.str.strip()
picklist_dict = {}
for col in picklist_df.columns:
    values = [safe_json_value(v) for v in picklist_df[col].dropna().tolist()]
    values = [v for v in values if v != ""]
    values = list(dict.fromkeys(values))
    if values:
        picklist_dict[col] = values

print(f"Loaded {len(picklist_dict)} picklists from Picklists tab.")

# Get existing organization fields
fields_url = f"{ADO_ORG_URL}/_apis/wit/fields?api-version=7.1-preview.2"
fields_response = requests.get(fields_url, headers=headers)
log_api_call(fields_url, {}, fields_response)
if fields_response.status_code == 200:
    try:
        fields_json = fields_response.json()
        existing_fields = {field["referenceName"]: field for field in fields_json.get("value", [])}
        existing_fields_by_name = {field["name"]: field for field in fields_json.get("value", [])}
    except Exception as e:
        log(f"Error decoding fields JSON: {e}")
        existing_fields = {}
        existing_fields_by_name = {}
else:
    log(f"Fields endpoint returned status {fields_response.status_code}: {fields_response.text}")
    existing_fields = {}
    existing_fields_by_name = {}

# Get existing picklists
lists_url = f"{ADO_ORG_URL}/_apis/work/processes/lists?api-version=7.1"
picklist_ids = {}

existing_lists_resp = requests.get(lists_url, headers=headers)
log_api_call(lists_url, {}, existing_lists_resp)
existing_lists = {}
if existing_lists_resp.status_code == 200:
    try:
        lists_json = existing_lists_resp.json()
        for lst in lists_json.get("value", []):
            existing_lists[lst["name"]] = lst
    except Exception as e:
        log(f"Error decoding lists JSON: {e}")

def process_picklist_item(label_values):
    label, values = label_values
    payload = {
        "name": label,
        "type": "String",
        "items": values,
        "isSuggested": label in multiselect_field_labels
    }
    if label in existing_lists:
        picklist_id = existing_lists[label]["id"]
        update_url = f"{ADO_ORG_URL}/_apis/work/processes/lists/{picklist_id}?api-version=7.1"
        print(f"Updating picklist: {label} with values: {values}")
        log(f"Updating picklist: {label} with values: {values}")
        response = requests.put(update_url, json=payload, headers=headers)
        log_api_call(update_url, payload, response)
        if response.status_code in [200, 201]:
            log(f"  Picklist updated with id: {picklist_id}")
            return label, picklist_id
        else:
            print(f"  Failed to update picklist: {label}")
            log(f"  Failed to update picklist: {label}")
            log(f"  Response: {response.text}")
            return label, None
    else:
        print(f"Creating picklist: {label} with values: {values}")
        log(f"Creating picklist: {label} with values: {values}")
        response = requests.post(lists_url, json=payload, headers=headers)
        log_api_call(lists_url, payload, response)
        if response.status_code in [200, 201]:
            picklist_id = response.json().get("id")
            log(f"  Picklist created with id: {picklist_id}")
            return label, picklist_id
        else:
            print(f"  Failed to create picklist: {label}")
            log(f"  Failed to create picklist: {label}")
            log(f"  Response: {response.text}")
            return label, None


for result in run_parallel_batch("picklists", list(picklist_dict.items()), process_picklist_item):
    if result:
        label, picklist_id = result
        if picklist_id:
            picklist_ids[label] = picklist_id

# Create or update fields
fields_url_create = f"{ADO_ORG_URL}/_apis/wit/fields?api-version=7.1"
def process_field_row(row):
    field_name = safe_json_value(row.get("Field name"))       # Unique name in ADO (suffixed with MS BPC)
    reference_name = safe_json_value(row.get("Reference name")) # Unique reference name
    field_label = safe_json_value(row.get("Label"))            # User-friendly display label
    field_type = safe_json_value(row.get("Field type"))
    custom_flag = str(safe_json_value(row.get("Custom field"))).strip().lower()
    description = safe_json_value(row.get("Description"))

    # Skip standard (OOB) fields
    if custom_flag == "no":
        print(f"Processing field: {field_label} (name: {field_name}, ref: {reference_name}) type: {field_type} Standard OOB field-skipping")
        log(f"Processing field: {field_label} (name: {field_name}, ref: {reference_name}) type: {field_type} Standard OOB field-skipping")
        return {"field": field_label, "status": "skipped-standard"}

    # Handle picklist fields — match picklist by Label (matches Picklists tab column headers)
    if field_type in ["PicklistString", "PicklistInteger"]:
        picklist_id = picklist_ids.get(field_label)
        if not picklist_id:
            print(f"  No picklist id found for label '{field_label}', skipping field creation.")
            log(f"  No picklist id found for label '{field_label}', skipping field creation.")
            return {"field": field_label, "status": "skipped-missing-picklist"}
        field_payload = {
            "name": field_name,
            "referenceName": reference_name,
            "type": "String",
            "isPicklist": True,
            "isPicklistSuggested": field_label in multiselect_field_labels,
            "picklistId": picklist_id,
            "description": description
        }
    else:
        field_payload = {
            "name": field_name,
            "type": field_type,
            "referenceName": reference_name,
            "description": description
        }

    # Check for existing fields by both reference name and name
    ref_match = existing_fields.get(reference_name)
    name_match = existing_fields_by_name.get(field_name)
    ref_exists = ref_match is not None
    name_exists = name_match is not None

    if ref_exists and name_exists:
        # Both match — verify they point to the same field, then update
        if ref_match["referenceName"] == name_match["referenceName"]:
            print(f"  Field '{reference_name}' (name: {field_name}) already exists. Updating...")
            log(f"Field '{reference_name}' (name: {field_name}) already exists. Updating...")
            log("Payload: " + json.dumps(field_payload, indent=2, allow_nan=False))
            update_field_url = f"{ADO_ORG_URL}/_apis/wit/fields/{url_encode(reference_name)}?api-version=7.1"
            response = requests.patch(update_field_url, json=field_payload, headers=headers)
            log_api_call(update_field_url, field_payload, response)
            print(f"  Field update response: {response}")
            return {"field": field_label, "status": "updated", "status_code": response.status_code}
        else:
            # Reference name and name each exist but belong to different fields — conflict
            error_msg = (f"ERROR: Conflict for field '{field_label}' — reference name '{reference_name}' matches "
                         f"existing field '{ref_match['name']}', but name '{field_name}' matches a different "
                         f"existing field with ref '{name_match['referenceName']}'. Please review and correct.")
            print(f"  {error_msg}")
            log(error_msg)
            return {"field": field_label, "status": "conflict"}
    elif ref_exists and not name_exists:
        # Only reference name matches — partial conflict
        error_msg = (f"ERROR: Partial match for field '{field_label}' — reference name '{reference_name}' already "
                     f"exists with name '{ref_match['name']}', but the expected name '{field_name}' was not found. "
                     f"Please review and correct the spreadsheet.")
        print(f"  {error_msg}")
        log(error_msg)
        return {"field": field_label, "status": "partial-reference-conflict"}
    elif not ref_exists and name_exists:
        # Only name matches — partial conflict
        error_msg = (f"ERROR: Partial match for field '{field_label}' — name '{field_name}' already exists with "
                     f"reference name '{name_match['referenceName']}', but the expected reference name "
                     f"'{reference_name}' was not found. Please review and correct the spreadsheet.")
        print(f"  {error_msg}")
        log(error_msg)
        return {"field": field_label, "status": "partial-name-conflict"}
    else:
        # Neither exists — create new field
        print(f"Creating field: {field_label} (name: {field_name}, ref: {reference_name})")
        log(f"Creating field: {field_label} (name: {field_name}, ref: {reference_name})")
        log("Payload: " + json.dumps(field_payload, indent=2, allow_nan=False))
        response = requests.post(fields_url_create, json=field_payload, headers=headers)
        log_api_call(fields_url_create, field_payload, response)
        print(f"  Field creation response: {response}")
        return {"field": field_label, "status": "created", "status_code": response.status_code}


run_parallel_batch("fields", [row for _, row in df_fields.iterrows()], process_field_row)

print("Script finished. See log file for details:")
print(f"  {LOG_FILE}")
log("Done!")
