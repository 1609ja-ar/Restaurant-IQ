"""The one entry point the app uses for language models: ``ask_llm(prompt, system=None)``.

The provider is chosen with LLM_PROVIDER in backend/.env:
  groq       (default) - uses GROQ_API_KEY and GROQ_MODEL
  anthropic            - uses ANTHROPIC_API_KEY and RIQ_LLM_MODEL
Without a configured key the AI Analyst runs in labeled Demo Mode. Keys never reach the browser or logs.
"""
from __future__ import annotations

import logging

from ..config import get_settings
from . import claude_client, groq_client
from .errors import LLMError, LLMNotConfigured, LLMRefused  # noqa: F401  (re-exported for callers)

log = logging.getLogger("restaurantiq.llm")
PROVIDERS = {"groq", "anthropic"}


def provider() -> str:
    return get_settings().llm_provider


def model() -> str:
    s = get_settings()
    return groq_client.current_model() if s.llm_provider == "groq" else s.llm_model


def label() -> str:
    """Human-readable name for the UI, e.g. 'Groq (llama-3.3-70b-versatile)'."""
    return f"{'Groq' if provider() == 'groq' else 'Claude'} ({model()})"


def is_configured() -> bool:
    p = provider()
    if p == "groq":
        return groq_client.is_configured()
    if p == "anthropic":
        return claude_client.is_configured()
    return False


def ask_llm(prompt: str, system: str | None = None, *, max_tokens: int = 1024) -> str:
    p = provider()
    if p == "groq":
        return groq_client.ask_groq(prompt, system, max_tokens=max_tokens)
    if p == "anthropic":
        return claude_client.ask_claude(prompt, system, max_tokens=max_tokens)
    raise LLMNotConfigured(f"LLM_PROVIDER '{p}' is not supported. Use 'groq' or 'anthropic' in backend/.env.")


def startup_check() -> bool:
    """Logs which provider is active and whether its key is present (never the key itself)."""
    p = provider()
    if p not in PROVIDERS:
        log.warning("LLM_PROVIDER '%s' is not supported (use groq or anthropic); AI Analyst runs in Demo Mode.", p)
        return False
    if is_configured():
        log.info("AI provider: %s; live AI explanations enabled.", label())
        return True
    key = "GROQ_API_KEY" if p == "groq" else "ANTHROPIC_API_KEY"
    log.warning("AI provider %s selected but %s is not set in backend/.env; the AI Analyst runs in Demo Mode.", p, key)
    return False
