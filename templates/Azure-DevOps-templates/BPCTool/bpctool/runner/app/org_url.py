"""Normalize Azure DevOps organization URLs (mirror of src/adoOrgUrl.js)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

_BARE_ORG = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$")
_VSSO_HOST = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]\.visualstudio\.com$", re.I)
_RESERVED_VSSO = {"app", "vssps", "vsaex", "pkgs", "feeds"}


@dataclass(frozen=True)
class ParsedOrgUrl:
    ok: bool
    org: str = ""
    organization_url: str = ""
    error: str = ""


def parse_ado_org_url(value: str) -> ParsedOrgUrl:
    """Parse SaaS org URLs: dev.azure.com/{org} or {org}.visualstudio.com.

    Always returns a canonical ``https://dev.azure.com/{org}`` API base so the
    runner talks to the modern host regardless of how the user entered the org.
    """
    raw = (value or "").strip()
    if not raw:
        return ParsedOrgUrl(ok=False, error="Azure DevOps org URL is required.")

    if "://" not in raw:
        if _BARE_ORG.fullmatch(raw) and "/" not in raw and "." not in raw and ":" not in raw:
            raw = f"https://dev.azure.com/{raw}"
        elif raw.lower().startswith("dev.azure.com/"):
            raw = f"https://{raw}"
        elif _VSSO_HOST.fullmatch(raw):
            raw = f"https://{raw}"
        else:
            return ParsedOrgUrl(
                ok=False,
                error=(
                    "Enter a full https:// URL (for example https://dev.azure.com/yourorg "
                    "or https://yourorg.visualstudio.com) or your organization name only."
                ),
            )

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ParsedOrgUrl(ok=False, error="Org URL must be an http(s) URL.")

    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    parts = [p for p in parsed.path.split("/") if p]

    if host == "dev.azure.com":
        if not parts:
            return ParsedOrgUrl(
                ok=False,
                error="Org URL must include the organization after dev.azure.com.",
            )
        org = parts[0]
        return ParsedOrgUrl(
            ok=True,
            org=org,
            organization_url=f"https://dev.azure.com/{org}",
        )

    if host.endswith(".visualstudio.com"):
        org = host[: -len(".visualstudio.com")]
        if not org or "." in org or org.lower() in _RESERVED_VSSO:
            return ParsedOrgUrl(
                ok=False,
                error=(
                    "URL must be https://dev.azure.com/{organization} or "
                    "https://{organization}.visualstudio.com"
                ),
            )
        return ParsedOrgUrl(
            ok=True,
            org=org,
            organization_url=f"https://dev.azure.com/{org}",
        )

    return ParsedOrgUrl(
        ok=False,
        error="Org URL must be a dev.azure.com or *.visualstudio.com organization URL.",
    )


def normalize_ado_org_url(value: str) -> str:
    """Canonical API base: always ``https://dev.azure.com/{org}``."""
    parsed = parse_ado_org_url(value)
    if not parsed.ok:
        raise ValueError(parsed.error)
    return parsed.organization_url
