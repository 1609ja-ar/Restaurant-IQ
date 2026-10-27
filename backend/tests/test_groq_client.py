"""Groq provider: request shape, error mapping, endpoint and analyst integration (mocked HTTP, no real calls)."""
import json
import logging

import httpx
import pytest

from app.config import reload_settings
from app.services import groq_client, llm_client
from app.services.errors import (LLMAuthError, LLMBilling, LLMNotConfigured, LLMRateLimited, LLMTimeout,
                                 LLMUnavailable)

FAKE_KEY = "gsk_test_0000_not_a_real_key"
REAL_CLIENT = httpx.Client


def _mock(monkeypatch, handler):
    """Route Groq's httpx calls through a fake server; records every request."""
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(groq_client.httpx, "Client",
                        lambda *a, **k: REAL_CLIENT(*a, **{**k, "transport": httpx.MockTransport(wrapped)}))
    return seen


def _ok(text="Hello from Groq", finish="stop"):
    return lambda req: httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text},
                                                              "finish_reason": finish}]})


def _err(status, message, code=None):
    return lambda req: httpx.Response(status, json={"error": {"message": message, "type": "invalid_request_error",
                                                              "code": code}})


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    reload_settings()
    groq_client._fallback_model.clear()
    yield
    groq_client._fallback_model.clear()


@pytest.mark.parametrize("value", ["", "your_groq_key_here"])
def test_missing_or_placeholder_key(monkeypatch, value):
    monkeypatch.setenv("GROQ_API_KEY", value)
    reload_settings()
    assert llm_client.is_configured() is False
    with pytest.raises(LLMNotConfigured, match="GROQ_API_KEY is not set"):
        llm_client.ask_llm("hi")


def test_request_shape_and_reply(monkeypatch, key):
    seen = _mock(monkeypatch, _ok(" Hi there "))
    assert llm_client.ask_llm("Say hi", system="Be brief") == "Hi there"
    req = seen[0]
    assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    body = json.loads(req.content)
    assert body["model"] == "llama-3.3-70b-versatile"
    assert body["messages"] == [{"role": "system", "content": "Be brief"}, {"role": "user", "content": "Say hi"}]


@pytest.mark.parametrize("handler,expected,text", [
    (_err(401, "Invalid API Key", "invalid_api_key"), LLMAuthError, "rejected the configured API key"),
    (_err(429, "Rate limit reached for model"), LLMRateLimited, "rate limit"),
    (_err(429, "You exceeded your current quota", "insufficient_quota"), LLMBilling, "quota"),
    (_err(404, "The model `x` does not exist", "model_not_found"), LLMUnavailable, "GROQ_MODEL"),
    (_err(400, "The model has been decommissioned", "model_decommissioned"), LLMUnavailable, "GROQ_MODEL"),
    (_err(500, "Internal error"), LLMUnavailable, "Internal error"),
])
def test_error_mapping(monkeypatch, key, handler, expected, text):
    _mock(monkeypatch, handler)
    with pytest.raises(expected, match=text) as info:
        llm_client.ask_llm("hi")
    assert FAKE_KEY not in str(info.value)


def test_timeout_and_connection_errors(monkeypatch, key):
    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)
    _mock(monkeypatch, timeout)
    with pytest.raises(LLMTimeout):
        llm_client.ask_llm("hi")

    def down(req):
        raise httpx.ConnectError("no route", request=req)
    _mock(monkeypatch, down)
    with pytest.raises(LLMUnavailable, match="could not be reached"):
        llm_client.ask_llm("hi")


def test_startup_check_never_logs_key(monkeypatch, key, caplog):
    with caplog.at_level(logging.INFO):
        assert llm_client.startup_check() is True
    assert "Groq" in caplog.text and FAKE_KEY not in caplog.text


def test_test_endpoint(client, monkeypatch, key):
    _mock(monkeypatch, _ok("RestaurantIQ connection OK"))
    r = client.get("/api/test-llm")
    assert r.status_code == 200 and r.json() == {"ok": True, "provider": "groq", "model": "llama-3.3-70b-versatile",
                                                  "reply": "RestaurantIQ connection OK"}
    assert FAKE_KEY not in r.text
    assert client.get("/api/test-claude").status_code == 200  # old URL still works


def test_test_endpoint_without_key(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    reload_settings()
    r = client.get("/api/test-llm")
    assert r.status_code == 503 and "GROQ_API_KEY is not set" in r.json()["error"]


def test_analyst_uses_groq_for_explanations(client, monkeypatch, key):
    seen = _mock(monkeypatch, _ok("Plain explanation from Groq."))
    client.post("/api/demo/load")
    sugg = client.get("/api/analyst/suggestions").json()
    assert sugg["mode"] == "llm" and sugg["provider"] == "Groq (llama-3.3-70b-versatile)"
    r = client.post("/api/analyst/ask", json={"question": "Which neighborhoods have the highest listing density?"}).json()
    assert r["mode"] == "llm" and r["explanation"] == "Plain explanation from Groq." and r["answer"]
    sent = json.loads(seen[-1].content)["messages"][-1]["content"]
    assert "top_locations" in sent  # only the computed JSON result is sent


def test_analyst_falls_back_to_computed_answer_on_groq_error(client, monkeypatch, key):
    _mock(monkeypatch, _err(401, "Invalid API Key", "invalid_api_key"))
    client.post("/api/demo/load")
    r = client.post("/api/analyst/ask", json={"question": "Which neighborhoods have the highest listing density?"}).json()
    assert r["explanation"] is None and "rejected" in r["ai_error"] and r["answer"]


def test_missing_model_falls_back_to_available_model(monkeypatch, key, caplog):
    """Groq retired llama-3.3-70b-versatile: the client must switch to an available chat model by itself."""
    def handler(req):
        if req.method == "GET" and req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "whisper-large-v3", "active": True},
                                                      {"id": "meta-llama/llama-prompt-guard-2-86m", "active": True},
                                                      {"id": "openai/gpt-oss-20b", "active": True},
                                                      {"id": "openai/gpt-oss-120b", "active": True}]})
        body = json.loads(req.content)
        if body["model"] == "llama-3.3-70b-versatile":
            return httpx.Response(404, json={"error": {"message": "The model `llama-3.3-70b-versatile` does not exist "
                                                                  "or you do not have access to it.",
                                                       "code": "model_not_found"}})
        assert body["reasoning_effort"] == "low"      # gpt-oss needs this or it may return no text
        return _ok("RestaurantIQ connection OK")(req)
    seen = _mock(monkeypatch, handler)
    with caplog.at_level(logging.WARNING):
        assert llm_client.ask_llm("hi") == "RestaurantIQ connection OK"
    assert "GROQ_MODEL=openai/gpt-oss-120b" in caplog.text
    assert llm_client.model() == "openai/gpt-oss-120b"
    # next call goes straight to the working model
    llm_client.ask_llm("again")
    assert json.loads(seen[-1].content)["model"] == "openai/gpt-oss-120b"


def test_reasoning_effort_only_for_gpt_oss(monkeypatch, key):
    seen = _mock(monkeypatch, _ok())
    llm_client.ask_llm("hi")
    assert "reasoning_effort" not in json.loads(seen[-1].content)


def test_empty_reply_after_token_budget_is_explained(monkeypatch, key):
    _mock(monkeypatch, _ok("", finish="length"))
    with pytest.raises(LLMUnavailable, match="whole token budget"):
        llm_client.ask_llm("hi")
