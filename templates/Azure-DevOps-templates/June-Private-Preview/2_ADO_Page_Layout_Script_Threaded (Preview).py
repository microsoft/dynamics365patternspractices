import requests
import pandas as pd
import json
import re
from typing import Optional
import os
import urllib.parse
import sys
import base64
import time
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from ado_setup_config import load_config

# === CONFIGURATION ===
config = load_config(default_log_file="2_ADO_Page_Layout_Script_Threaded_Log.txt", require_process=True)
ADO_ORG_URL = config.ado_org_url
ADO_PROJECT = config.ado_project
PROCESS_NAME = config.process_name
PAT = config.pat
EXCEL_FILE = config.excel_file
LOG_FILE = config.log_file
SYSTEM_WORK_ITEM_TYPE = "Microsoft.VSTS.WorkItemTypes"
if os.path.basename(LOG_FILE) == "2_ADO_Page_Layout_Script_Threaded_Log.txt":
    run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_FILE = os.path.join(os.path.dirname(LOG_FILE), f"2_ADO_Page_Layout_Script_Threaded_Log_{run_id}.txt")

# === THREADING CONFIGURATION ===
# Maximum number of parallel threads for processing work item types
# Recommended: 5-10 to balance speed vs Azure DevOps API rate limits
MAX_WORKERS = 8

# Richard Jansen/partner preview feedback indicated Azure DevOps can add HTML
# controls through the layout API when the control payload uses HtmlFieldControl.
ADD_HTML_LAYOUT_CONTROLS = os.getenv("BPC_ADO_ADD_HTML_LAYOUT_CONTROLS", "true").strip().lower() not in ("0", "false", "no")
REMOVE_OLD_HTML_PLACEHOLDER_GROUPS = os.getenv("BPC_ADO_REMOVE_OLD_HTML_PLACEHOLDER_GROUPS", "true").strip().lower() not in ("0", "false", "no")
ADD_MULTIVALUE_CONTROLS = os.getenv("BPC_ADO_ADD_MULTIVALUE_CONTROLS", "true").strip().lower() not in ("0", "false", "no")
MULTIVALUE_PUBLISHER = "ms-devlabs"
MULTIVALUE_EXTENSION = "vsts-extensions-multivalue-control"
MULTIVALUE_CONTRIBUTION_ID = "ms-devlabs.vsts-extensions-multivalue-control.multivalue-form-control"
multivalue_extension_checked = False
multivalue_extension_available = False

# === AUTHENTICATION SETUP ===
authorization = str.encode(':' + PAT)
b64_auth = base64.b64encode(authorization).decode()
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Basic {b64_auth}"
}

# === THREAD-SAFE LOGGING ===
log_lock = threading.Lock()

def append_log_text(text: str):
    global LOG_FILE
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

def log(msg: str):
    """Thread-safe logging to file and console."""
    with log_lock:
        append_log_text(msg + "\n")
        print(msg)

# === THREAD-SAFE CACHES ===
layout_cache_lock = threading.Lock()
layout_cache: dict[str, Optional[dict]] = {}
locked_layout_wits: set[str] = set()

