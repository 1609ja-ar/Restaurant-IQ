"""Errors shared by every language-model provider (Groq, Anthropic).

``str(exc)`` is always a friendly message that is safe to show users; it never contains an API key.
"""


class LLMError(Exception):
    status_code = 502


class LLMNotConfigured(LLMError):
    status_code = 503


class LLMAuthError(LLMError):
    status_code = 502


class LLMBilling(LLMError):
    """The key is valid but the account cannot be charged (no credit / quota exhausted)."""
    status_code = 402


class LLMRateLimited(LLMError):
    status_code = 429


class LLMTimeout(LLMError):
    status_code = 504


class LLMUnavailable(LLMError):
    status_code = 502


class LLMRefused(LLMError):
    status_code = 422
