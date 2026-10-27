"""Single, reusable Claude (Anthropic API) client for the backend.

* The API key is read from configuration (environment / backend/.env) only; it is never
  hard-coded, returned to the browser, printed or logged.
* ``ask_claude(prompt, system=None)`` returns the reply text, or raises a ``ClaudeError``
  subclass whose message is safe to show to users.
* The frontend never talks to Anthropic: it calls this backend, which calls Anthropic.
"""
from __future__ import annotations

import logging

from ..config import get_settings
from .errors import (LLMAuthError, LLMBilling, LLMError, LLMNotConfigured, LLMRateLimited,
                     LLMRefused, LLMTimeout, LLMUnavailable)

log = logging.getLogger("restaurantiq.claude")

# Server-side fallback (recommended for claude-opus-5-5): if the model declines a request, the API
# retries it on Anthropic's recommended fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


# Shared provider errors; the Claude* names are kept as aliases for existing callers.
ClaudeError = LLMError
ClaudeNotConfigured = LLMNotConfigured
ClaudeAuthError = LLMAuthError
ClaudeRateLimited = LLMRateLimited
ClaudeTimeout = LLMTimeout
ClaudeUnavailable = LLMUnavailable
ClaudeRefused = LLMRefused
ClaudeBilling = LLMBilling


def _api_error_message(exc) -> str | None:
    """Anthropic's own error text (e.g. 'Your credit balance is too low...'). It never contains the key."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"][:300]
    return None


NOT_CONFIGURED_MESSAGE = ("ANTHROPIC_API_KEY is not set. Add your key to backend/.env "
                          "(ANTHROPIC_API_KEY=...) and restart the backend.")


def is_configured() -> bool:
    return get_settings().anthropic_configured


def startup_check() -> bool:
    """Called once at startup: logs a clear message (never the key) and returns whether the key exists."""
    if is_configured():
        log.info("Anthropic API key found; live AI explanations enabled (model %s).", get_settings().llm_model)
        return True
    log.warning("Anthropic API key missing: %s The AI Analyst runs in Demo Mode until then.", NOT_CONFIGURED_MESSAGE)
    return False


def _client():
    import anthropic
    s = get_settings()
    if not s.anthropic_configured:
        raise ClaudeNotConfigured(NOT_CONFIGURED_MESSAGE)
    return anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=s.llm_timeout_seconds, max_retries=1)


def ask_claude(prompt: str, system: str | None = None, *, max_tokens: int = 4000, effort: str = "low") -> str:
    """Send one prompt and return Claude's text reply.

    Raises ClaudeNotConfigured, ClaudeAuthError, ClaudeRateLimited, ClaudeTimeout, ClaudeUnavailable
    or ClaudeRefused (all subclasses of ClaudeError) with user-safe messages.
    """
    import anthropic
    client = _client()
    kwargs = {"system": system} if system else {}
    try:
        response = client.beta.messages.create(
            model=get_settings().llm_model,
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": effort},
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
    except anthropic.AuthenticationError:
        log.warning("Anthropic rejected the configured API key (authentication error).")
        raise ClaudeAuthError("The Anthropic API rejected the configured API key. Check ANTHROPIC_API_KEY in backend/.env.")
    except anthropic.PermissionDeniedError:
        raise ClaudeAuthError("The configured API key is not allowed to use this model. Check your Anthropic account.")
    except anthropic.RateLimitError:
        raise ClaudeRateLimited("The Anthropic API rate limit was reached. Wait a moment and try again.")
    except anthropic.APITimeoutError:
        raise ClaudeTimeout("The Anthropic API did not respond in time. Try again shortly.")
    except anthropic.APIConnectionError:
        raise ClaudeUnavailable("The Anthropic API could not be reached. Check the internet connection.")
    except anthropic.APIStatusError as exc:
        reason = _api_error_message(exc)
        log.warning("Anthropic API returned HTTP %s: %s", exc.status_code, reason or "no details")
        if reason and "credit balance" in reason.lower():
            raise ClaudeBilling("Your Anthropic account has no credit left, so Claude cannot answer. Add credits at "
                                "console.anthropic.com > Plans & Billing; the AI Analyst shows computed answers meanwhile.")
        detail = f": {reason}" if reason else ". Try again later."
        raise ClaudeUnavailable(f"The Anthropic API returned an error ({exc.status_code}){detail}")
    if response.stop_reason == "refusal":
        raise ClaudeRefused("Claude declined to answer this request.")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise ClaudeUnavailable("The Anthropic API returned an empty reply.")
    return text