# === Retry logic for requests ===
def make_request_with_retry(method, url, max_retries=3, retry_delay=2, **kwargs):
    """
    Makes an HTTP request with retry logic for transient errors.
    
    Args:
        method: HTTP method ('GET', 'POST', 'PATCH', 'PUT', 'DELETE')
        url: Request URL
        max_retries: Maximum retry attempts
        retry_delay: Initial delay in seconds (exponential backoff)
        **kwargs: Additional arguments to pass to requests (headers, json, etc.)
    
    Returns:
        Response object
    """
    resp = None
    for attempt in range(max_retries):
        try:
            if method.upper() == 'GET':
                resp = requests.get(url, **kwargs)
            elif method.upper() == 'POST':
                resp = requests.post(url, **kwargs)
            elif method.upper() == 'PATCH':
                resp = requests.patch(url, **kwargs)
            elif method.upper() == 'PUT':
                resp = requests.put(url, **kwargs)
            elif method.upper() == 'DELETE':
                resp = requests.delete(url, **kwargs)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            # Handle rate limiting and service unavailability
            if resp.status_code in (429, 503, 504):
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    log(f" Service unavailable (status {resp.status_code}). Retrying in {wait_time} seconds... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
            
            return resp
            
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                log(f" Request error: {e}. Retrying in {wait_time} seconds... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                raise
    
    return resp


def get_org_name() -> str:
    return ADO_ORG_URL.rstrip("/").split("/")[-1]


def ensure_multivalue_extension_installed() -> bool:
    global multivalue_extension_checked, multivalue_extension_available
    if multivalue_extension_checked:
        return multivalue_extension_available
    if not ADD_MULTIVALUE_CONTROLS:
        multivalue_extension_checked = True
        multivalue_extension_available = False
        return False

    org = get_org_name()
    url = (f"https://extmgmt.dev.azure.com/{org}/_apis/extensionmanagement/installedextensionsbyname/"
           f"{MULTIVALUE_PUBLISHER}/{MULTIVALUE_EXTENSION}?api-version=7.1-preview.1")
    log(f" Ensuring Azure DevOps extension is installed: {MULTIVALUE_PUBLISHER}.{MULTIVALUE_EXTENSION}")
    resp = make_request_with_retry("POST", url, headers=headers)
    if resp.status_code in [200, 201] or (resp.status_code == 409 and "already installed" in resp.text.lower()):
        multivalue_extension_checked = True
        multivalue_extension_available = True
        log(" Multivalue control extension is installed or already available.")
        return True

    multivalue_extension_checked = True
    multivalue_extension_available = False
    log(f" WARNING: Could not install/confirm multivalue control extension: {resp.status_code} - {resp.text}")
    log("          Install it manually from Marketplace or rerun with a PAT that can manage extensions.")
    return False

# === Process ID Lookup ===
def get_process_id_by_name(process_name):
    """
    Gets the process type ID for a given process name.
    Args:
        process_name (str): The name of the process.
    Returns:
        str: The process type ID.
    Raises:
        Exception: If process is not found.
    """
    url = f"{ADO_ORG_URL}/_apis/work/processes?api-version=7.1-preview.2"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    for proc in resp.json().get("value", []):
        if proc["name"].strip().lower() == process_name.strip().lower():
            log(f"Found process '{process_name}' with ID: {proc['typeId']}")
            return proc["typeId"]
    raise Exception(f"Process '{process_name}' not found. Please create it first using ADO_Creation_Script.py")

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

def is_system_work_item_type(wit_ref_name: str) -> bool:
    """
    Determines if a work item type is an OOTB system type (locked layout).
    Args:
        wit_ref_name (str): The reference name of the work item type.
    Returns:
        bool: True if it's a system work item type, False otherwise.
    """
    return wit_ref_name.startswith("Microsoft.VSTS.WorkItemTypes.")


def get_process_work_item_type_map(process_id: str) -> dict:
    url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workitemtypes?api-version=7.1-preview.2"
    resp = make_request_with_retry("GET", url, headers=headers)
    if resp.status_code != 200:
        log(f" WARNING: Could not retrieve process work item type list: {resp.status_code} - {resp.text}")
        return {}

    wit_map = {}
    for wit in resp.json().get("value", []):
        ref = safe_json_value(wit.get("referenceName")).strip()
        name = safe_json_value(wit.get("name")).strip()
        if ref:
            wit_map[ref.lower()] = wit
            wit_map[ref.rsplit(".", 1)[-1].lower()] = wit
        if name:
            wit_map[name.lower()] = wit
            wit_map[name.replace(" ", "").lower()] = wit
    log(f"Retrieved {len(resp.json().get('value', []))} work item types from the process API.")
    return wit_map


def resolve_process_wit_reference(wit_name: str, excel_ref_name: str, custom_type_flag: str, process_wit_map: dict) -> Optional[str]:
    candidates = []
    if custom_type_flag == "yes":
        candidates.extend([build_reference_name(wit_name), excel_ref_name])
    else:
        candidates.extend([
            excel_ref_name,
            wit_name,
            wit_name.replace(" ", ""),
            f"{SYSTEM_WORK_ITEM_TYPE}.{wit_name}",
            f"{SYSTEM_WORK_ITEM_TYPE}.{wit_name.replace(' ', '')}",
        ])

    for candidate in candidates:
        candidate = safe_json_value(candidate).strip()
        if not candidate:
            continue
        match = process_wit_map.get(candidate.lower())
        if match and match.get("referenceName"):
            return match["referenceName"]

    if custom_type_flag == "yes":
        return build_reference_name(wit_name)
    if excel_ref_name:
        return excel_ref_name
    return f"{SYSTEM_WORK_ITEM_TYPE}.{wit_name.replace(' ', '')}"


def resolve_wit_process_api_identifier(wit_name: str, wit_ref_name: str, process_wit_map: dict) -> str:
    """
    For inherited/custom WITs, the Process API accepts the canonical reference
    name. For several system Agile WITs, field mutation endpoints can require
    the display name even though the process WIT list returns the global
    Microsoft.VSTS.WorkItemTypes.* reference name.
    """
    wit = process_wit_map.get(safe_json_value(wit_name).strip().lower()) or process_wit_map.get(safe_json_value(wit_ref_name).strip().lower())
    if wit:
        resolved_ref = safe_json_value(wit.get("referenceName")).strip()
        resolved_name = safe_json_value(wit.get("name")).strip()
        if resolved_ref.startswith(f"{SYSTEM_WORK_ITEM_TYPE}."):
            return resolved_name or wit_name or resolved_ref
        return resolved_ref or resolved_name or wit_ref_name or wit_name
    if is_system_work_item_type(wit_ref_name):
        return safe_json_value(wit_name).strip() or wit_ref_name
    return wit_ref_name


def ensure_inherited_wit_customized(wit_ref_name: str, process_id: str, process_wit_map: dict) -> bool:
    wit_info = process_wit_map.get(wit_ref_name.lower())
    if not wit_info:
        return False
    if safe_json_value(wit_info.get("customization")).strip().lower() in ("inherited", "custom"):
        return True
    if not is_system_work_item_type(wit_ref_name):
        return True

    enc_wit = urllib.parse.quote(wit_ref_name, safe='')
    url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}?api-version=7.1-preview.2"
    payload = {
        "description": wit_info.get("description"),
        "color": wit_info.get("color"),
        "icon": wit_info.get("icon"),
        "isDisabled": wit_info.get("isDisabled", False)
    }
    log(f" Materializing inherited system WIT '{wit_ref_name}' before adding custom fields.")
    resp = make_request_with_retry("PATCH", url, headers=headers, json=payload)
    if resp.status_code in [200, 201]:
        wit_info["customization"] = "inherited"
        log(f" System WIT '{wit_ref_name}' is now customized in the inherited process.")
        return True
    if resp.status_code == 409:
        log(f" System WIT '{wit_ref_name}' already appears customized (409 conflict).")
        return True
    log(f" WARNING: Could not materialize system WIT '{wit_ref_name}': {resp.status_code} - {resp.text}")
    return False


def add_field_to_wit(wit_ref_name: str, wit_process_api_id: str, process_id: str, payload: dict, field_label: str,
                     field_name: str, process_wit_map: dict, is_boolean: bool = False) -> requests.Response:
    enc_wit = urllib.parse.quote(wit_process_api_id, safe='')
    add_field_url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}/fields?api-version=7.1-preview.2"
    log(f" Adding field '{field_label}' (name: {field_name}, ref: {payload.get('referenceName')}) "
        f"to WIT '{wit_ref_name}' via Process API ID '{wit_process_api_id}'")
    add_resp = make_request_with_retry('POST', add_field_url, headers=headers, json=payload)
    if add_resp.status_code == 404 and is_system_work_item_type(wit_ref_name) and wit_process_api_id == wit_ref_name:
        if ensure_inherited_wit_customized(wit_ref_name, process_id, process_wit_map):
            log(f" Retrying field '{field_label}' after materializing system WIT '{wit_ref_name}'.")
            add_resp = make_request_with_retry('POST', add_field_url, headers=headers, json=payload)
    if add_resp.status_code not in [200, 201] and is_boolean:
        if try_add_boolean_field(add_field_url, wit_ref_name, field_name, payload.get("referenceName", "")):
            class BooleanRetryResponse:
                status_code = 200
                text = "Boolean retry succeeded"
            return BooleanRetryResponse()
    if add_resp.status_code == 404 and is_system_work_item_type(wit_ref_name):
        log(f" WARNING: Azure DevOps process API still returned 404 for system WIT '{wit_ref_name}'. "
            "Review the API response and Azure DevOps process settings if endpoint casing and materialization both fail.")
    return add_resp

# === Utility helpers ===
def safe_json_value(val, default=""):
    if pd.isna(val) or val is None:
        return default
    if isinstance(val, float) and (val != val):  # NaN
        return default
    return str(val)

def parse_required(val):
    v = safe_json_value(val).strip().lower()
    if v == "yes":
        return True
    if v == "conditional":
        return False
    return False

