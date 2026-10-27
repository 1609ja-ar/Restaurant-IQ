"""File-backed storage for raw uploads, immutable dataset versions and settings.

Layout (under RIQ_DATA_DIR, default backend/data):
  uploads/<upload_id>/original.<ext>   raw bytes exactly as uploaded (never modified)
  uploads/<upload_id>/meta.json        filename, size, profile
  datasets/<dataset_id>/cleaned.pkl    cleaned dataframe (all de-duplicated rows, flags included)
  datasets/<dataset_id>/meta.json      mapping, settings, reconciliation, quality, capabilities
  state.json                           active dataset per user + version counter
  settings.json                        analysis settings (sample thresholds, Bayesian prior)
  users.json                           user accounts (bcrypt password hashes only)

Every import creates a new dataset id (v1, v2, ...); existing versions are never overwritten.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DEFAULT_SETTINGS = {"min_group_n": 10, "opportunity_min_n": 8, "bayes_m_override": None}


def _json_default(value):
    """numpy scalars -> native Python values; anything else -> str (e.g. timestamps)."""
    if hasattr(value, "item") and callable(value.item):
        return value.item()
    return str(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class NotFound(Exception):
    pass


class DuplicateUser(Exception):
    """An account with this email already exists."""


class Store:
    """Local-file backend (used by the test-suite and when RIQ_STORAGE=file)."""
    backend = "file"

    def __init__(self, base: Path | str | None = None):
        self.base = Path(base or os.environ.get("RIQ_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
        (self.base / "uploads").mkdir(parents=True, exist_ok=True)
        (self.base / "datasets").mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self._cache_size = 3

    # ---- json helpers -------------------------------------------------------
    def _read_json(self, path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def _write_json(self, path: Path, data) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=_json_default), encoding="utf-8")
        os.replace(tmp, path)  # atomic on the same filesystem

    # ---- uploads ------------------------------------------------------------
    def save_upload(self, fileobj, filename: str, owner_id: str | None = None) -> tuple[str, Path]:
        """Stream the uploaded file to disk in 1 MB blocks (no full in-memory copy)."""
        upload_id = uuid.uuid4().hex[:12]
        folder = self.base / "uploads" / upload_id
        folder.mkdir(parents=True)
        ext = Path(filename).suffix.lower()
        path = folder / f"original{ext}"
        with open(path, "wb") as out:
            shutil.copyfileobj(fileobj, out, length=1 << 20)
        self._write_json(folder / "meta.json", {"upload_id": upload_id, "filename": filename, "owner_id": owner_id,
                                                "size_bytes": path.stat().st_size, "uploaded_at": _now()})
        return upload_id, path

    def upload_meta(self, upload_id: str) -> dict:
        if not upload_id.isalnum():
            raise NotFound("Upload not found.")
        meta = self._read_json(self.base / "uploads" / upload_id / "meta.json", None)
        if meta is None:
            raise NotFound("Upload not found. It may have expired; please upload the file again.")
        return meta

    def upload_path(self, upload_id: str) -> Path:
        meta = self.upload_meta(upload_id)
        return self.base / "uploads" / upload_id / f"original{Path(meta['filename']).suffix.lower()}"

    def verify_upload(self, upload_id: str) -> Path:
        return self.upload_path(upload_id)

    def health(self) -> dict:
        return {"backend": "file", "connected": True, "path": str(self.base)}

    def update_upload_meta(self, upload_id: str, **fields) -> None:
        meta = self.upload_meta(upload_id)
        meta.update(fields)
        self._write_json(self.base / "uploads" / upload_id / "meta.json", meta)

    def delete_upload(self, upload_id: str) -> None:
        if upload_id.isalnum():
            shutil.rmtree(self.base / "uploads" / upload_id, ignore_errors=True)

    # ---- dataset versions ---------------------------------------------------
    def _state(self) -> dict:
        state = self._read_json(self.base / "state.json", {"active": None, "counter": 0})
        state.setdefault("active_by_user", {})
        return state

    def create_dataset(self, cleaned: pd.DataFrame, meta: dict) -> dict:
        with self._lock:
            state = self._state()
            state["counter"] += 1
            dataset_id = f"v{state['counter']}"
            folder = self.base / "datasets" / dataset_id
            folder.mkdir(parents=True, exist_ok=False)
            cleaned.to_pickle(folder / "cleaned.pkl")
            meta = {**meta, "dataset_id": dataset_id, "version": state["counter"], "created_at": _now()}
            self._write_json(folder / "meta.json", meta)
            state["active_by_user"][meta.get("owner_id") or ""] = dataset_id
            self._write_json(self.base / "state.json", state)
            return meta

    def list_datasets(self, owner_id: str | None = None) -> list[dict]:
        out = []
        for folder in (self.base / "datasets").iterdir():
            meta = self._read_json(folder / "meta.json", None)
            if meta and (owner_id is None or meta.get("owner_id") == owner_id):
                out.append({k: meta.get(k) for k in ("dataset_id", "version", "name", "created_at", "is_demo",
                                                     "source_filename")}
                           | {"rows_used": meta.get("reconciliation", {}).get("rows_used_in_analysis")})
        return sorted(out, key=lambda m: -m["version"])

    def dataset_meta(self, dataset_id: str) -> dict:
        if not dataset_id or not dataset_id[1:].isdigit():
            raise NotFound("Dataset version not found.")
        meta = self._read_json(self.base / "datasets" / dataset_id / "meta.json", None)
        if meta is None:
            raise NotFound(f"Dataset version '{dataset_id}' not found.")
        return meta

    def load_cleaned(self, dataset_id: str) -> pd.DataFrame:
        with self._lock:
            if dataset_id in self._cache:
                self._cache.move_to_end(dataset_id)
                return self._cache[dataset_id]
        self.dataset_meta(dataset_id)
        df = pd.read_pickle(self.base / "datasets" / dataset_id / "cleaned.pkl")
        with self._lock:
            self._cache[dataset_id] = df
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return df

    def active_id(self, owner_id: str | None = None) -> str | None:
        state = self._state()
        active = state["active_by_user"].get(owner_id or "")
        if active and (self.base / "datasets" / active / "meta.json").exists():
            return active
        return None

    def set_active(self, dataset_id: str, owner_id: str | None = None) -> None:
        with self._lock:
            self.dataset_meta(dataset_id)
            state = self._state()
            state["active_by_user"][owner_id or ""] = dataset_id
            self._write_json(self.base / "state.json", state)

    def claim_unowned(self, owner_id: str) -> list[str]:
        """Give datasets/uploads created before accounts existed to this user (done once)."""
        claimed = []
        with self._lock:
            for folder in (self.base / "datasets").iterdir():
                meta = self._read_json(folder / "meta.json", None)
                if meta and not meta.get("owner_id"):
                    meta["owner_id"] = owner_id
                    self._write_json(folder / "meta.json", meta)
                    claimed.append(meta["dataset_id"])
            for folder in (self.base / "uploads").iterdir():
                meta = self._read_json(folder / "meta.json", None)
                if meta and not meta.get("owner_id"):
                    meta["owner_id"] = owner_id
                    self._write_json(folder / "meta.json", meta)
            state = self._state()
            legacy = state.get("active")
            if claimed and legacy in claimed and not state["active_by_user"].get(owner_id):
                state["active_by_user"][owner_id] = legacy
                self._write_json(self.base / "state.json", state)
        return claimed

    # ---- users -----------------------------------------------------------------
    def _users(self) -> list[dict]:
        return self._read_json(self.base / "users.json", {"users": []})["users"]

    def create_user(self, user: dict) -> dict:
        with self._lock:
            users = self._users()
            if any(u["email"] == user["email"] for u in users):
                raise DuplicateUser(user["email"])
            users.append(user)
            self._write_json(self.base / "users.json", {"users": users})
        return user

    def get_user(self, user_id: str) -> dict | None:
        return next((u for u in self._users() if u["id"] == user_id), None)

    def get_user_by_email(self, email: str) -> dict | None:
        return next((u for u in self._users() if u["email"] == email), None)

    def update_user(self, user_id: str, **fields) -> None:
        with self._lock:
            users = self._users()
            for u in users:
                if u["id"] == user_id:
                    u.update(fields)
            self._write_json(self.base / "users.json", {"users": users})

    def count_users(self) -> int:
        return len(self._users())

    def resolve(self, dataset_id: str | None) -> str:
        ds = dataset_id or self.active_id()
        if not ds:
            raise NotFound("No dataset is loaded yet. Load the sample dataset or import a file on the Data page.")
        self.dataset_meta(ds)
        return ds

    # ---- settings -------------------------------------------------------------
    def settings(self) -> dict:
        s = self._read_json(self.base / "settings.json", {})
        merged = {**DEFAULT_SETTINGS, **{k: v for k, v in s.items() if k in DEFAULT_SETTINGS}}
        merged["revision"] = s.get("revision", 0)
        return merged

    def update_settings(self, **changes) -> dict:
        with self._lock:
            current = self.settings()
            current.update(changes)
            current["revision"] = current.get("revision", 0) + 1
            self._write_json(self.base / "settings.json", current)
            return current
