"""Org URL parsing parity with src/adoOrgUrl.js (dev.azure.com + visualstudio.com)."""

import pytest

from app.org_url import normalize_ado_org_url, parse_ado_org_url


@pytest.mark.parametrize(
    "raw,org",
    [
        ("https://dev.azure.com/contoso", "contoso"),
        ("https://dev.azure.com/contoso/", "contoso"),
        ("https://dev.azure.com/contoso/Contoso-BPC", "contoso"),
        ("http://dev.azure.com/My-Org", "My-Org"),
        ("dev.azure.com/contoso", "contoso"),
        ("contoso", "contoso"),
        ("https://contoso.visualstudio.com", "contoso"),
        ("https://contoso.visualstudio.com/", "contoso"),
        ("https://contoso.visualstudio.com/DefaultCollection", "contoso"),
        ("contoso.visualstudio.com", "contoso"),
        ("https://CONTOSO.visualstudio.com", "contoso"),
    ],
)
def test_parse_accepts_modern_and_legacy(raw: str, org: str) -> None:
    parsed = parse_ado_org_url(raw)
    assert parsed.ok, parsed.error
    assert parsed.org == org
    assert parsed.organization_url == f"https://dev.azure.com/{org}"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "https://example.com/org",
        "https://dev.azure.com/",
        "https://app.visualstudio.com",
        "https://vssps.visualstudio.com",
        "not a url!!!",
    ],
)
def test_parse_rejects_invalid(raw: str) -> None:
    assert not parse_ado_org_url(raw).ok


def test_normalize_always_canonicalizes_to_dev_azure() -> None:
    assert normalize_ado_org_url("https://contoso.visualstudio.com") == "https://dev.azure.com/contoso"
    assert normalize_ado_org_url("https://dev.azure.com/contoso") == "https://dev.azure.com/contoso"
    assert normalize_ado_org_url("contoso") == "https://dev.azure.com/contoso"


def test_legacy_and_modern_same_api_base() -> None:
    modern = normalize_ado_org_url("https://dev.azure.com/fabrikam")
    legacy = normalize_ado_org_url("https://fabrikam.visualstudio.com")
    assert modern == legacy == "https://dev.azure.com/fabrikam"