def parse_default_value(val):
    v = safe_json_value(val)
    if v.strip().lower() == "none":
        return ""
    return v


def normalize_reference_name(ref: str) -> str:
    """Normalize reference names from Excel by removing invisible characters and accidental spaces."""
    if ref is None:
        return ""
    cleaned = str(ref).strip()
    cleaned = cleaned.replace("\u200b", "").replace("\ufeff", "").replace("\u200e", "").replace("\u200f", "")
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned


def normalize_boolean_default(val: object) -> bool:
    if val is None:
        return False
    try:
        if pd.isna(val):
            return False
    except Exception:
        pass
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(int(val))
    value = str(val).strip().lower()
    if value in ("true", "yes", "y", "1", "on"):
        return True
    if value in ("false", "no", "n", "0", "off", ""):
        return False
    return False


def build_boolean_field_payload(reference_name: str, required: bool = False, default_value: object = False) -> dict:
    return {
        "referenceName": reference_name,
        "defaultValue": normalize_boolean_default(default_value),
        "required": required,
        "requiredValue": False,
        "visible": True
    }


def try_add_boolean_field(add_field_url: str, wit_ref_name: str, field_name: str, field_ref: str) -> bool:
    variants = [("min_bool", {"referenceName": field_ref, "defaultValue": False, "visible": True})]
    for required in (False, True):
        variants.append((f"req_{str(required).lower()}_bool", {
            "referenceName": field_ref, "defaultValue": False, "required": required, "visible": True
        }))
        variants.append((f"req_{str(required).lower()}_bool_reqval", {
            "referenceName": field_ref, "defaultValue": False, "required": required, "requiredValue": False, "visible": True
        }))
    variants.append(("min_str", {"referenceName": field_ref, "defaultValue": "false", "visible": True}))
    for required in (False, True):
        variants.append((f"req_{str(required).lower()}_str", {
            "referenceName": field_ref, "defaultValue": "false", "required": required, "visible": True
        }))
        variants.append((f"req_{str(required).lower()}_str_reqval", {
            "referenceName": field_ref, "defaultValue": "false", "required": required, "requiredValue": "false", "visible": True
        }))

    last_status = None
    last_text = None
    for tag, payload in variants:
        log(f"  [BOOLEAN TRY] {field_ref} ({tag}) -> {json.dumps(payload)}")
        resp = make_request_with_retry('POST', add_field_url, headers=headers, json=payload)
        if resp is not None and resp.status_code in [200, 201]:
            log(f"  Boolean add succeeded for '{field_name}' ({field_ref}) on '{wit_ref_name}' using variant '{tag}'.")
            return True
        if resp is not None:
            last_status = resp.status_code
            last_text = resp.text
    log(f"  Boolean add failed for '{field_name}' ({field_ref}) on '{wit_ref_name}'. Last response: {last_status} - {last_text}")
    return False

# === Azure DevOps API helpers (Thread-Safe) ===
LOCKED_LAYOUT_MARKER = "FormLayoutInfoNotAvailableException"

def invalidate_layout_cache(wit_ref_name: str) -> None:
    """Thread-safe cache invalidation."""
    with layout_cache_lock:
        layout_cache.pop(wit_ref_name, None)

def get_layout(wit_ref_name: str, process_id: str, force_refresh: bool = False) -> Optional[dict]:
    """Get the layout for a work item type with retry logic (thread-safe)."""
    with layout_cache_lock:
        if not force_refresh:
            if wit_ref_name in locked_layout_wits:
                return None
            cached = layout_cache.get(wit_ref_name)
            if cached is not None:
                return cached

    url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workItemTypes/{wit_ref_name}/layout?api-version=7.1-preview.1"

    resp = make_request_with_retry('GET', url, headers=headers)

    if resp.status_code in (400, 403) and LOCKED_LAYOUT_MARKER in resp.text:
        log(f" Layout for '{wit_ref_name}' is locked (likely OOTB). Skipping layout changes.")
        with layout_cache_lock:
            locked_layout_wits.add(wit_ref_name)
            layout_cache.pop(wit_ref_name, None)
        return None

    resp.raise_for_status()
    result = resp.json()
    with layout_cache_lock:
        layout_cache[wit_ref_name] = result
    return result

def get_section_id(layout: Optional[dict], page_id: str, section_label: Optional[str] = None) -> Optional[str]:
    """
    Given a layout and a page_id, return the section id for the given section label
    (e.g., "Section 1"). If not found, return the first section id on the page.
    """
    if not layout:
        return None
    excel_to_ado_section = {
        "left": "section1",
        "middle": "section2",
        "right": "section3"
    }
    section_label_clean = section_label.strip().lower() if section_label else None
    mapped_label = excel_to_ado_section.get(section_label_clean, section_label_clean) if section_label_clean else None
    for page in layout.get("pages", []):
        if page.get("id") == page_id:
            for section in page.get("sections", []):
                api_label = section.get("id", "").strip().lower()
                if mapped_label and api_label == mapped_label:
                    return section.get("id")
            if page.get("sections"):
                return page["sections"][0]["id"]
    return None

def find_page_by_label(layout: Optional[dict], page_label: str) -> Optional[dict]:
    if not layout:
        return None
    for page in layout.get("pages", []):
        if page.get("label") == page_label:
            return page
    return None

def ensure_group_on_page(layout: Optional[dict], page_id: str, group_label: str) -> tuple[Optional[str], Optional[str]]:
    """
    Check if a group with the given label exists anywhere on the page (in any section).
    Returns (group_id, section_id) if found, otherwise (None, None).
    """
    if not layout:
        return None, None
    for page in layout.get("pages", []):
        if page.get("id") == page_id:
            for section in page.get("sections", []):
                for group in section.get("groups", []):
                    if group.get("label") == group_label:
                        return group.get("id"), section.get("id")
    return None, None

def ensure_group_in_section(layout: Optional[dict], page_id: str, section_id: str, group_label: str) -> Optional[str]:
    """
    Return group_id if a group with the given label exists in the specific section; otherwise None.
    """
    if not layout:
        return None
    for page in layout.get("pages", []):
        if page.get("id") == page_id:
            for section in page.get("sections", []):
                if section.get("id") == section_id:
                    for group in section.get("groups", []):
                        if group.get("label") == group_label:
                            return group.get("id")
    return None

