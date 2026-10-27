"""Groq client (OpenAI-compatible chat completions API) using httpx.

Endpoint: POST https://api.groq.com/openai/v1/chat/completions with ``Authorization: Bearer <GROQ_API_KEY>``.
The key is read from configuration only and is never logged or returned.

Groq retires models regularly. If the configured GROQ_MODEL no longer exists, the client asks Groq for the
models this key can use, switches to the best available chat model for the rest of the session, and logs a
warning telling you which GROQ_MODEL to set.
"""
from __future__ import annotations

import logging
import threading

import httpx

from ..config import get_settings
from .errors import (LLMAuthError, LLMBilling, LLMNotConfigured, LLMRateLimited, LLMRefused, LLMTimeout,
                     LLMUnavailable)

log = logging.getLogger("restaurantiq.groq")

NOT_CONFIGURED_MESSAGE = ("GROQ_API_KEY is not set. Add your key to backend/.env (GROQ_API_KEY=gsk_...) "
                          "and restart the backend.")
MODELS_HELP = "See https://console.groq.com/docs/models and set GROQ_MODEL in backend/.env."

# Preferred chat models, best first. Anything containing a NON_CHAT marker is never picked automatically.
PREFERRED_MODELS = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
NON_CHAT = ("whisper", "guard", "safeguard", "orpheus", "tts", "playai", "distil")

_fallback_lock = threading.Lock()
_fallback_model: dict[str, str] = {}   # configured model -> model actually used


def is_configured() -> bool:
    return get_settings().groq_configured


def current_model() -> str:
    configured = get_settings().groq_model
    return _fallback_model.get(configured, configured)


def _error_message(resp: httpx.Response) -> str | None:
    try:
        err = resp.json().get("error")
    except ValueError:
        return None
    if isinstance(err, dict) and isinstance(err.get("message"), str):
        return err["message"][:300]
    return None


def _error_code(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return str(err.get("code") or err.get("type") or "")
    except ValueError:
        return ""


def _is_model_missing(resp: httpx.Response) -> bool:
    code = _error_code(resp)
    reason = (_error_message(resp) or "").lower()
    return (resp.status_code == 404 or "model_not_found" in code or "decommissioned" in code
            or "does not exist" in reason or "decommissioned" in reason)


def _body(model: str, messages: list[dict], max_tokens: int) -> dict:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
    if model.startswith("openai/gpt-oss"):
        # Reasoning model: without this it can spend the whole token budget "thinking" and return no text.
        body["reasoning_effort"] = "low"
    return body


def pick_available_model(client: httpx.Client, api_key: str) -> str | None:
    """Best chat model this key can use, from Groq's /models list."""
    try:
        resp = client.get("/models", headers={"Authorization": f"Bearer {api_key}"})
        ids = [m["id"] for m in resp.json().get("data", []) if m.get("active", True)] if resp.status_code == 200 else []
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    chat = [i for i in ids if not any(x in i.lower() for x in NON_CHAT)]
    for preferred in PREFERRED_MODELS:
        if preferred in chat:
            return preferred
    return sorted(chat)[0] if chat else None


def ask_groq(prompt: str, system: str | None = None, *, max_tokens: int = 1024,
             transport: httpx.BaseTransport | None = None) -> str:
    s = get_settings()
    if not s.groq_configured:
        raise LLMNotConfigured(NOT_CONFIGURED_MESSAGE)
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    headers = {"Authorization": f"Bearer {s.groq_api_key}"}
    model = current_model()
    try:
        with httpx.Client(base_url=s.groq_base_url, timeout=s.llm_timeout_seconds, transport=transport) as client:
            resp = client.post("/chat/completions", json=_body(model, messages, max_tokens), headers=headers)
            if resp.status_code != 200 and _is_model_missing(resp):
                replacement = pick_available_model(client, s.groq_api_key)
                if replacement and replacement != model:
                    log.warning("Groq model '%s' is not available; using '%s' instead. Set GROQ_MODEL=%s in "
                                "backend/.env to make this permanent.", model, replacement, replacement)
                    with _fallback_lock:
                        _fallback_model[s.groq_model] = replacement
                    model = replacement
                    resp = client.post("/chat/completions", json=_body(model, messages, max_tokens), headers=headers)
    except httpx.TimeoutException:
        raise LLMTimeout("Groq did not respond in time. Try again shortly.")
    except httpx.TransportError:
        raise LLMUnavailable("Groq could not be reached. Check the internet connection.")

    if resp.status_code == 200:
        try:
            choice = resp.json()["choices"][0]
            text = (choice.get("message") or {}).get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMUnavailable("Groq returned a response the app could not read.")
        if choice.get("finish_reason") == "content_filter":
            raise LLMRefused("Groq declined to answer this request.")
        text = text.strip()
        if not text:
            if choice.get("finish_reason") == "length":
                raise LLMUnavailable(f"Groq's model '{model}' used its whole token budget before answering. "
                                     "Try again, or choose another GROQ_MODEL.")
            raise LLMUnavailable("Groq returned an empty reply.")
        return text

    reason = _error_message(resp)
    code = _error_code(resp)
    log.warning("Groq API returned HTTP %s: %s", resp.status_code, reason or "no details")
    if resp.status_code == 401:
        raise LLMAuthError("Groq rejected the configured API key. Check GROQ_API_KEY in backend/.env.")
    if resp.status_code == 403:
        raise LLMAuthError(f"Groq refused access with this key{': ' + reason if reason else '.'}")
    if resp.status_code == 429:
        if "quota" in (reason or "").lower() or "insufficient" in code:
            raise LLMBilling(f"Your Groq quota is used up{': ' + reason if reason else '.'}")
        raise LLMRateLimited("The Groq rate limit was reached. Wait a moment and try again.")
    if _is_model_missing(resp):
        raise LLMUnavailable(f"Groq does not offer the model '{model}' to this key"
                             f"{' (' + reason + ')' if reason else ''}. {MODELS_HELP}")
    if resp.status_code == 413:
        raise LLMUnavailable("The request was too large for Groq. Try a narrower question.")
    detail = f": {reason}" if reason else ". Try again later."
    raise LLMUnavailable(f"Groq returned an error ({resp.status_code}){detail}")
