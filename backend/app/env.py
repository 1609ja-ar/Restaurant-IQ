"""Minimal .env loader (avoids an extra dependency).

Looks for backend/.env, then the project-root .env. Existing environment variables win.
Values are never logged.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env() -> None:
    here = Path(__file__).resolve().parent
    for path in (here.parent / ".env", here.parent.parent / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value