def add_page_if_missing(wit_ref_name: str, process_id: str, page_label: str, order: int) -> Optional[str]:
    log(f"[add_page_if_missing] Checking for page '{page_label}' on '{wit_ref_name}'")
    layout = get_layout(wit_ref_name, process_id)
    if layout is None:
        return None
    existing = find_page_by_label(layout, page_label)
    if existing:
        log(f" Page '{page_label}' already exists on '{wit_ref_name}' (id: {existing.get('id')})")
        return existing.get("id")

    url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workItemTypes/{wit_ref_name}/layout/pages?api-version=7.1-preview.1"
    payload = {"label": page_label, "order": order, "visible": True, "inherited": True}
    log(f" Creating page '{page_label}' on '{wit_ref_name}' with payload: {json.dumps(payload)}")
    
    resp = make_request_with_retry('POST', url, headers=headers, json=payload)
    
    if resp.status_code in [200, 201]:
        invalidate_layout_cache(wit_ref_name)
        pid = resp.json().get("id")
        log(f" Added page '{page_label}' to '{wit_ref_name}' (id: {pid})")
        return pid
    elif resp.status_code == 409:
        layout = get_layout(wit_ref_name, process_id, force_refresh=True)
        if layout is None:
            return None
        existing = find_page_by_label(layout, page_label)
        if existing:
            return existing.get("id")
    log(f" ERROR: Failed to add page '{page_label}': {resp.status_code} - {resp.text}")
    return None

def add_group_if_missing(wit_ref_name: str, process_id: str, page_id: str, section_id: str, group_label: str) -> Optional[str]:
    """
    Ensures a group exists on the page. First checks the entire page for the group.
    If found in a different section, logs a warning and returns that group_id.
    If not found anywhere, creates it in the target section.
    """
    log(f"[add_group_if_missing] Checking for group '{group_label}' on page '{page_id}' for '{wit_ref_name}'")
    layout = get_layout(wit_ref_name, process_id)
    if layout is None:
        return None
    
    group_id, found_section_id = ensure_group_on_page(layout, page_id, group_label)
    if group_id:
        if found_section_id == section_id:
            log(f" Group '{group_label}' already exists in target section '{section_id}' on page '{page_id}' (id: {group_id})")
        else:
            log(f" WARNING: Group '{group_label}' already exists in section '{found_section_id}' instead of target section '{section_id}' on page '{page_id}' (id: {group_id}). Using existing group.")
        return group_id

    url = f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workItemTypes/{wit_ref_name}/layout/pages/{page_id}/sections/{section_id}/groups?api-version=7.1-preview.1"
    payload = {"label": group_label, "visible": True, "inherited": True}
    log(f" Creating group '{group_label}' in section '{section_id}' on page '{page_id}' with payload: {json.dumps(payload)}")
    
    resp = make_request_with_retry('POST', url, headers=headers, json=payload)
    
    if resp.status_code in [200, 201]:
        invalidate_layout_cache(wit_ref_name)
        layout = get_layout(wit_ref_name, process_id, force_refresh=True)
        if layout is None:
            return None
        group_id = ensure_group_in_section(layout, page_id, section_id, group_label)
        if group_id:
            log(f" Added group '{group_label}' to section '{section_id}' on page '{page_id}' (id: {group_id})")
            return group_id
    elif resp.status_code == 409:
        layout = get_layout(wit_ref_name, process_id, force_refresh=True)
        if layout is None:
            return None
        group_id, found_section_id = ensure_group_on_page(layout, page_id, group_label)
        if group_id:
            if found_section_id != section_id:
                log(f" WARNING: Group '{group_label}' was created in section '{found_section_id}' instead of target section '{section_id}' (409 conflict)")
            return group_id
    log(f" ERROR: Failed to add group '{group_label}': {resp.status_code} - {resp.text}")
    return None

def get_control_type(field_type: Optional[str], field_ref_name: str, picklist_name: Optional[str]) -> str:
    ft = (field_type or "").strip().lower()
    ref = (field_ref_name or "").strip().lower()
    pick = (picklist_name or "").strip()

    if ref in ["system.areaid", "system.area", "system.areapath", "system.iterationid", "system.iteration", "system.iterationpath"]:
        return "WorkItemClassificationControl"
    if ref in ["system.assignedto", "system.createdby", "system.changedby", "system.authorizedas", "system.owner", "system.requestedby"]:
        return "IdentityControl"
    if ref in ["system.createddate", "system.changeddate", "system.resolveddate", "system.closeddate"] or ft == "datetime":
        return "DateTimeControl"
    if ft == "boolean":
        return "BooleanControl"
    if ft == "html":
        return "HtmlFieldControl"
    if pick:
        if ft == "integer":
            return "PickListIntegerControl"
        return "PickListStringControl"
    if ft == "identity":
        return "IdentityControl"
    return "Field"

def add_control_if_missing(wit_ref_name: str, process_id: str, page_id: str, section_id: str, group_id: str,
                           field_ref_name: str, label: str, order: int,
                           field_type: Optional[str] = None, picklist_name: Optional[str] = None):
    log(f"[add_control_if_missing] Checking for control '{label}' ({field_ref_name}) "
        f"in group '{group_id}' on page '{page_id}' for '{wit_ref_name}'")

    if not section_id:
        log(f" ERROR: section_id is empty for page '{page_id}'. Cannot add control.")
        return

    layout = get_layout(wit_ref_name, process_id)
    if layout is None:
        log(f" Skipping control '{label}' on '{wit_ref_name}' because layout is unavailable")
        return
    
    found_group = False
    for page in layout.get("pages", []):
        if page.get("id") == page_id:
            for section in page.get("sections", []):
                if section.get("id") == section_id:
                    for group in section.get("groups", []):
                        if group.get("id") == group_id:
                            found_group = True
                            for control in group.get("controls", []):
                                if control.get("id") == field_ref_name:
                                    log(f" Control '{label}' ({field_ref_name}) already exists in group '{group_id}' on page '{page_id}'")
                                    return
                            break
    if not found_group:
        log(f" ERROR: group_id '{group_id}' not found in section '{section_id}' on page '{page_id}'.")
        return

    control_type = get_control_type(field_type, field_ref_name, picklist_name)
    payload = {
        "id": field_ref_name,
        "label": label,
        "order": order,
        "controlType": control_type,
        "visible": True,
        "inherited": True
    }

    enc_wit = urllib.parse.quote(wit_ref_name, safe='')
    enc_group = urllib.parse.quote(group_id, safe='')

    url = (f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}"
           f"/layout/groups/{enc_group}/controls"
           f"?api-version=7.1-preview.1")

    log(f" Creating control '{label}' ({field_ref_name}) in group '{group_id}' on page '{page_id}' "
        f"in section '{section_id}'")

    resp = make_request_with_retry('POST', url, headers=headers, json=payload)
    
    if resp.status_code in [200, 201]:
        invalidate_layout_cache(wit_ref_name)
        log(f" Added control '{label}' ({field_ref_name}) to group '{group_id}' on page '{page_id}' "
            f"in section '{section_id}' for '{wit_ref_name}'")
    elif resp.status_code == 409:
        log(f" Control '{label}' ({field_ref_name}) already exists in group '{group_id}' on page '{page_id}' "
            f"in section '{section_id}' for '{wit_ref_name}' (409 conflict)")
    else:
        body = resp.text
        log(f" ERROR: Failed to add control '{label}': {resp.status_code} - {body}")


