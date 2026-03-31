import pandas as pd
import requests
import base64
import json
import time
import urllib.parse
import datetime
import os
import sys

# === USER CONFIGURATION ===
# Fill in these variables with your Azure DevOps details and file paths.
ADO_ORG_URL = "https://dev.azure.com/<YOUR_ORGANIZATION>"       # e.g. "https://dev.azure.com/Contoso"
ADO_PROJECT = "<YOUR_PROJECT_NAME>"                              # e.g. "Business process catalog"
PROCESS_NAME = "<YOUR_PROCESS_NAME>"                             # e.g. "Business process catalog"
PAT = "<YOUR_PERSONAL_ACCESS_TOKEN>"                             # Azure DevOps PAT with full access
EXCEL_FILE = "ADO template guideline (Preview).xlsx"     # Path to the Excel template file
LOG_FILE = "1_ADO_Creation_Script_Log.txt"

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

def log_api_call(url, payload, response):
    """
    Logs details of an API call to the log file.
    Args:
        url (str): The API endpoint URL.
        payload (dict): The request payload.
        response (requests.Response): The HTTP response object.
    """
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.datetime.now()}]\n")
        f.write(f"URL: {url}\n")
        f.write(f"Payload: {json.dumps(payload, indent=2)}\n")
        f.write(f"Response [{response.status_code}]: {response.text}\n")
        f.write("-" * 60 + "\n")

def log(msg):
    """
    Writes a message to the log file.
    Args:
        msg (str): The message to log.
    """
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def url_encode(name):
    """
    URL-encodes a string for safe use in API endpoints.
    Args:
        name (str): The string to encode.
    Returns:
        str: The URL-encoded string.
    """
    return urllib.parse.quote(name)

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
    resp.raise_for_status()
    for proc in resp.json().get("value", []):
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
    resp.raise_for_status()
    for proc in resp.json().get("value", []):
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
if os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)

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
        existing_wits[wit["referenceName"]] = wit
        # Also index by the short name (last segment) for matching spreadsheet ref names
        short_name = wit["referenceName"].rsplit(".", 1)[-1] if "." in wit["referenceName"] else wit["referenceName"]
        existing_wits[short_name] = wit

for idx, row in df.iterrows():
    wit_name = row["Work item type"]
    description = row["Help text"] if "Help text" in row and pd.notna(row["Help text"]) else ""
    inherit_from = row.get("Inherit from", None)
    color = row["Color"]
    icon = row["Icon"] if pd.notna(row["Icon"]) and str(row["Icon"]).strip() != "" else "icon_test_case"
    custom_flag = str(row.get("Custom work item type", "")).strip().lower()
    ref_name = row.get("Reference name", build_reference_name(wit_name)).strip()

    # Check if work item type already exists using the pre-fetched list
    exists = ref_name in existing_wits

    # Skip standard work item types (no action needed)
    if custom_flag == "no":
        print(f"Skipped: {wit_name} (Standard work item, no changes)")
        continue

    # Disable work item types marked as disabled
    if custom_flag == "disabled":
        if exists:
            full_ref = existing_wits[ref_name]["referenceName"]
            already_disabled = existing_wits[ref_name].get("isDisabled", False)
            if already_disabled:
                print(f"Already disabled: {wit_name}")
            else:
                disable_url = f"{ADO_ORG_URL}/_apis/work/processes/{ADO_PROCESS_ID}/workitemtypes/{full_ref}?api-version=7.1-preview.2"
                disable_payload = {"isDisabled": True}
                response = requests.patch(disable_url, json=disable_payload, headers=headers)
                log_api_call(disable_url, disable_payload, response)
                if response.status_code in [200, 204]:
                    print(f"Disabled: {wit_name}")
                else:
                    print(f"ERROR disabling {wit_name}: {response.status_code} - {response.text}")
        else:
            print(f"Skipped: {wit_name} (marked disabled but not found in process)")
        continue

    # Create or update custom work item type
    if custom_flag == "yes":
        payload = {
            "name": wit_name,
            "description": description,
            "referenceName": ref_name,
            "color": color,
            "icon": icon
        }
        if pd.notna(inherit_from) and str(inherit_from).strip() != "":
            payload["inherits"] = inherit_from

        if exists:
            # Use the full reference name from ADO for the update URL
            full_ref = existing_wits[ref_name]["referenceName"]
            update_url = f"{ADO_ORG_URL}/_apis/work/processes/{ADO_PROCESS_ID}/workitemtypes/{full_ref}?api-version=7.1-preview.2"
            response = requests.patch(update_url, json=payload, headers=headers)
            log_api_call(update_url, payload, response)
            print(f"Updated: {wit_name}")
        else:
            create_url = f"{ADO_ORG_URL}/_apis/work/processes/{ADO_PROCESS_ID}/workitemtypes?api-version=7.1-preview.2"
            response = requests.post(create_url, json=payload, headers=headers)
            log_api_call(create_url, payload, response)
            print(f"Created: {wit_name}")

