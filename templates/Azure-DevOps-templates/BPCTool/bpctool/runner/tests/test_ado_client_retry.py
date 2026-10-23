"""Retry and idempotency rules for AdoClient.request."""

from __future__ import annotations

import base64

import pytest

from app import ado_client
from app.ado_client import AdoClient, AdoError, retry_delay_seconds

PAT = "x" * 52


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ado_client.time, "sleep", lambda _s: None)


def _client(monkeypatch: pytest.MonkeyPatch, responses: list) -> tuple[AdoClient, list]:
    client = AdoClient("https://dev.azure.com/contoso", PAT)
    calls: list[str] = []

    def fake_send(method, url, data, headers):
        calls.append(method)
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(client, "_send", fake_send)
    return client, calls


def test_retry_delay_honors_retry_after_seconds_and_float() -> None:
    assert retry_delay_seconds("3", 0) == 3.0
    assert retry_delay_seconds("1.5", 0) == 1.5
    assert retry_delay_seconds("9999", 0) == ado_client.MAX_RETRY_DELAY_S


def test_retry_delay_backoff_is_jittered_and_bounded() -> None:
    for attempt in range(8):
        delay = retry_delay_seconds(None, attempt)
        base = min(30.0, 1.5 * (2**attempt))
        assert base * 0.75 <= delay <= base * 1.25


def test_get_retries_network_error_and_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _client(
        monkeypatch,
        [
            ConnectionResetError("reset"),
            (502, "Bad Gateway", None, b""),
            (200, "OK", None, b'{"ok": true}'),
        ],
    )
    assert client.get("/_apis/projects") == {"ok": True}
    assert calls == ["GET", "GET", "GET"]


def test_create_does_not_retry_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _client(monkeypatch, [ConnectionResetError("reset")])
    with pytest.raises(AdoError) as info:
        client.create_work_item("Demo", "Scenario", {"System.Title": "x"})
    assert info.value.outcome_unknown is True
    assert calls == ["PATCH"]


def test_create_does_not_retry_500(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _client(monkeypatch, [(500, "Server Error", None, b"oops")])
    with pytest.raises(AdoError) as info:
        client.create_work_item("Demo", "Scenario", {"System.Title": "x"})
    assert info.value.status == 500
    assert info.value.outcome_unknown is False
    assert calls == ["PATCH"]


def test_create_retries_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _client(
        monkeypatch,
        [
            (429, "Too Many Requests", "0.5", b""),
            (200, "OK", None, b'{"id": 42}'),
        ],
    )
    assert client.create_work_item("Demo", "Scenario", {"System.Title": "x"}) == {"id": 42}
    assert calls == ["PATCH", "PATCH"]


def test_203_sign_in_page_is_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _client(
        monkeypatch, [(203, "Non-Authoritative Information", None, b"<html>sign in</html>")]
    )
    with pytest.raises(AdoError) as info:
        client.get("/_apis/projects")
    assert info.value.status == 401
    assert "PAT" in str(info.value)
    assert calls == ["GET"]


def test_pool_tunnels_https_through_env_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ado_client, "getproxies", lambda: {"https": "http://bob:p%40ss@proxy.local:3128"}
    )
    monkeypatch.setattr(ado_client, "proxy_bypass", lambda _host: False)
    pool = ado_client._ConnectionPool(5)
    conn, http_proxy_headers = pool.get("https", "dev.azure.com")
    assert http_proxy_headers is None
    assert (conn.host, conn.port) == ("proxy.local", 3128)
    assert conn._tunnel_host == "dev.azure.com"
    assert conn._tunnel_port == 443
    expected = "Basic " + base64.b64encode(b"bob:p@ss").decode("ascii")
    assert conn._tunnel_headers["Proxy-Authorization"] == expected


def test_pool_connects_directly_when_proxy_bypassed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ado_client, "getproxies", lambda: {"https": "http://proxy.local:3128"})
    monkeypatch.setattr(ado_client, "proxy_bypass", lambda host: host == "dev.azure.com")
    conn, _ = ado_client._ConnectionPool(5).get("https", "dev.azure.com")
    assert conn.host == "dev.azure.com"
    assert getattr(conn, "_tunnel_host", None) is None


def test_non_retryable_status_raises_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _client(monkeypatch, [(400, "Bad Request", None, b"bad field")])
    with pytest.raises(AdoError) as info:
        client.get("/_apis/projects")
    assert info.value.status == 400
    assert "bad field" in str(info.value)
    assert calls == ["GET"]