def control_exists_on_page(layout: Optional[dict], page_id: str, field_ref_name: str) -> bool:
    if not layout:
        return False
    for page in layout.get("pages", []):
        if page.get("id") != page_id:
            continue
        for section in page.get("sections", []):
            for group in section.get("groups", []):
                for control in group.get("controls", []):
                    if control.get("id") == field_ref_name:
                        return True
    return False


def find_controls_on_page(layout: Optional[dict], page_id: str, control_id: str) -> list[tuple[str, str, dict]]:
    matches = []
    if not layout:
        return matches
    for page in layout.get("pages", []):
        if page.get("id") != page_id:
            continue
        for section in page.get("sections", []):
            section_id = section.get("id")
            for group in section.get("groups", []):
                group_id = group.get("id")
                for control in group.get("controls", []):
                    if control.get("id") == control_id:
                        matches.append((section_id, group_id, control))
    return matches


def remove_control_from_group(wit_ref_name: str, process_id: str, group_id: str, control_id: str) -> bool:
    enc_wit = urllib.parse.quote(wit_ref_name, safe='')
    enc_group = urllib.parse.quote(group_id, safe='')
    enc_control = urllib.parse.quote(control_id, safe='')
    url = (f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}"
           f"/layout/groups/{enc_group}/controls/{enc_control}?api-version=7.1-preview.1")
    resp = make_request_with_retry("DELETE", url, headers=headers)
    if resp.status_code in [200, 204]:
        invalidate_layout_cache(wit_ref_name)
        return True
    log(f" WARNING: Could not remove original control '{control_id}' from group '{group_id}': "
        f"{resp.status_code} - {resp.text}")
    return False


def add_multivalue_control_if_missing(wit_ref_name: str, process_id: str, page_id: str, section_id: str, group_id: str,
                                      field_ref_name: str, label: str, order: int) -> bool:
    if not multivalue_extension_available:
        log(f" SKIPPED: Multivalue control '{label}' ({field_ref_name}) because the extension is not available.")
        return False

    layout = get_layout(wit_ref_name, process_id, force_refresh=True)
    contribution_id = f"{field_ref_name}.multivalue"
    if control_exists_on_page(layout, page_id, contribution_id):
        log(f" Multivalue control '{label}' ({contribution_id}) already exists for '{wit_ref_name}'.")
        return True

    for _, original_group_id, control in find_controls_on_page(layout, page_id, field_ref_name):
        if not control.get("isContribution"):
            if remove_control_from_group(wit_ref_name, process_id, original_group_id, field_ref_name):
                log(f" Removed original field control '{label}' ({field_ref_name}) before adding multivalue control.")

    enc_wit = urllib.parse.quote(wit_ref_name, safe='')
    enc_group = urllib.parse.quote(group_id, safe='')
    url = (f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}"
           f"/layout/groups/{enc_group}/controls?api-version=7.1-preview.1")
    payload = {
        "id": contribution_id,
        "label": label,
        "order": order,
        "visible": True,
        "isContribution": True,
        "contribution": {
            "contributionId": MULTIVALUE_CONTRIBUTION_ID,
            "inputs": {
                "FieldName": field_ref_name
            },
            "height": 50
        },
        "height": 50
    }
    log(f" Creating multivalue control '{label}' ({contribution_id}) in group '{group_id}' for '{wit_ref_name}'")
    resp = make_request_with_retry("POST", url, headers=headers, json=payload)
    if resp.status_code in [200, 201]:
        invalidate_layout_cache(wit_ref_name)
        log(f" Added multivalue control '{label}' ({contribution_id}) for '{wit_ref_name}'.")
        return True
    if resp.status_code == 409:
        log(f" Multivalue control '{label}' already exists for '{wit_ref_name}' (409 conflict).")
        invalidate_layout_cache(wit_ref_name)
        return True

    log(f" ERROR: Failed to create multivalue control '{label}' ({contribution_id}): {resp.status_code} - {resp.text}")
    return False


def remove_empty_html_placeholder_groups(wit_ref_name: str, process_id: str, page_id: str, labels: set[str]) -> int:
    layout = get_layout(wit_ref_name, process_id, force_refresh=True)
    if not layout:
        return 0

    enc_wit = urllib.parse.quote(wit_ref_name, safe='')
    removed = 0
    for page in layout.get("pages", []):
        if page.get("id") != page_id:
            continue
        for section in page.get("sections", []):
            section_id = section.get("id")
            for group in list(section.get("groups", [])):
                group_id = group.get("id")
                group_label = safe_json_value(group.get("label"))
                controls = group.get("controls", [])
                if not group_id or group_label not in labels or controls:
                    continue

                enc_group = urllib.parse.quote(group_id, safe='')
                delete_url = (f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}"
                              f"/layout/pages/{page_id}/sections/{section_id}/groups/{enc_group}"
                              f"?api-version=7.1-preview.1")
                log(f" Removing empty HTML placeholder group '{group_label}' ({group_id}) from '{wit_ref_name}'.")
                delete_resp = make_request_with_retry('DELETE', delete_url, headers=headers)
                if delete_resp.status_code in [200, 204]:
                    removed += 1
                    invalidate_layout_cache(wit_ref_name)
                else:
                    log(f" WARNING: Could not remove empty HTML placeholder group '{group_label}': "
                        f"{delete_resp.status_code} - {delete_resp.text}")
    return removed


