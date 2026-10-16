"""Azure DevOps REST client used by apply writers."""

from __future__ import annotations

import base64
import http.client
import json
import random
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import getproxies, proxy_bypass

from .org_url import normalize_ado_org_url, parse_ado_org_url

USER_AGENT = "BPCTool-runner (python http.client)"
REQUEST_TIMEOUT_S = 120
# Azure front doors drop idle keep-alive sockets after a few minutes.
IDLE_RECONNECT_S = 60.0
MAX_RETRY_DELAY_S = 60.0

# Statuses where ADO did not process the request, so any method may be retried.
_REJECTED_STATUSES = {429, 503}
# Additional statuses retried only for idempotent calls (request may have run).
_IDEMPOTENT_RETRY_STATUSES = {500, 502, 504}


class AdoError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        transient: bool = False,
        outcome_unknown: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.transient = transient
        self.outcome_unknown = outcome_unknown


def _proxy_for(scheme: str, host: str) -> Any:
    """Proxy URL for a target, honouring *_PROXY / NO_PROXY and macOS system settings."""
    proxy = getproxies().get(scheme)
    if not proxy or proxy_bypass(host):
        return None
    return urlsplit(proxy if "://" in proxy else f"http://{proxy}")


class _ConnectionPool:
    """Per-thread keep-alive HTTP(S) connections keyed by scheme + host."""

    def __init__(self, timeout: float) -> None:
        self._timeout = timeout
        self._local = threading.local()

    def _conns(self) -> dict[tuple[str, str], list[Any]]:
        conns = getattr(self._local, "conns", None)
        if conns is None:
            conns = self._local.conns = {}
        return conns

    def get(
        self, scheme: str, netloc: str
    ) -> tuple[http.client.HTTPConnection, dict[str, str] | None]:
        """Return (connection, proxy headers when requests go via a plain-HTTP proxy).

        A non-None second value means the request target must be the absolute URL.
        """
        conns = self._conns()
        key = (scheme, netloc)
        entry = conns.get(key)
        now = time.monotonic()
        if entry is not None and now - entry[2] > IDLE_RECONNECT_S:
            self.discard(scheme, netloc)
            entry = None
        if entry is None:
            conn, http_proxy_headers = self._open(scheme, netloc)
            entry = [conn, http_proxy_headers, now]
            conns[key] = entry
        entry[2] = now
        return entry[0], entry[1]

    def _open(
        self, scheme: str, netloc: str
    ) -> tuple[http.client.HTTPConnection, dict[str, str] | None]:
        target = urlsplit(f"{scheme}://{netloc}")
        proxy = _proxy_for(scheme, target.hostname or netloc)
        if proxy is None or not proxy.hostname:
            cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
            return cls(netloc, timeout=self._timeout), None
        proxy_port = proxy.port or (443 if proxy.scheme == "https" else 80)
        proxy_headers: dict[str, str] = {}
        if proxy.username:
            credentials = f"{unquote(proxy.username)}:{unquote(proxy.password or '')}"
            proxy_headers["Proxy-Authorization"] = (
                "Basic " + base64.b64encode(credentials.encode("utf-8")).decode("ascii")
            )
        if scheme == "https":
            conn = http.client.HTTPSConnection(proxy.hostname, proxy_port, timeout=self._timeout)
            conn.set_tunnel(target.hostname or netloc, target.port or 443, headers=proxy_headers)
            return conn, None
        conn = http.client.HTTPConnection(proxy.hostname, proxy_port, timeout=self._timeout)
        return conn, proxy_headers

    def discard(self, scheme: str, netloc: str) -> None:
        entry = self._conns().pop((scheme, netloc), None)
        if entry is not None:
            try:
                entry[0].close()
            except OSError:
                pass


def retry_delay_seconds(retry_after: str | None, attempt: int) -> float:
    """Honor Retry-After (seconds or HTTP-date); else jittered exponential backoff."""
    if retry_after:
        value = retry_after.strip()
        try:
            return min(MAX_RETRY_DELAY_S, max(0.0, float(value)))
        except ValueError:
            pass
        try:
            when = parsedate_to_datetime(value)
            return min(MAX_RETRY_DELAY_S, max(0.0, when.timestamp() - time.time()))
        except (TypeError, ValueError, OverflowError):
            pass
    base = min(30.0, 1.5 * (2**attempt))
    return base * (0.75 + random.random() * 0.5)


