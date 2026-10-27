"""Claude client: configuration, error mapping and the /api/test-claude endpoint (no real API calls)."""
import logging
import types

import httpx
import pytest

from app.config import reload_settings
from app.services import claude_client

FAKE_KEY = "sk-ant-test-0000-not-a-real-key"


@pytest.fixture(autouse=True)
def _use_anthropic_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    reload_settings()


def _fake_anthropic(monkeypatch, create):
    import anthropic

    class Fake:
        def __init__(self, *a, **k):
            self.kwargs = k
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    monkeypatch.setattr(anthropic, "Anthropic", Fake)


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    reload_settings()


@pytest.mark.parametrize("value", ["", "your_key_here"])
def test_missing_or_placeholder_key_is_not_configured(monkeypatch, value):
    monkeypatch.setenv("ANTHROPIC_API_KEY", value)
    reload_settings()
    assert claude_client.is_configured() is False
    with pytest.raises(claude_client.ClaudeNotConfigured, match="ANTHROPIC_API_KEY is not set"):
        claude_client.ask_claude("hi")


def test_startup_check_logs_without_key(monkeypatch, caplog):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    reload_settings()
    with caplog.at_level(logging.INFO):
        assert claude_client.startup_check() is True
    assert FAKE_KEY not in caplog.text
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    reload_settings()
    with caplog.at_level(logging.WARNING):
        assert claude_client.startup_check() is False
    assert "ANTHROPIC_API_KEY is not set" in caplog.text


def test_settings_repr_hides_secrets(key):
    from app.config import get_settings
    assert FAKE_KEY not in repr(get_settings())


def test_ask_claude_success_passes_system_and_model(monkeypatch, key):
    seen = {}

    def create(**kw):
        seen.update(kw)
        return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=" Hello ")])
    _fake_anthropic(monkeypatch, create)
    assert claude_client.ask_claude("Say hi", system="Be brief") == "Hello"
    assert seen["system"] == "Be brief" and seen["model"] == "claude-opus-5-5" and seen["fallbacks"] == "default"
    assert seen["messages"] == [{"role": "user", "content": "Say hi"}]


def _status_error(cls, status):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message="x", response=httpx.Response(status, request=req), body=None)


@pytest.mark.parametrize("make_exc,expected", [
    (lambda a: _status_error(a.AuthenticationError, 401), claude_client.ClaudeAuthError),
    (lambda a: _status_error(a.RateLimitError, 429), claude_client.ClaudeRateLimited),
    (lambda a: a.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com")), claude_client.ClaudeTimeout),
    (lambda a: a.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), claude_client.ClaudeUnavailable),
    (lambda a: _status_error(a.InternalServerError, 500), claude_client.ClaudeUnavailable),
])
def test_error_mapping(monkeypatch, key, make_exc, expected):
    import anthropic

    def create(**kw):
        raise make_exc(anthropic)
    _fake_anthropic(monkeypatch, create)
    with pytest.raises(expected) as info:
        claude_client.ask_claude("hi")
    assert FAKE_KEY not in str(info.value)


def test_no_credit_gives_billing_message(client, monkeypatch, key):
    import anthropic

    def create(**kw):
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.BadRequestError(message="x", response=httpx.Response(400, request=req), body={
            "type": "error", "error": {"type": "invalid_request_error",
                                       "message": "Your credit balance is too low to access the Anthropic API."}})
    _fake_anthropic(monkeypatch, create)
    with pytest.raises(claude_client.ClaudeBilling, match="no credit"):
        claude_client.ask_claude("hi")
    r = client.get("/api/test-claude")
    assert r.status_code == 402 and "Plans & Billing" in r.json()["error"] and FAKE_KEY not in r.text


def test_other_400_shows_api_reason(monkeypatch, key):
    import anthropic

    def create(**kw):
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.BadRequestError(message="x", response=httpx.Response(400, request=req),
                                        body={"error": {"message": "max_tokens: must be positive"}})
    _fake_anthropic(monkeypatch, create)
    with pytest.raises(claude_client.ClaudeUnavailable, match="max_tokens: must be positive"):
        claude_client.ask_claude("hi")


def test_refusal(monkeypatch, key):
    _fake_anthropic(monkeypatch, lambda **kw: types.SimpleNamespace(stop_reason="refusal", content=[]))
    with pytest.raises(claude_client.ClaudeRefused):
        claude_client.ask_claude("hi")


def test_endpoint_without_key_returns_clear_503(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    reload_settings()
    r = client.get("/api/test-claude")
    assert r.status_code == 503 and "ANTHROPIC_API_KEY is not set" in r.json()["error"]


def test_endpoint_with_key(client, monkeypatch, key):
    _fake_anthropic(monkeypatch, lambda **kw: types.SimpleNamespace(
        stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text="RestaurantIQ connection OK")]))
    r = client.get("/api/test-claude")
    assert r.status_code == 200 and r.json()["reply"] == "RestaurantIQ connection OK"
    assert FAKE_KEY not in r.text


def test_endpoint_rate_limited(client, monkeypatch, key):
    import anthropic

    def create(**kw):
        raise _status_error(anthropic.RateLimitError, 429)
    _fake_anthropic(monkeypatch, create)
    r = client.get("/api/test-claude")
    assert r.status_code == 429 and "rate limit" in r.json()["error"] and FAKE_KEY not in r.text
