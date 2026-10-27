"""Copy data saved in local-file mode (backend/data) into MongoDB. Optional, run once if you want it.

    cd backend
    .\\.venv\\Scripts\\python.exe -m app.db_import

Copies accounts (users.json, bcrypt hashes and ids unchanged), dataset versions with their raw uploads,
each user's active version and the analysis settings. Nothing in backend/data is changed or deleted.
Skipped when MongoDB already contains dataset versions, so running it twice copies nothing more.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import reload_settings
from .db import DatabaseUnavailable, MongoStore
from .store import DuplicateUser


def import_file_store(store: MongoStore, data_dir: Path) -> int:
    ds_dir = data_dir / "datasets"
    metas = []
    for folder in ds_dir.iterdir() if ds_dir.exists() else []:
        meta_path = folder / "meta.json"
        if meta_path.exists() and (folder / "cleaned.pkl").exists():
            metas.append((json.loads(meta_path.read_text(encoding="utf-8")), folder))
    if store.db.datasets.count_documents({}):
        print("MongoDB already contains dataset versions; import skipped to avoid duplicates.")
        return 0
    n_users = _import_users(store, data_dir)
    if not metas:
        print(f"No local-file dataset versions to import ({n_users} account(s) copied).")
        return 0
    state = json.loads((data_dir / "state.json").read_text(encoding="utf-8")) if (data_dir / "state.json").exists() else {}
    id_map = {}
    for meta, folder in sorted(metas, key=lambda t: t[0]["version"]):
        up = meta.get("source_upload_id")
        if up:
            _import_upload(store, data_dir, up, meta.get("owner_id"))
        cleaned = pd.read_pickle(folder / "cleaned.pkl")
        keep = {k: v for k, v in meta.items() if k not in ("dataset_id", "version", "created_at", "columns")}
        new = store.create_dataset(cleaned, keep)
        id_map[meta["dataset_id"]] = new["dataset_id"]
        print(f"  imported {meta['dataset_id']} -> {new['dataset_id']}  ({meta.get('name')}, {len(cleaned):,} rows)")
    if state.get("active") in id_map:
        store.set_active(id_map[state["active"]])
    for owner, active in (state.get("active_by_user") or {}).items():
        if owner and active in id_map:
            store.set_active(id_map[active], owner)
    settings_path = data_dir / "settings.json"
    if settings_path.exists():
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        store.update_settings(**{k: saved[k] for k in ("min_group_n", "opportunity_min_n", "bayes_m_override") if k in saved})
    print(f"Imported {n_users} account(s) and {len(id_map)} dataset version(s).")
    return len(id_map)


def _import_users(store: MongoStore, data_dir: Path) -> int:
    """Accounts created in file mode keep their id and bcrypt hash, so the same login and dataset ownership
    keep working. An existing MongoDB account with the same email is left unchanged."""
    path = data_dir / "users.json"
    if not path.exists():
        return 0
    copied = 0
    for u in json.loads(path.read_text(encoding="utf-8")).get("users", []):
        if store.get_user(u["id"]):
            continue
        try:
            store.create_user({**u, "token_version": int(u.get("token_version", 0)), "is_demo": bool(u.get("is_demo"))})
            copied += 1
        except DuplicateUser:
            continue
    return copied


def _import_upload(store: MongoStore, data_dir: Path, upload_id: str, dataset_owner: str | None) -> None:
    folder = data_dir / "uploads" / upload_id
    meta_path = folder / "meta.json"
    if not meta_path.exists() or store.db.uploads.find_one({"_id": upload_id}, {"_id": 1}):
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    ext = Path(meta["filename"]).suffix.lower()
    path = folder / f"original{ext}"
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1 << 20):
            digest.update(block)
    uploaded = datetime.fromisoformat(meta["uploaded_at"])
    if uploaded.tzinfo is not None:
        uploaded = uploaded.astimezone(timezone.utc).replace(tzinfo=None)
    summary = meta.get("profile_summary") or {}
    store._record_upload(upload_id, owner_id=meta.get("owner_id") or dataset_owner, filename=meta["filename"], ext=ext,
                         size=path.stat().st_size, sha256=digest.hexdigest(), uploaded_at=uploaded,
                         row_count=summary.get("row_count"), column_count=summary.get("column_count"))


def main() -> int:
    s = reload_settings()
    store = MongoStore(s.mongo_uri, s.mongo_db, s.data_dir, timeout_ms=s.mongo_timeout_ms)
    print(f"Importing local-file data from {s.data_dir} into MongoDB database '{s.mongo_db}' ...")
    try:
        import_file_store(store, s.data_dir)
        return 0
    except DatabaseUnavailable as exc:
        print(f"FAIL: {exc}")
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