def add_html_control_as_own_group(wit_ref_name: str, process_id: str, page_id: str, section_id: str,
                                  field_ref_name: str, label: str, group_label: str,
                                  group_order: int, field_order: int) -> bool:
    """
    HTML controls cannot be added to an existing group. Azure DevOps requires a
    new group payload with a non-empty label and the HTML control included in
    the initial group create request.
    """
    html_group_label = group_label if group_label else label
    cleanup_labels = {label}
    if group_label:
        cleanup_labels.add(group_label)

    layout = get_layout(wit_ref_name, process_id)
    if control_exists_on_page(layout, page_id, field_ref_name):
        log(f" HTML control '{label}' ({field_ref_name}) already exists on page '{page_id}' for '{wit_ref_name}'.")
        if REMOVE_OLD_HTML_PLACEHOLDER_GROUPS:
            removed = remove_empty_html_placeholder_groups(wit_ref_name, process_id, page_id, cleanup_labels)
            if removed:
                log(f" Removed {removed} old empty placeholder group(s) for HTML control '{label}'.")
        return True

    enc_wit = urllib.parse.quote(wit_ref_name, safe='')
    url = (f"{ADO_ORG_URL}/_apis/work/processes/{process_id}/workItemTypes/{enc_wit}"
           f"/layout/pages/{page_id}/sections/{section_id}/groups"
           f"?api-version=7.1-preview.1")
    payload = {
        "label": html_group_label,
        "order": group_order,
        "visible": True,
        "inherited": True,
        "controls": [
            {
                "id": field_ref_name,
                "label": label,
                "order": field_order,
                "controlType": "HtmlFieldControl",
                "visible": True,
                "readOnly": False,
                "metadata": "",
                "watermark": "",
                "height": 250
            }
        ]
    }

    log(f" Creating HTML container group '{html_group_label}' with control '{label}' ({field_ref_name}) "
        f"on page '{page_id}' in section '{section_id}' for '{wit_ref_name}'")
    resp = make_request_with_retry('POST', url, headers=headers, json=payload)
    if resp.status_code in [200, 201]:
        invalidate_layout_cache(wit_ref_name)
        log(f" Added dedicated HTML control '{label}' ({field_ref_name}) for '{wit_ref_name}'.")
        return True
    if resp.status_code == 409:
        layout = get_layout(wit_ref_name, process_id, force_refresh=True)
        if control_exists_on_page(layout, page_id, field_ref_name):
            log(f" HTML control '{label}' ({field_ref_name}) already exists on '{wit_ref_name}' (409 conflict).")
            if REMOVE_OLD_HTML_PLACEHOLDER_GROUPS:
                removed = remove_empty_html_placeholder_groups(wit_ref_name, process_id, page_id, cleanup_labels)
                if removed:
                    log(f" Removed {removed} old empty placeholder group(s) for HTML control '{label}'.")
            return True
    log(f" ERROR: Failed to create dedicated HTML control '{label}' ({field_ref_name}): {resp.status_code} - {resp.text}")
    return False


