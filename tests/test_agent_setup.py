from __future__ import annotations

import urllib.error

import pytest

import agent_setup


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def http_error(request, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(request.full_url, code, "test", {}, None)


def test_server_access_requires_authenticated_agent_api(monkeypatch: pytest.MonkeyPatch):
    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/health"):
            return Response()
        raise http_error(request, 404)

    monkeypatch.setattr(agent_setup.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(agent_setup, "log", lambda _message: None)
    status = agent_setup.check_server_access("http://server:6001", "valid-token-12345678901234567890")

    assert status == agent_setup.SERVER_AUTHENTICATED
    assert [request.full_url for request, _ in requests] == [
        "http://server:6001/health",
        "http://server:6001/agent/v1/update/0",
    ]
    assert requests[1][0].get_header("X-agent-token") == "valid-token-12345678901234567890"


def test_server_access_rejects_invalid_token_without_logging_secret(monkeypatch: pytest.MonkeyPatch):
    messages = []
    secret = "invalid-token-12345678901234567890"

    def urlopen(request, timeout):
        if request.full_url.endswith("/health"):
            return Response()
        raise http_error(request, 401)

    monkeypatch.setattr(agent_setup.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(agent_setup, "log", messages.append)
    status = agent_setup.check_server_access("http://server:6001", secret)

    assert status == agent_setup.SERVER_TOKEN_INVALID
    assert secret not in "\n".join(messages)
    assert "401" in "\n".join(messages)


def test_server_access_allows_offline_install_retry(monkeypatch: pytest.MonkeyPatch):
    messages = []

    def urlopen(_request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(agent_setup.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(agent_setup, "log", messages.append)
    status = agent_setup.check_server_access("http://server:6001", "token-123456789012345678901234")

    assert status == agent_setup.SERVER_UNREACHABLE
    assert "offline" in "\n".join(messages)


def test_install_stops_before_changes_when_token_is_invalid(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_setup, "is_admin", lambda: True)
    monkeypatch.setattr(
        agent_setup,
        "load_bootstrap",
        lambda: {
            "server_url": "http://server:6001",
            "agent_token": "invalid-token-12345678901234567890",
            "version": "1.0.10",
        },
    )
    monkeypatch.setattr(
        agent_setup,
        "check_server_access",
        lambda _server_url, _agent_token: agent_setup.SERVER_TOKEN_INVALID,
    )
    monkeypatch.setattr(agent_setup, "log", lambda _message: None)
    monkeypatch.setattr(
        agent_setup,
        "stop_and_remove_services",
        lambda: pytest.fail("installation changed before token validation"),
    )

    with pytest.raises(RuntimeError, match="Agent token"):
        agent_setup.install()
