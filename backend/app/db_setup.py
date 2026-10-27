"""One-time MySQL setup for RestaurantIQ.

    cd backend
    python -m app.db_setup                 # prompts for the MySQL root password (not echoed)
    python -m app.db_setup --migrate       # ...and copies existing local-file versions into MySQL

What it does
1. Connects with an administrator account (default: root) to the server in backend/.env
   (RIQ_MYSQL_HOST / RIQ_MYSQL_PORT, default 127.0.0.1:3306).
2. Creates the database (default `restaurantiq`, utf8mb4) and an application user
   (default `riq_app`) that can only access that database. A strong random password is
   generated unless RIQ_MYSQL_PASSWORD is already set in backend/.env.
3. Writes RIQ_STORAGE / RIQ_MYSQL_* to backend/.env (other lines, e.g. ANTHROPIC_API_KEY, are kept).
4. Creates the tables (idempotent) and optionally migrates backend/data versions.

The administrator password is used only for this run and is never written anywhere.
Neither password is printed.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.engine import URL

from .config import BACKEND_DIR, reload_settings
from .db import MySQLStore, datasets, uploads

ENV_PATH = Path(os.environ.get("RIQ_ENV_FILE") or BACKEND_DIR / ".env")  # override only for testing
NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")


def update_env_file(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    missing = [k for k in values if k not in seen]
    if missing:
        out += ["", "# MySQL (written by python -m app.db_setup)"] + [f"{k}={values[k]}" for k in missing]
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def setup(admin_user: str, admin_password: str, migrate: bool) -> int:
    s = reload_settings()
    db_name, app_user = s.mysql_database, s.mysql_user
    if not NAME_RE.match(db_name) or not NAME_RE.match(app_user):
        print("RIQ_MYSQL_DATABASE and RIQ_MYSQL_USER may only contain letters, digits and underscores.")
        return 2
    app_password = s.mysql_password or secrets.token_urlsafe(24)
    admin = create_engine(URL.create("mysql+pymysql", username=admin_user, password=admin_password or None,
                                     host=s.mysql_host, port=s.mysql_port, query={"charset": "utf8mb4"}))
    try:
        with admin.begin() as con:
            version = con.execute(text("SELECT VERSION()")).scalar()
            print(f"Connected to MySQL {version} at {s.mysql_host}:{s.mysql_port} as {admin_user}.")
            con.execute(text(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"))
            for host in ("localhost", "127.0.0.1"):
                con.execute(text(f"CREATE USER IF NOT EXISTS '{app_user}'@'{host}' IDENTIFIED BY :pw"), {"pw": app_password})
                con.execute(text(f"ALTER USER '{app_user}'@'{host}' IDENTIFIED BY :pw"), {"pw": app_password})
                con.execute(text(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{app_user}'@'{host}'"))
            con.execute(text("FLUSH PRIVILEGES"))
    except Exception as exc:  # report without echoing credentials
        msg = str(getattr(exc, "orig", exc)).split("\n")[0]
        print(f"MySQL setup failed: {msg}")
        return 1
    finally:
        admin.dispose()
    print(f"Database `{db_name}` and user '{app_user}' are ready.")

    update_env_file(ENV_PATH, {"RIQ_STORAGE": "mysql", "RIQ_MYSQL_HOST": s.mysql_host, "RIQ_MYSQL_PORT": str(s.mysql_port),
                               "RIQ_MYSQL_USER": app_user, "RIQ_MYSQL_PASSWORD": app_password,
                               "RIQ_MYSQL_DATABASE": db_name})
    os.environ["RIQ_MYSQL_PASSWORD"] = app_password
    os.environ["RIQ_STORAGE"] = "mysql"
    print(f"Saved connection settings to {ENV_PATH} (git-ignored).")

    s = reload_settings()
    store = MySQLStore(s.mysql_url(), s.data_dir)
    health = store.health()
    if not health["connected"]:
        print(f"Could not connect as {app_user}: {health['error']}")
        return 1
    print("Tables created/verified: uploads, datasets, restaurants, restaurant_cuisines, restaurant_types, "
          "cleaning_log, column_quality, app_state.")
    if migrate:
        migrate_file_store(store, s.data_dir)
    return 0


def migrate_file_store(store: MySQLStore, data_dir: Path) -> None:
    """Copy versions from the old local-file store (backend/data/datasets) into MySQL, in version order."""
    ds_dir = data_dir / "datasets"
    metas = []
    for folder in ds_dir.iterdir() if ds_dir.exists() else []:
        meta_path = folder / "meta.json"
        if meta_path.exists() and (folder / "cleaned.pkl").exists():
            metas.append((json.loads(meta_path.read_text(encoding="utf-8")), folder))
    if not metas:
        print("No local-file versions to migrate.")
        return
    with store.engine.begin() as con:
        if con.execute(select(func.count()).select_from(datasets)).scalar():
            print("MySQL already contains dataset versions; migration skipped to avoid duplicates.")
            return
    state = json.loads((data_dir / "state.json").read_text(encoding="utf-8")) if (data_dir / "state.json").exists() else {}
    id_map = {}
    for meta, folder in sorted(metas, key=lambda t: t[0]["version"]):
        up = meta.get("source_upload_id")
        if up:
            _register_upload(store, data_dir, up)
        cleaned = pd.read_pickle(folder / "cleaned.pkl")
        keep = {k: v for k, v in meta.items() if k not in ("dataset_id", "version", "created_at", "columns")}
        new = store.create_dataset(cleaned, keep)
        id_map[meta["dataset_id"]] = new["dataset_id"]
        print(f"  migrated {meta['dataset_id']} -> {new['dataset_id']}  ({meta.get('name')}, {len(cleaned):,} rows)")
    if state.get("active") in id_map:
        store.set_active(id_map[state["active"]])
    settings_path = data_dir / "settings.json"
    if settings_path.exists():
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        store.update_settings(**{k: saved[k] for k in ("min_group_n", "opportunity_min_n", "bayes_m_override") if k in saved})
    print(f"Migrated {len(id_map)} version(s). Active version: {store.active_id()}.")


def _register_upload(store: MySQLStore, data_dir: Path, upload_id: str) -> None:
    folder = data_dir / "uploads" / upload_id
    meta_path = folder / "meta.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    ext = Path(meta["filename"]).suffix.lower()
    path = folder / f"original{ext}"
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1 << 20):
            digest.update(block)
    from datetime import datetime
    with store.engine.begin() as con:
        if con.execute(select(uploads.c.upload_id).where(uploads.c.upload_id == upload_id)).first():
            return
        con.execute(insert(uploads).values(
            upload_id=upload_id, filename=meta["filename"][:255], file_ext=ext, size_bytes=path.stat().st_size,
            sha256=digest.hexdigest(), stored_path=f"uploads/{upload_id}/original{ext}",
            uploaded_at=datetime.fromisoformat(meta["uploaded_at"]).replace(tzinfo=None),
            row_count=(meta.get("profile_summary") or {}).get("row_count"),
            column_count=(meta.get("profile_summary") or {}).get("column_count")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create the RestaurantIQ MySQL database, app user and tables.")
    parser.add_argument("--admin-user", default="root", help="MySQL administrator account (default: root)")
    parser.add_argument("--admin-password-env", metavar="VAR",
                        help="read the administrator password from this environment variable instead of prompting")
    parser.add_argument("--migrate", action="store_true", help="copy existing backend/data versions into MySQL")
    args = parser.parse_args(argv)
    if args.admin_password_env:
        password = os.environ.get(args.admin_password_env, "")
    else:
        password = getpass.getpass(f"MySQL password for '{args.admin_user}' (input hidden): ")
    return setup(args.admin_user, password, args.migrate)


if __name__ == "__main__":
    sys.exit(main())