def process_work_item_type(wit_row, process_id: str, field_labels: list, reference_names: dict, 
                           field_name_map: dict, field_types: dict, picklist_names: dict, required_flags: dict, 
                           default_values: dict, field_layout_map: dict, existing_fields: dict,
                           process_wit_map: dict) -> dict:
    """
    Process a single work item type - adds fields and updates layout.
    This function is designed to run in a separate thread.
    
    Returns:
        dict with 'wit_name', 'status', 'fields_added', 'errors'
    """
    result = {
        'wit_name': '',
        'status': 'success',
        'fields_added': 0,
        'errors': []
    }
    
    try:
        custom_type_flag = safe_json_value(wit_row.get("Custom work item type")).strip().lower()
        wit_name_raw = safe_json_value(wit_row.get("Work item type")).strip()
        wit_ref_name_excel = safe_json_value(wit_row.get("Reference name")).strip()
        
        result['wit_name'] = wit_name_raw
        
        wit_ref_name = resolve_process_wit_reference(wit_name_raw, wit_ref_name_excel, custom_type_flag, process_wit_map)
        wit_process_api_id = resolve_wit_process_api_identifier(wit_name_raw, wit_ref_name, process_wit_map)

        log(f"[Thread] Processing work item type: {wit_name_raw} (Reference: {wit_ref_name}, Process API ID: {wit_process_api_id})")

        # Get existing fields on the WIT
        encoded_wit_name = urllib.parse.quote(wit_name_raw, safe='')
        wit_fields_url = f"{ADO_ORG_URL}/{ADO_PROJECT}/_apis/wit/workitemtypes/{encoded_wit_name}/fields?api-version=7.0"
        wit_fields_resp = requests.get(wit_fields_url, headers=headers)
        wit_existing_fields = set()
        if wit_fields_resp.status_code == 200:
            wit_fields_json = wit_fields_resp.json()
            wit_existing_fields = set(f["referenceName"] for f in wit_fields_json.get("value", []))
        elif wit_fields_resp.status_code == 404:
            log(f" No fields found for work item type '{wit_ref_name}' in project '{ADO_PROJECT}' (404). Continuing with additions.")
        else:
            log(f" Failed to get fields for work item type '{wit_ref_name}': {wit_fields_resp.status_code}")
            result['status'] = 'error'
            result['errors'].append(f"Failed to get fields: {wit_fields_resp.status_code}")
            return result

        wit_field_flags = {label: safe_json_value(wit_row.get(label)).strip().upper() for label in field_labels}
        if all(flag != "X" for flag in wit_field_flags.values()):
            log(f" Skipping '{wit_name_raw}' — no fields flagged for addition.")
            result['status'] = 'skipped'
            return result

        # Loop through fields to add (using Label to match WIT sheet columns)
        for field_label in field_labels:
            if wit_field_flags.get(field_label) != "X":
                continue
            field_layout_info = field_layout_map.get(field_label)
            if not field_layout_info:
                log(f" WARNING: No layout metadata for field '{field_label}'. Skipping layout update.")
                continue

            ref_name = normalize_reference_name(reference_names.get(field_label))
            field_name = field_name_map.get(field_label)  # MS BPC-suffixed name
            field_type = safe_json_value(field_types.get(field_label)).strip()
            picklist_name = safe_json_value(picklist_names.get(field_label)) if picklist_names else ""
            required = parse_required(required_flags.get(field_label)) if required_flags else False
            default_value = parse_default_value(default_values.get(field_label)) if default_values else ""
            is_multivalue = safe_json_value(field_layout_info.get("Multi-select field")).strip().lower() in ("yes", "true", "1", "x")
            effective_field_type = field_type.strip().lower()
            existing_field_obj = existing_fields.get(ref_name)
            if not existing_field_obj:
                for key, value in existing_fields.items():
                    if key.casefold() == ref_name.casefold():
                        existing_field_obj = value
                        ref_name = value.get("referenceName", ref_name)
                        break
            if existing_field_obj and not effective_field_type:
                effective_field_type = str(existing_field_obj.get("type") or "").strip().lower()
                field_type = effective_field_type
            if effective_field_type in ("boolean", "bool") and str(default_value).strip() == "":
                default_value = False

            # Ensure field exists at org level
            field_exists = existing_field_obj is not None or any(key.casefold() == ref_name.casefold() for key in existing_fields.keys())
            if not field_exists:
                log(f" ERROR: Field '{field_label}' (name: {field_name}, ref: {ref_name}) does not exist at organization level. Cannot add to WIT '{wit_ref_name}'.")
                result['errors'].append(f"Field '{field_label}' not at org level")
                continue

            # Add field to WIT if not present
            if ref_name in wit_existing_fields or any(existing.casefold() == ref_name.casefold() for existing in wit_existing_fields):
                log(f" Field '{field_label}' (name: {field_name}, ref: {ref_name}) already exists on WIT '{wit_ref_name}'. Skipping field addition.")
            else:
                is_boolean = effective_field_type in ("boolean", "bool")
                if is_boolean:
                    payload = build_boolean_field_payload(ref_name, required=required, default_value=default_value)
                else:
                    payload = {
                        "referenceName": ref_name,
                        "required": required,
                        "visible": True
                    }
                    if effective_field_type == "identity":
                        payload["allowGroups"] = True
                    if default_value is not None and str(default_value) != "":
                        payload["defaultValue"] = default_value

                add_resp = add_field_to_wit(wit_ref_name, wit_process_api_id, process_id, payload, field_label, field_name, process_wit_map, is_boolean=is_boolean)
                if add_resp.status_code in [200, 201]:
                    log(f" Successfully added field '{field_label}' (name: {field_name}, ref: {ref_name}) to '{wit_ref_name}'.")
                    wit_existing_fields.add(ref_name)
                    result['fields_added'] += 1
                else:
                    log(f" ERROR: Failed to add field '{field_label}' (name: {field_name}, ref: {ref_name}) to '{wit_ref_name}': {add_resp.status_code} - {add_resp.text}")
                    result['errors'].append(f"Failed to add field '{field_label}'")
                    continue

            # === Layout update section ===
            with layout_cache_lock:
                if wit_ref_name in locked_layout_wits:
                    log(f" Skipping layout updates for '{wit_ref_name}' because its layout is locked.")
                    continue
            
            if field_type.lower() == "html" and not ADD_HTML_LAYOUT_CONTROLS:
                log(f" SKIPPED: HTML field '{field_label}' ({ref_name}) because BPC_ADO_ADD_HTML_LAYOUT_CONTROLS is disabled.")
                continue
            
            page_name = safe_json_value(field_layout_info["Page name"])
            group_sequence = int(field_layout_info["Group sequence"]) if not pd.isna(field_layout_info["Group sequence"]) else 1
            group_name = safe_json_value(field_layout_info["Group name"])
            field_sequence = int(field_layout_info["Field sequence"]) if not pd.isna(field_layout_info["Field sequence"]) else 1
            section_label_raw = safe_json_value(field_layout_info["Group location"])

            # 1) Ensure page exists
            layout = get_layout(wit_ref_name, process_id)
            if layout is None:
                with layout_cache_lock:
                    locked_layout_wits.add(wit_ref_name)
                continue
            page = find_page_by_label(layout, page_name)
            page_id = page.get("id") if page else None
            if not page_id:
                page_id = add_page_if_missing(wit_ref_name, process_id, page_name, group_sequence)
            if not page_id:
                log(f" ERROR: Could not resolve or create page '{page_name}' for WIT '{wit_ref_name}'.")
                result['errors'].append(f"Could not create page '{page_name}'")
                continue

            # 2) Resolve section id
            layout = get_layout(wit_ref_name, process_id)
            if layout is None:
                with layout_cache_lock:
                    locked_layout_wits.add(wit_ref_name)
                continue
            section_id = get_section_id(layout, page_id, section_label=section_label_raw)
            if not section_id:
                log(f" ERROR: Could not resolve section for label '{section_label_raw}' on page '{page_name}'.")
                result['errors'].append(f"Could not resolve section '{section_label_raw}'")
                continue

            if field_type.lower() == "html":
                if add_html_control_as_own_group(
                    wit_ref_name, process_id, page_id, section_id,
                    ref_name, field_label, group_name,
                    group_sequence, field_sequence
                ):
                    continue
                result['errors'].append(f"Failed to add HTML control '{field_label}'")
                continue
           
            # 3) Check if group exists
            existing_group = ensure_group_on_page(layout, page_id, group_name)
            if existing_group:
                group_id, actual_section_id = existing_group
                if actual_section_id and actual_section_id != section_id:
                    log(f" WARNING: Group '{group_name}' exists in section '{actual_section_id}' instead of target section '{section_id}'.")
                    section_id = actual_section_id
                elif not actual_section_id:
                    group_id = add_group_if_missing(wit_ref_name, process_id, page_id, section_id, group_name)
                    if not group_id:
                        log(f" ERROR: Could not create group '{group_name}'.")
                        result['errors'].append(f"Could not create group '{group_name}'")
                        continue
            else:
                group_id = add_group_if_missing(wit_ref_name, process_id, page_id, section_id, group_name)
                if not group_id:
                    log(f" ERROR: Could not create group '{group_name}'.")
                    result['errors'].append(f"Could not create group '{group_name}'")
                    continue

            # 4) Add control to the group — use Label for form display
            if is_multivalue:
                if ADD_MULTIVALUE_CONTROLS:
                    if add_multivalue_control_if_missing(
                        wit_ref_name, process_id, page_id, section_id, group_id,
                        ref_name, field_label, field_sequence
                    ):
                        continue
                    result['errors'].append(f"Failed to add multivalue control '{field_label}'")
                    continue
                log(f" SKIPPED: Multivalue control '{field_label}' ({ref_name}) because BPC_ADO_ADD_MULTIVALUE_CONTROLS is disabled.")
                continue

            add_control_if_missing(
                wit_ref_name, process_id, page_id, section_id, group_id,
                ref_name, field_label, field_sequence,
                field_type=field_type, picklist_name=picklist_name
            )

        log(f"[Thread] Finished processing WIT '{wit_name_raw}'")
        
    except Exception as e:
        result['status'] = 'error'
        result['errors'].append(str(e))
        log(f"[Thread] ERROR processing WIT: {e}")
    
    return result


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