def _wiql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class AdoClient:
    def __init__(self, org_url: str, pat: str, *, api_version: str = "7.1") -> None:
        parsed = parse_ado_org_url(org_url)
        if not parsed.ok:
            raise ValueError(parsed.error)
        if not pat or len(pat.strip()) < 20:
            raise ValueError("PAT is required and should be at least 20 characters.")
        self.org = parsed.org
        self.organization_url = normalize_ado_org_url(org_url)
        token = base64.b64encode(f":{pat.strip()}".encode("utf-8")).decode("ascii")
        self._auth = f"Basic {token}"
        self.api_version = api_version
        self._pool = _ConnectionPool(REQUEST_TIMEOUT_S)

    def url(self, path: str, *, project: str | None = None, api_version: str | None = None) -> str:
        version = api_version or self.api_version
        clean = path if path.startswith("/") else f"/{path}"
        if project:
            # Allow "Project/Team" style paths used by teamsettings APIs.
            encoded_project = "/".join(quote(part, safe="") for part in project.split("/") if part)
            base = f"{self.organization_url}/{encoded_project}"
        else:
            base = self.organization_url
        sep = "&" if "?" in clean else "?"
        return f"{base}{clean}{sep}{urlencode({'api-version': version})}"

    def request(
        self,
        method: str,
        path: str,
        *,
        project: str | None = None,
        api_version: str | None = None,
        json_body: Any = None,
        content_type: str | None = None,
        retry_attempts: int = 5,
        absolute_url: str | None = None,
        idempotent: bool = True,
    ) -> Any:
        """Send a request with retries.

        ``idempotent=False`` (work item create) never retries after the request
        may have reached ADO: network errors raise ``outcome_unknown`` and only
        429/503 rejections are retried.
        """
        url = absolute_url or self.url(path, project=project, api_version=api_version)
        data = None
        headers = {
            "Authorization": self._auth,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = content_type or "application/json"

        retry_statuses = (
            _REJECTED_STATUSES | _IDEMPOTENT_RETRY_STATUSES if idempotent else _REJECTED_STATUSES
        )
        attempts = max(1, retry_attempts)
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                status, reason, retry_after, raw = self._send(method.upper(), url, data, headers)
            except (http.client.HTTPException, OSError) as exc:
                if not idempotent:
                    raise AdoError(
                        f"Network error talking to Azure DevOps (outcome unknown, not retried): {exc}",
                        transient=True,
                        outcome_unknown=True,
                    ) from exc
                if last:
                    raise AdoError(
                        f"Network error talking to Azure DevOps: {exc}", transient=True
                    ) from exc
                time.sleep(retry_delay_seconds(None, attempt))
                continue

            if status == 203:
                # ADO answers an invalid/expired PAT with a 203 HTML sign-in page.
                raise AdoError(
                    "Azure DevOps returned a sign-in page (HTTP 203): the PAT is invalid, "
                    "expired, or lacks the required scopes.",
                    status=401,
                )
            if 200 <= status < 300:
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))

            body = raw.decode("utf-8", errors="replace")[:500]
            transient = status in _REJECTED_STATUSES | _IDEMPOTENT_RETRY_STATUSES
            if status not in retry_statuses or last:
                raise AdoError(f"ADO {status} {reason}: {body}", status=status, transient=transient)
            time.sleep(retry_delay_seconds(retry_after, attempt))
        raise AdoError("ADO request failed after retries", transient=True)

    def _send(
        self, method: str, url: str, data: bytes | None, headers: dict[str, str]
    ) -> tuple[int, str, str | None, bytes]:
        parts = urlsplit(url)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        conn, http_proxy_headers = self._pool.get(parts.scheme, parts.netloc)
        if http_proxy_headers is not None:
            target = url
            headers = {**headers, **http_proxy_headers}
        try:
            conn.request(method, target, body=data, headers=headers)
            response = conn.getresponse()
            raw = response.read()
        except (http.client.HTTPException, OSError):
            self._pool.discard(parts.scheme, parts.netloc)
            raise
        if response.will_close:
            self._pool.discard(parts.scheme, parts.netloc)
        return response.status, response.reason, response.getheader("Retry-After"), raw

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json_body: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, json_body=json_body, **kwargs)

    # Microsoft DevLabs Multivalue control (Multi-select layout contribution).
    MULTIVALUE_PUBLISHER = "ms-devlabs"
    MULTIVALUE_EXTENSION = "vsts-extensions-multivalue-control"

    def extmgmt_url(self, path: str, *, api_version: str = "7.1-preview.1") -> str:
        clean = path if path.startswith("/") else f"/{path}"
        sep = "&" if "?" in clean else "?"
        return (
            f"https://extmgmt.dev.azure.com/{quote(self.org, safe='')}"
            f"{clean}{sep}{urlencode({'api-version': api_version})}"
        )

    def get_multivalue_extension_status(self) -> str:
        """Return installed | missing | disabled."""
        path = (
            "/_apis/extensionmanagement/installedextensionsbyname/"
            f"{quote(self.MULTIVALUE_PUBLISHER, safe='')}/"
            f"{quote(self.MULTIVALUE_EXTENSION, safe='')}"
        )
        try:
            data = self.get(path, absolute_url=self.extmgmt_url(path)) or {}
        except AdoError as exc:
            if exc.status == 404:
                return "missing"
            raise
        flags = str((data.get("installState") or {}).get("flags") or "none").lower()
        if "disabled" in flags:
            return "disabled"
        return "installed"

    def install_multivalue_extension(self) -> dict[str, Any]:
        path = (
            "/_apis/extensionmanagement/installedextensionsbyname/"
            f"{quote(self.MULTIVALUE_PUBLISHER, safe='')}/"
            f"{quote(self.MULTIVALUE_EXTENSION, safe='')}"
        )
        return self.post(path, absolute_url=self.extmgmt_url(path)) or {}

    def require_multivalue_extension(self) -> None:
        status = self.get_multivalue_extension_status()
        if status == "installed":
            return
        if status == "disabled":
            raise AdoError(
                "DevLabs Multivalue control extension is installed but disabled. "
                "Enable it under Organization settings → Extensions before "
                "process template and project setup.",
                status=403,
            )
        raise AdoError(
            "DevLabs Multivalue control extension "
            f"({self.MULTIVALUE_PUBLISHER}.{self.MULTIVALUE_EXTENSION}) is not "
            "installed. It is required for process template and project setup. "
            "Install from the Marketplace or approve install in the UI, then retry.",
            status=404,
        )

    def patch(self, path: str, json_body: Any = None, **kwargs: Any) -> Any:
        return self.request("PATCH", path, json_body=json_body, **kwargs)

    def put(self, path: str, json_body: Any = None, **kwargs: Any) -> Any:
        return self.request("PUT", path, json_body=json_body, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    def list_processes(self) -> list[dict[str, Any]]:
        data = self.get("/_apis/work/processes", api_version="7.1-preview.2") or {}
        return list(data.get("value") or [])

    def get_process_id(self, process_name: str) -> str | None:
        target = process_name.strip().lower()
        for proc in self.list_processes():
            if str(proc.get("name") or "").strip().lower() == target:
                return str(proc.get("typeId"))
        return None

    def get_agile_process_id(self) -> str:
        for proc in self.list_processes():
            if str(proc.get("name") or "").strip().lower() == "agile":
                return str(proc["typeId"])
        raise AdoError("Built-in Agile process not found in organization.")

    def create_process(self, process_name: str) -> str:
        existing = self.get_process_id(process_name)
        if existing:
            return existing
        payload = {
            "name": process_name,
            "description": f"Custom process based on Agile: {process_name}",
            "parentProcessTypeId": self.get_agile_process_id(),
        }
        try:
            created = self.post("/_apis/work/processes", json_body=payload, api_version="7.1-preview.2")
            return str(created["typeId"])
        except AdoError as exc:
            if exc.status == 409:
                found = self.get_process_id(process_name)
                if found:
                    return found
            raise

    def list_projects(self) -> list[dict[str, Any]]:
        data = self.get("/_apis/projects", api_version="7.1-preview.4") or {}
        return list(data.get("value") or [])

    def get_project_id(self, project_name: str) -> str | None:
        target = project_name.strip().lower()
        for project in self.list_projects():
            if str(project.get("name") or "").strip().lower() == target:
                return str(project.get("id"))
        return None

    def create_project(
        self,
        project_name: str,
        process_id: str,
        *,
        description: str = "",
    ) -> str | None:
        existing = self.get_project_id(project_name)
        if existing:
            return existing
        payload = {
            "name": project_name,
            "description": description or "",
            "capabilities": {
                "versioncontrol": {"sourceControlType": "Git"},
                "processTemplate": {"templateTypeId": process_id},
            },
        }
        self.post("/_apis/projects", json_body=payload, api_version="7.1-preview.4")
        # Creation is async (202); poll briefly.
        for _ in range(30):
            time.sleep(2)
            found = self.get_project_id(project_name)
            if found:
                return found
        return self.get_project_id(project_name)

    def update_project_description(self, project_id: str, description: str) -> None:
        self.patch(
            f"/_apis/projects/{quote(project_id, safe='')}",
            json_body={"description": description},
            api_version="7.1-preview.4",
        )

    def list_process_wits(self, process_id: str) -> list[dict[str, Any]]:
        data = (
            self.get(
                f"/_apis/work/processes/{process_id}/workitemtypes",
                api_version="7.1-preview.2",
            )
            or {}
        )
        return list(data.get("value") or [])

    def create_work_item(
        self,
        project: str,
        work_item_type: str,
        fields: dict[str, Any],
        *,
        parent_id: int | None = None,
        dry_run: bool = False,
        markdown_format_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        patch: list[dict[str, Any]] = []
        # Preserve path: mark large-text fields as Markdown so they
        # render correctly instead of as plain text inside HTML controls.
        for ref in markdown_format_fields or []:
            if ref and fields.get(ref) not in (None, ""):
                patch.append(
                    {
                        "op": "add",
                        "path": f"/multilineFieldsFormat/{ref}",
                        "value": "Markdown",
                    }
                )
        for ref, value in fields.items():
            if value is None or value == "":
                continue
            patch.append({"op": "add", "path": f"/fields/{ref}", "value": value})
        if parent_id:
            parent_url = self.url(f"/_apis/wit/workItems/{parent_id}", project=project)
            # strip query for relation URL
            parent_url = parent_url.split("?")[0]
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
        # ADO create-by-type URLs require a literal "$" before the type name
        # (e.g. /workitems/$Bug). In Python f-strings "$" is literal; "{...}" interpolates.
        return self.request(
            "PATCH",
            f"/_apis/wit/workitems/${quote(work_item_type, safe='')}",
            project=project,
            json_body=patch,
            content_type="application/json-patch+json",
            idempotent=False,
        )

    def find_work_item_ids(
        self,
        project: str,
        work_item_type: str,
        *,
        title: str,
        field_ref: str | None = None,
        field_value: Any = None,
    ) -> list[int]:
        """WIQL lookup used to reconcile a create whose outcome is unknown."""
        clauses = [
            "[System.TeamProject] = @project",
            f"[System.WorkItemType] = {_wiql_literal(work_item_type)}",
            f"[System.Title] = {_wiql_literal(title)}",
        ]
        if field_ref and field_value not in (None, ""):
            clauses.append(f"[{field_ref}] = {_wiql_literal(field_value)}")
        query = "SELECT [System.Id] FROM WorkItems WHERE " + " AND ".join(clauses)
        data = self.post("/_apis/wit/wiql", {"query": query}, project=project) or {}
        return [int(item["id"]) for item in data.get("workItems") or [] if "id" in item]

    def get_parent_id(self, project: str, work_item_id: int) -> int | None:
        """Return Hierarchy-Reverse parent id, or None if unlinked."""
        data = (
            self.request(
                "GET",
                f"/_apis/wit/workItems/{int(work_item_id)}?$expand=Relations",
                project=project,
                api_version="7.1",
            )
            or {}
        )
        for relation in data.get("relations") or []:
            if relation.get("rel") == "System.LinkTypes.Hierarchy-Reverse":
                url = str(relation.get("url") or "").rstrip("/")
                if not url:
                    continue
                try:
                    return int(url.split("/")[-1])
                except ValueError:
                    continue
        return None

    def add_parent_link(
        self,
        project: str,
        child_id: int,
        parent_id: int,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        parent_url = self.url(f"/_apis/wit/workItems/{int(parent_id)}", project=project)
        parent_url = parent_url.split("?")[0]
        patch = [
            {
                "op": "add",
                "path": "/relations/-",
                "value": {
                    "rel": "System.LinkTypes.Hierarchy-Reverse",
                    "url": parent_url,
                    "attributes": {"comment": "Backfilled imported parent link"},
                },
            }
        ]
        if dry_run:
            return {"id": child_id, "parentId": parent_id, "patch": patch}
        return self.request(
            "PATCH",
            f"/_apis/wit/workitems/{int(child_id)}",
            project=project,
            json_body=patch,
            content_type="application/json-patch+json",
        )
