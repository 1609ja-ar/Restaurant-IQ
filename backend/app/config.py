"""Application settings, loaded once from environment variables.

Values come from the process environment, optionally pre-filled from ``backend/.env``
(then the project-root ``.env``) via python-dotenv. Existing environment variables always
win. Secrets (API key, database password) are never logged: they are excluded from repr().
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

PLACEHOLDER_KEYS = {"", "your_key_here", "your-api-key", "changeme", "your_groq_key_here"}


def load_env_files() -> None:
    for path in (BACKEND_DIR / ".env", PROJECT_DIR / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


@dataclass(frozen=True)
class Settings:
    # Language model for the AI Analyst: "groq" (default) or "anthropic". Without a key: Demo Mode.
    llm_provider: str = "groq"
    groq_api_key: str | None = field(default=None, repr=False)
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    # Anthropic (optional alternative provider)
    anthropic_api_key: str | None = field(default=None, repr=False)
    llm_model: str = "claude-opus-5-5"
    llm_timeout_seconds: float = 60.0
    # Storage: "mongodb" (default, the database of record) or "file" (local files, used by tests)
    storage: str = "mongodb"
    mongo_uri: str = field(default="mongodb://127.0.0.1:27017", repr=False)   # may contain a password
    mongo_db: str = "restaurantiq"
    mongo_timeout_ms: int = 5000
    data_dir: Path = BACKEND_DIR / "data"
    # Authentication
    app_env: str = "development"            # "production" makes a missing JWT_SECRET a startup error
    jwt_secret: str | None = field(default=None, repr=False)
    jwt_expire_minutes: int = 60
    allow_registration: bool = True
    demo_user_email: str | None = None
    demo_user_password: str | None = field(default=None, repr=False)
    cookie_secure: bool = False             # set true when served over HTTPS
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key) and self.groq_api_key.strip() not in PLACEHOLDER_KEYS

    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key) and self.anthropic_api_key.strip() not in PLACEHOLDER_KEYS


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _from_env() -> Settings:
    env = os.environ.get
    return Settings(
        llm_provider=(env("LLM_PROVIDER") or "groq").strip().lower(),
        groq_api_key=env("GROQ_API_KEY") or None,
        groq_model=env("GROQ_MODEL") or "openai/gpt-oss-120b",
        groq_base_url=env("GROQ_BASE_URL") or "https://api.groq.com/openai/v1",
        anthropic_api_key=env("ANTHROPIC_API_KEY") or None,
        llm_model=env("RIQ_LLM_MODEL") or "claude-opus-5-5",
        llm_timeout_seconds=float(env("RIQ_LLM_TIMEOUT") or 60),
        storage=(env("RIQ_STORAGE") or "mongodb").strip().lower(),
        mongo_uri=(env("RIQ_MONGO_URI") or "mongodb://127.0.0.1:27017").strip(),
        mongo_db=(env("RIQ_MONGO_DB") or "restaurantiq").strip(),
        mongo_timeout_ms=int(env("RIQ_MONGO_TIMEOUT_MS") or 5000),
        data_dir=Path(env("RIQ_DATA_DIR") or BACKEND_DIR / "data"),
        app_env=(env("RIQ_ENV") or "development").strip().lower(),
        jwt_secret=env("JWT_SECRET") or None,
        jwt_expire_minutes=int(env("JWT_EXPIRE_MINUTES") or 60),
        allow_registration=_bool(env("ALLOW_REGISTRATION"), True),
        demo_user_email=(env("DEMO_USER_EMAIL") or "").strip().lower() or None,
        demo_user_password=env("DEMO_USER_PASSWORD") or None,
        cookie_secure=_bool(env("COOKIE_SECURE"), False),
        cors_origins=tuple(o.strip() for o in (env("CORS_ORIGINS") or "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_env_files()
    return _from_env()


def reload_settings() -> Settings:
    """Re-read the environment (used by tests and the setup command)."""
    get_settings.cache_clear()
    return get_settings()
