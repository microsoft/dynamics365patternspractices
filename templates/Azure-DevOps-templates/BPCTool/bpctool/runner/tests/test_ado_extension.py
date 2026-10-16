"""DevLabs Multivalue extension preflight helpers."""

from __future__ import annotations

from typing import Any

import pytest

from app.ado_client import AdoClient, AdoError


class FakeExtClient(AdoClient):
    def __init__(self, *, get_result: Any = None, get_error: AdoError | None = None) -> None:
        # Bypass real PAT/org validation for unit tests.
        self.org = "contoso"
        self.organization_url = "https://dev.azure.com/contoso"
        self._auth = "Basic dGVzdA=="
        self.api_version = "7.1"
        self._get_result = get_result
        self._get_error = get_error
        self.calls: list[str] = []

    def get(self, path: str, **kwargs: Any) -> Any:  # noqa: ANN401
        self.calls.append(path)
        if self._get_error is not None:
            raise self._get_error
        return self._get_result


def test_multivalue_status_installed() -> None:
    client = FakeExtClient(get_result={"installState": {"flags": "none"}})
    assert client.get_multivalue_extension_status() == "installed"


def test_multivalue_status_disabled() -> None:
    client = FakeExtClient(get_result={"installState": {"flags": "disabled"}})
    assert client.get_multivalue_extension_status() == "disabled"


def test_multivalue_status_missing() -> None:
    client = FakeExtClient(get_error=AdoError("missing", status=404))
    assert client.get_multivalue_extension_status() == "missing"


def test_require_multivalue_raises_when_missing() -> None:
    client = FakeExtClient(get_error=AdoError("missing", status=404))
    with pytest.raises(AdoError, match="not installed"):
        client.require_multivalue_extension()