print("Work item type creation complete.")

# === FIELD AND PICKLIST CREATION/UPDATE ===
print("Starting Azure DevOps field creation script...")
print(f"Reading spreadsheet: {EXCEL_FILE}")

# Load fields from Excel
df_fields = pd.read_excel(excel_path, sheet_name="Fields")
df_fields.columns = df_fields.columns.str.strip()
df_fields = df_fields.drop_duplicates(subset=["Reference name"])
df_fields = df_fields.fillna("")

print(f"Loaded {len(df_fields)} fields from spreadsheet.")

# Load picklists from Excel
picklist_df = pd.read_excel(excel_path, sheet_name="Picklists")
picklist_df.columns = picklist_df.columns.str.strip()
picklist_dict = {}
for col in picklist_df.columns:
    values = [safe_json_value(v) for v in picklist_df[col].dropna().tolist()]
    values = [v for v in values if v != ""]
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

# Create or update picklists
for label, values in picklist_dict.items():
    payload = {
        "name": label,
        "type": "String",
        "items": values
    }
    if label in existing_lists:
        picklist_id = existing_lists[label]["id"]
        update_url = f"{ADO_ORG_URL}/_apis/work/processes/lists/{picklist_id}?api-version=7.1"
        print(f"Updating picklist: {label} with values: {values}")
        log(f"Updating picklist: {label} with values: {values}")
        response = requests.put(update_url, json=payload, headers=headers)
        log_api_call(update_url, payload, response)
        if response.status_code in [200, 201]:
            picklist_ids[label] = picklist_id
            log(f"  Picklist updated with id: {picklist_id}")
        else:
            print(f"  Failed to update picklist: {label}")
            log(f"  Failed to update picklist: {label}")
            log(f"  Response: {response.text}")
    else:
        print(f"Creating picklist: {label} with values: {values}")
        log(f"Creating picklist: {label} with values: {values}")
        response = requests.post(lists_url, json=payload, headers=headers)
        log_api_call(lists_url, payload, response)
        if response.status_code in [200, 201]:
            picklist_id = response.json().get("id")
            picklist_ids[label] = picklist_id
            log(f"  Picklist created with id: {picklist_id}")
        else:
            print(f"  Failed to create picklist: {label}")
            log(f"  Failed to create picklist: {label}")
            log(f"  Response: {response.text}")

# Create or update fields
fields_url_create = f"{ADO_ORG_URL}/_apis/wit/fields?api-version=7.1"
for idx, row in df_fields.iterrows():
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
        continue

    # Handle picklist fields — match picklist by Label (matches Picklists tab column headers)
    if field_type in ["PicklistString", "PicklistInteger"]:
        picklist_id = picklist_ids.get(field_label)
        if not picklist_id:
            print(f"  No picklist id found for label '{field_label}', skipping field creation.")
            log(f"  No picklist id found for label '{field_label}', skipping field creation.")
            continue
        field_payload = {
            "name": field_name,
            "referenceName": reference_name,
            "type": "String",
            "isPicklist": True,
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
        else:
            # Reference name and name each exist but belong to different fields — conflict
            error_msg = (f"ERROR: Conflict for field '{field_label}' — reference name '{reference_name}' matches "
                         f"existing field '{ref_match['name']}', but name '{field_name}' matches a different "
                         f"existing field with ref '{name_match['referenceName']}'. Please review and correct.")
            print(f"  {error_msg}")
            log(error_msg)
    elif ref_exists and not name_exists:
        # Only reference name matches — partial conflict
        error_msg = (f"ERROR: Partial match for field '{field_label}' — reference name '{reference_name}' already "
                     f"exists with name '{ref_match['name']}', but the expected name '{field_name}' was not found. "
                     f"Please review and correct the spreadsheet.")
        print(f"  {error_msg}")
        log(error_msg)
    elif not ref_exists and name_exists:
        # Only name matches — partial conflict
        error_msg = (f"ERROR: Partial match for field '{field_label}' — name '{field_name}' already exists with "
                     f"reference name '{name_match['referenceName']}', but the expected reference name "
                     f"'{reference_name}' was not found. Please review and correct the spreadsheet.")
        print(f"  {error_msg}")
        log(error_msg)
    else:
        # Neither exists — create new field
        print(f"Creating field: {field_label} (name: {field_name}, ref: {reference_name})")
        log(f"Creating field: {field_label} (name: {field_name}, ref: {reference_name})")
        log("Payload: " + json.dumps(field_payload, indent=2, allow_nan=False))
        response = requests.post(fields_url_create, json=field_payload, headers=headers)
        log_api_call(fields_url_create, field_payload, response)
        print(f"  Field creation response: {response}")

print("Script finished. See log file for details:")
print(f"  {LOG_FILE}")
log("Done!")