# === Main flow ===
def main():
    start_time = time.time()
    
    log("=" * 60)
    log("Starting MULTITHREADED Azure DevOps script")
    log(f"Max parallel workers: {MAX_WORKERS}")
    log("=" * 60)
    
    log(f"Looking up process: {PROCESS_NAME}")
    process_id = get_process_id_by_name(PROCESS_NAME)
    log(f"Found process ID: {process_id}")
    
    log(f"Reading spreadsheet: {EXCEL_FILE}")

    # Read Excel sheets
    wit_df = pd.read_excel(excel_path, sheet_name="Work item types")
    wit_df.columns = wit_df.columns.str.strip()
    df = pd.read_excel(excel_path, sheet_name="Fields")
    df.columns = df.columns.str.strip()

    # Sort Fields sheet
    sort_columns = []
    if "Page name" in df.columns:
        sort_columns.append("Page name")
    if "Group location" in df.columns:
        sort_columns.append("Group location")
    if "Group sequence" in df.columns:
        sort_columns.append("Group sequence")
    if "Field sequence" in df.columns:
        sort_columns.append("Field sequence")

    if sort_columns:
        df = df.sort_values(sort_columns)
        log(f"Sorted Fields sheet by: {', '.join(sort_columns)}")

    has_multivalue_fields = (
        "Multi-select field" in df.columns
        and df["Multi-select field"].fillna("").astype(str).str.strip().str.lower().isin(["yes", "true", "1", "x"]).any()
    )
    if has_multivalue_fields and ADD_MULTIVALUE_CONTROLS:
        log("Detected multivalue fields in the Excel template. Checking extension once before processing work item types.")
        ensure_multivalue_extension_installed()
    elif has_multivalue_fields:
        log("Detected multivalue fields, but BPC_ADO_ADD_MULTIVALUE_CONTROLS is disabled.")

    # Get existing organization fields
    fields_url = f"{ADO_ORG_URL}/_apis/wit/fields?api-version=7.0"
    fields_response = requests.get(fields_url, headers=headers)
    if fields_response.status_code == 200:
        fields_json = fields_response.json()
        existing_fields = {field["referenceName"]: field for field in fields_json.get("value", [])}
        log(f"Retrieved {len(existing_fields)} organization fields.")
    else:
        log(f"Failed to get organization fields: {fields_response.status_code} - {fields_response.text}")
        existing_fields = {}

    # Get all picklists
    picklists_url = f"{ADO_ORG_URL}/_apis/work/processes/lists?api-version=7.0"
    picklists_response = requests.get(picklists_url, headers=headers)
    if picklists_response.status_code == 200:
        log(f"Retrieved {len(picklists_response.json().get('value', []))} picklists.")
    else:
        log(f"Failed to get picklists: {picklists_response.status_code} - {picklists_response.text}")

    # Build lookups from Fields sheet, keyed by Label (matches WIT sheet column headers)
    field_labels = df["Label"].tolist()
    missing_wit_columns = [label for label in field_labels if label not in wit_df.columns]
    if missing_wit_columns:
        preview = ", ".join(str(label) for label in missing_wit_columns[:20])
        suffix = "..." if len(missing_wit_columns) > 20 else ""
        log(
            f" WARNING: {len(missing_wit_columns)} field label(s) from the Fields sheet do not have matching "
            f"columns in the Work item types sheet: {preview}{suffix}. These fields will not be added to any WIT "
            "unless the Work item types sheet has a matching column with X values."
        )
    reference_names = df.set_index("Label")["Reference name"].to_dict()
    field_name_map = df.set_index("Label")["Field name"].to_dict()  # Label -> Field name (MS BPC-suffixed)
    field_types = df.set_index("Label")["Field type"].to_dict()
    picklist_names = df.set_index("Label")["Picklist name"].to_dict() if "Picklist name" in df.columns else {}
    required_flags = df.set_index("Label")["Required"].to_dict() if "Required" in df.columns else {}
    default_values = df.set_index("Label")["Default value"].to_dict() if "Default value" in df.columns else {}

    if df["Label"].duplicated().any():
        dupes = df[df["Label"].duplicated() == True]["Label"].unique()
        dupes_str = ", ".join(str(name) for name in dupes)
        log(f" WARNING: Duplicate layout rows found for labels: {dupes_str}. Using the first occurrence of each.")
    layout_rows = df.drop_duplicates(subset="Label", keep="first")
    field_layout_map = layout_rows.set_index("Label").to_dict(orient="index")
    process_wit_map = get_process_work_item_type_map(process_id)

    # Clear caches
    with layout_cache_lock:
        layout_cache.clear()
        locked_layout_wits.clear()

    # Prepare work item types for parallel processing
    wit_rows = [row for _, row in wit_df.iterrows()]
    total_wits = len(wit_rows)
    log(f"Processing {total_wits} work item types with {MAX_WORKERS} parallel workers...")

    # Process work item types in parallel
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        future_to_wit = {
            executor.submit(
                process_work_item_type,
                wit_row, process_id, field_labels, reference_names,
                field_name_map, field_types, picklist_names, required_flags,
                default_values, field_layout_map, existing_fields, process_wit_map
            ): wit_row for wit_row in wit_rows
        }
        
        # Collect results as they complete
        completed = 0
        for future in as_completed(future_to_wit):
            completed += 1
            try:
                result = future.result()
                results.append(result)
                log(f"Progress: {completed}/{total_wits} work item types processed")
            except Exception as e:
                log(f"ERROR: Thread raised exception: {e}")
                results.append({'wit_name': 'Unknown', 'status': 'error', 'errors': [str(e)]})

    # Summary
    elapsed_time = time.time() - start_time
    log("=" * 60)
    log("SUMMARY")
    log("=" * 60)
    
    successful = sum(1 for r in results if r['status'] == 'success')
    skipped = sum(1 for r in results if r['status'] == 'skipped')
    failed = sum(1 for r in results if r['status'] == 'error')
    total_fields_added = sum(r.get('fields_added', 0) for r in results)
    
    log(f"Total work item types: {total_wits}")
    log(f"  Successful: {successful}")
    log(f"  Skipped: {skipped}")
    log(f"  Failed: {failed}")
    log(f"Total fields added: {total_fields_added}")
    log(f"Elapsed time: {elapsed_time:.2f} seconds ({elapsed_time/60:.2f} minutes)")
    log("=" * 60)
    
    if failed > 0:
        log("Failed work item types:")
        for r in results:
            if r['status'] == 'error':
                log(f"  - {r['wit_name']}: {', '.join(r['errors'])}")
    
    log("Script finished. See log file for details:")
    log(f"  {LOG_FILE}")


if __name__ == "__main__":
    log(f"Starting Script 2. Log file: {LOG_FILE}")
    main()
