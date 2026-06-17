from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote, urlparse

import requests


@dataclass(frozen=True)
class ProjectUrl:
    organization_url: str
    project: str


def parse_project_url(value: str) -> ProjectUrl:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid Azure DevOps project URL: {value}")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("Project URL must look like https://dev.azure.com/{org}/{project}/")
    return ProjectUrl(f"{parsed.scheme}://{parsed.netloc}/{unquote(parts[0])}", unquote(parts[1]))


class AzureDevOpsClient:
    def __init__(self, project_url: str, pat: str, api_version: str = "7.1") -> None:
        self.project = parse_project_url(project_url)
        token = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Basic {token}"})
        self.api_version = api_version

    def _url(self, path: str) -> str:
        return f"{self.project.organization_url}/{quote(self.project.project)}/{path}"

    def get_fields(self) -> set[str]:
        url = self._url(f"_apis/wit/fields?api-version={self.api_version}")
        data = self._request("GET", url).json()
        return {f["referenceName"] for f in data.get("value", [])}

    def get_work_item_types(self) -> set[str]:
        url = self._url(f"_apis/wit/workitemtypes?api-version={self.api_version}")
        data = self._request("GET", url).json()
        return {w["name"] for w in data.get("value", [])}

    def get_work_item_type_references(self) -> dict[str, str]:
        url = self._url(f"_apis/wit/workitemtypes?api-version={self.api_version}")
        data = self._request("GET", url).json()
        refs: dict[str, str] = {}
        for wit in data.get("value", []):
            name = str(wit.get("name") or "").strip()
            reference_name = str(wit.get("referenceName") or "").strip()
            if not name or not reference_name:
                continue
            refs[name] = reference_name
            refs[reference_name] = reference_name
        return refs

    def ensure_classification_path(self, structure_group: str, tree_path: str) -> None:
        parts = [p for p in tree_path.split("\\") if p]
        if not parts:
            return
        if parts[0].lower() == self.project.project.lower():
            parts = parts[1:]
        parent_parts: list[str] = []
        for name in parts:
            current_parts = parent_parts + [name]
            if not self._classification_exists(structure_group, current_parts):
                self._create_classification_node(structure_group, parent_parts, name)
            parent_parts = current_parts

    def _classification_exists(self, structure_group: str, parts: list[str]) -> bool:
        path = "/".join(quote(p, safe="") for p in parts)
        url = self._url(f"_apis/wit/classificationnodes/{structure_group}/{path}?api-version={self.api_version}")
        response = self.session.get(url, timeout=60)
        if response.status_code == 404:
            return False
        if response.status_code >= 400:
            raise RuntimeError(f"ADO GET failed ({response.status_code}): {response.text}")
        return True

    def _create_classification_node(self, structure_group: str, parent_parts: list[str], name: str) -> None:
        parent_path = "/".join(quote(p, safe="") for p in parent_parts)
        suffix = f"/{parent_path}" if parent_path else ""
        url = self._url(f"_apis/wit/classificationnodes/{structure_group}{suffix}?api-version={self.api_version}")
        self._request("POST", url, json={"name": name})

    def create_work_item(
        self,
        work_item_type: str,
        fields: dict[str, Any],
        parent_id: int | None = None,
        dry_run: bool = False,
        max_retries: int = 3,
        retry_delay_seconds: float = 5,
        recovery_field: str = "MSBPC.microsoftid",
    ) -> dict[str, Any]:
        patch: list[dict[str, Any]] = []
        for ref, value in fields.items():
            if value is not None and value != "":
                patch.append({"op": "add", "path": f"/fields/{ref}", "value": value})
        if parent_id:
            parent_url = self._url(f"_apis/wit/workItems/{parent_id}")
            patch.append(
                {
                    "op": "add",
                    "path": "/relations/-",
                    "value": {
                        "rel": "System.LinkTypes.Hierarchy-Reverse",
                        "url": parent_url,
                        "attributes": {"comment": "Imported parent link"},
                    },
                }
            )
        if dry_run:
            return {"id": None, "workItemType": work_item_type, "patch": patch}
        url = self._url(f"_apis/wit/workitems/${quote(work_item_type)}?api-version={self.api_version}")
        attempts = max(1, max_retries + 1)
        for attempt in range(1, attempts + 1):
            try:
                return self._request(
                    "PATCH",
                    url,
                    retry_transient=False,
                    json=patch,
                    headers={"Content-Type": "application/json-patch+json"},
                ).json()
            except requests.RequestException as exc:
                if not _is_transient_exception(exc) or attempt == attempts:
                    raise
                recovered = self.find_work_item_id(work_item_type, recovery_field, fields.get(recovery_field))
                if recovered:
                    return {"id": recovered, "recovered": True}
                time.sleep(retry_delay_seconds * attempt)
                recovered = self.find_work_item_id(work_item_type, recovery_field, fields.get(recovery_field))
                if recovered:
                    return {"id": recovered, "recovered": True}
            except RuntimeError as exc:
                if not _is_transient_runtime_error(str(exc)) or attempt == attempts:
                    raise
                recovered = self.find_work_item_id(work_item_type, recovery_field, fields.get(recovery_field))
                if recovered:
                    return {"id": recovered, "recovered": True}
                time.sleep(retry_delay_seconds * attempt)
        raise RuntimeError("ADO create failed after retry loop")

    def find_work_item_id(self, work_item_type: str, field_ref: str, value: Any) -> int | None:
        if not field_ref or value in (None, ""):
            return None
        field_value = _wiql_quote(str(value))
        type_value = _wiql_quote(work_item_type)
        query = (
            "SELECT [System.Id] FROM WorkItems "
            f"WHERE [System.TeamProject] = @project "
            f"AND [System.WorkItemType] = '{type_value}' "
            f"AND [{field_ref}] = '{field_value}'"
        )
        url = self._url(f"_apis/wit/wiql?api-version={self.api_version}")
        data = self._request("POST", url, json={"query": query}).json()
        items = data.get("workItems", [])
        if len(items) == 1:
            return int(items[0]["id"])
        return None

    def get_parent_id(self, work_item_id: int) -> int | None:
        url = self._url(f"_apis/wit/workItems/{work_item_id}?$expand=Relations&api-version={self.api_version}")
        data = self._request("GET", url).json()
        for relation in data.get("relations", []) or []:
            if relation.get("rel") == "System.LinkTypes.Hierarchy-Reverse":
                return int(str(relation.get("url", "")).rstrip("/").split("/")[-1])
        return None

    def add_parent_link(self, child_id: int, parent_id: int, dry_run: bool = False) -> dict[str, Any]:
        patch = [
            {
                "op": "add",
                "path": "/relations/-",
                "value": {
                    "rel": "System.LinkTypes.Hierarchy-Reverse",
                    "url": self._url(f"_apis/wit/workItems/{parent_id}"),
                    "attributes": {"comment": "Backfilled imported parent link"},
                },
            }
        ]
        if dry_run:
            return {"id": child_id, "parentId": parent_id, "patch": patch}
        url = self._url(f"_apis/wit/workItems/{child_id}?api-version={self.api_version}")
        return self._request(
            "PATCH",
            url,
            json=patch,
            headers={"Content-Type": "application/json-patch+json"},
        ).json()

    def update_work_item_fields(self, work_item_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        patch = [
            {"op": "add", "path": f"/fields/{ref}", "value": value}
            for ref, value in fields.items()
            if value is not None and value != ""
        ]
        url = self._url(f"_apis/wit/workItems/{work_item_id}?api-version={self.api_version}")
        return self._request(
            "PATCH",
            url,
            json=patch,
            headers={"Content-Type": "application/json-patch+json"},
        ).json()

    def _request(self, method: str, url: str, retry_transient: bool = True, **kwargs: Any) -> requests.Response:
        attempts = 4 if retry_transient else 1
        for attempt in range(1, attempts + 1):
            try:
                response = self.session.request(method, url, timeout=60, **kwargs)
            except requests.RequestException:
                if not retry_transient or attempt == attempts:
                    raise
                time.sleep(2 * attempt)
                continue
            if response.status_code < 400:
                return response
            if retry_transient and _is_transient_status(response.status_code) and attempt < attempts:
                time.sleep(_retry_after_seconds(response) or 2 * attempt)
                continue
            raise RuntimeError(f"ADO {method} failed ({response.status_code}): {response.text}")
        raise RuntimeError(f"ADO {method} failed after retry loop")


def _is_transient_status(status_code: int) -> bool:
    return status_code == 408 or status_code == 429 or 500 <= status_code <= 599


def _is_transient_exception(exc: BaseException) -> bool:
    return isinstance(
        exc,
        (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    )


def _is_transient_runtime_error(message: str) -> bool:
    return re.search(r"[\s(](408|429|500|502|503|504)[\s):]", message) is not None


def _retry_after_seconds(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _wiql_quote(value: str) -> str:
    return value.replace("'", "''")
