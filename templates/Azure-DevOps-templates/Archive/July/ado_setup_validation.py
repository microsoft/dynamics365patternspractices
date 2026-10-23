import base64
import re
import urllib.parse
from typing import Dict, Iterable, List, Set

import pandas as pd
import requests

from ado_setup_config import AdoSetupConfig


def _headers(config: AdoSetupConfig) -> Dict[str, str]:
    token = base64.b64encode(f":{config.pat}".encode("utf-8")).decode("utf-8")
    return {"Content-Type": "application/json", "Authorization": f"Basic {token}"}


def _get_json(config: AdoSetupConfig, url: str) -> dict:
    response = requests.get(url, headers=_headers(config), timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(f"Validation request failed: {response.status_code} - {response.text}")
    return response.json()


def _build_reference_name(wit_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(wit_name))
    return f"Custom.{cleaned}"


def _lookup_keys(value: object) -> Set[str]:
    text = "" if value is None or pd.isna(value) else str(value).strip()
    if not text:
        return set()
    compact = re.sub(r"[\s_\-]+", "", text)
    short = text.rsplit(".", 1)[-1] if "." in text else text
    short_compact = re.sub(r"[\s_\-]+", "", short)
    return {text.casefold(), compact.casefold(), short.casefold(), short_compact.casefold()}


def _build_wit_lookup(wits: Iterable[dict]) -> Set[str]:
    lookup = set()
    for wit in wits:
        for value in (wit.get("referenceName"), wit.get("name")):
            lookup.update(_lookup_keys(value))
    return lookup


def _process_id(config: AdoSetupConfig) -> str:
    url = f"{config.ado_org_url}/_apis/work/processes?api-version=7.1-preview.2"
    for process in _get_json(config, url).get("value", []):
        if process.get("name") == config.process_name:
            return process.get("typeId", "")
    raise RuntimeError(f"Process '{config.process_name}' was not found.")


def _project_id(config: AdoSetupConfig) -> str:
    project = urllib.parse.quote(config.ado_project, safe="")
    url = f"{config.ado_org_url}/_apis/projects/{project}?api-version=7.1"
    project_json = _get_json(config, url)
    project_id = project_json.get("id")
    if not project_id:
        raise RuntimeError(f"Project '{config.ado_project}' was found but did not include an ID.")
    return project_id


def _sheet(config: AdoSetupConfig, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(config.excel_file, sheet_name=sheet_name)


def _clean_values(values: Iterable[object]) -> Set[str]:
    result = set()
    for value in values:
        if pd.notna(value):
            text = str(value).strip()
            if text:
                result.add(text)
    return result


def _print_result(title: str, errors: List[str], warnings: List[str]) -> None:
    print()
    print(f"Validation: {title}")
    if not errors and not warnings:
        print("  Passed.")
        return
    for warning in warnings:
        print(f"  WARNING: {warning}")
    for error in errors:
        print(f"  ERROR: {error}")


def _validate_phase_1(config: AdoSetupConfig) -> None:
    errors: List[str] = []
    warnings: List[str] = []
    process_id = _process_id(config)
    _project_id(config)

    wit_url = f"{config.ado_org_url}/_apis/work/processes/{process_id}/workitemtypes?api-version=7.1-preview.2"
    existing_wit_items = _get_json(config, wit_url).get("value", [])
    existing_wits = _build_wit_lookup(existing_wit_items)

    wit_df = _sheet(config, "Work item types")
    expected_wits = set()
    for _, row in wit_df.iterrows():
        wit_name = str(row.get("Work item type", "")).strip()
        if not wit_name:
            continue
        reference_name = str(row.get("Reference name", "")).strip()
        custom_flag = str(row.get("Custom work item type", "")).strip().lower()
        if custom_flag == "disabled":
            continue
        expected_wits.update(_lookup_keys(reference_name or _build_reference_name(wit_name)))
        expected_wits.update(_lookup_keys(wit_name))

    missing_wits = sorted(key for key in expected_wits if key not in existing_wits)
    if missing_wits:
        warnings.append("Some expected work item types were not found through the process API: " + ", ".join(missing_wits[:10]))

    fields_df = _sheet(config, "Fields")
    expected_fields = _clean_values(fields_df.get("Reference name", []))
    fields_url = f"{config.ado_org_url}/_apis/wit/fields?api-version=7.1"
    existing_fields = {item.get("referenceName", "") for item in _get_json(config, fields_url).get("value", [])}
    missing_fields = sorted(expected_fields - existing_fields)
    if missing_fields:
        warnings.append("Some expected fields were not found through the fields API: " + ", ".join(missing_fields[:10]))

    _print_result("phase 1 process, project, work item types, and fields", errors, warnings)
    if errors:
        raise RuntimeError("Phase 1 validation failed.")


def _validate_phase_2(config: AdoSetupConfig) -> None:
    errors: List[str] = []
    warnings: List[str] = []
    process_id = _process_id(config)
    wit_url = f"{config.ado_org_url}/_apis/work/processes/{process_id}/workitemtypes?api-version=7.1-preview.2"
    existing_wits = [item for item in _get_json(config, wit_url).get("value", []) if item.get("referenceName")]
    if not existing_wits:
        errors.append("No work item types were returned for the configured process.")
    else:
        first_ref = existing_wits[0]["referenceName"]
        layout_url = (
            f"{config.ado_org_url}/_apis/work/processes/{process_id}/workItemTypes/"
            f"{urllib.parse.quote(first_ref, safe='')}/layout?api-version=7.1-preview.1"
        )
        layout = _get_json(config, layout_url)
        if not layout.get("pages"):
            warnings.append("A sample work item type layout was returned without pages.")

    _print_result("phase 2 page layout API accessibility", errors, warnings)
    if errors:
        raise RuntimeError("Phase 2 validation failed.")


def _validate_phase_3(config: AdoSetupConfig) -> None:
    errors: List[str] = []
    warnings: List[str] = []
    project_id = _project_id(config)
    area_df = _sheet(config, "Area paths")
    expected_teams = _clean_values(area_df.get("Teams", []))

    teams_url = f"{config.ado_org_url}/_apis/projects/{project_id}/teams?api-version=7.1"
    existing_teams = {team.get("name", "") for team in _get_json(config, teams_url).get("value", [])}
    missing_teams = sorted(expected_teams - existing_teams)
    if missing_teams:
        warnings.append("Some expected teams were not found: " + ", ".join(missing_teams[:10]))

    project = urllib.parse.quote(config.ado_project, safe="")
    areas_url = f"{config.ado_org_url}/{project}/_apis/wit/classificationnodes/Areas?$depth=10&api-version=7.1"
    areas = _get_json(config, areas_url)
    if not areas:
        errors.append("Area path tree could not be read.")

    _print_result("phase 3 teams and area paths", errors, warnings)
    if errors:
        raise RuntimeError("Phase 3 validation failed.")


def _validate_phase_4(config: AdoSetupConfig) -> None:
    errors: List[str] = []
    warnings: List[str] = []
    process_id = _process_id(config)
    _project_id(config)

    behaviors_url = f"{config.ado_org_url}/_apis/work/processes/{process_id}/behaviors?api-version=7.1-preview.2"
    behaviors = _get_json(config, behaviors_url).get("value", [])
    if not behaviors:
        errors.append("No backlog behaviors were returned for the configured process.")

    project = urllib.parse.quote(config.ado_project, safe="")
    iterations_url = f"{config.ado_org_url}/{project}/_apis/wit/classificationnodes/Iterations?$depth=10&api-version=7.1"
    iterations = _get_json(config, iterations_url)
    if not iterations:
        warnings.append("Iteration path tree was empty or could not be confirmed.")

    _print_result("phase 4 backlogs, iterations, and team settings", errors, warnings)
    if errors:
        raise RuntimeError("Phase 4 validation failed.")


def validate_phase(phase_number: int, config: AdoSetupConfig) -> None:
    validators = {
        1: _validate_phase_1,
        2: _validate_phase_2,
        3: _validate_phase_3,
        4: _validate_phase_4,
    }
    validator = validators.get(phase_number)
    if validator:
        validator(config)
