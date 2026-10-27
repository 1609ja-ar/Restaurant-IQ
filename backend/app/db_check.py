"""Check the MongoDB connection the backend will use, and say exactly what is wrong.

    cd backend
    .\\.venv\\Scripts\\python.exe -m app.db_check

Prints the settings (never the password), connects, creates any missing collections/indexes (the same
idempotent step the backend runs on startup), then prints OK or FAIL with the reason and the fix.
Exit code 0 = OK, 1 = failure.
"""
from __future__ import annotations

import logging
import re
import sys

from pymongo.errors import OperationFailure

from .config import reload_settings
from .db import INDEXES, MIN_SERVER_VERSION, DatabaseUnavailable, MongoStore, _redact, classify_db_error, redact_uri


def check() -> int:
    logging.getLogger("restaurantiq.db").setLevel(logging.ERROR)   # the result below already explains failures
    s = reload_settings()
    print("RestaurantIQ MongoDB connection check")
    print(f"  storage  : {s.storage}" + ("   (RIQ_STORAGE=file: the backend is NOT using MongoDB)" if s.storage == "file" else ""))
    print(f"  uri      : {redact_uri(s.mongo_uri)}")
    print(f"  database : {s.mongo_db}")
    print(f"  timeout  : {s.mongo_timeout_ms} ms")

    if s.storage == "file":
        print("OK: Using local file storage (RIQ_STORAGE=file). MongoDB is not needed.")
        return 0

    store = MongoStore(s.mongo_uri, s.mongo_db, s.data_dir, timeout_ms=s.mongo_timeout_ms)
    try:
        # 1. Reach the server and sign in (the first command does both).
        try:
            created = store.ensure_indexes()
            info = store._client.server_info()
        except DatabaseUnavailable as exc:
            cause = exc.__cause__
            kind = classify_db_error(cause) if cause else "other"
            print(f"FAIL ({kind.replace('_', ' ')}): {exc}")
            if isinstance(cause, OperationFailure):   # server error: its code name says it exactly
                print(f"  detail   : {(cause.details or {}).get('codeName', 'OperationFailure')} (code {cause.code})")
            elif cause:   # first part of the driver message (host, port and reason), password removed
                detail = re.split(r" \(configured timeouts|, Timeout:", str(cause))[0]
                print(f"  detail   : {type(cause).__name__}: {_redact(detail, s.mongo_uri)[:200]}")
            return 1

        # 2. Server version.
        version = info.get("version", "?")
        parts = tuple(int(p) for p in version.split(".")[:2] if p.isdigit())
        if parts and parts < MIN_SERVER_VERSION:
            print(f"FAIL (server too old): MongoDB {version} is running, but RestaurantIQ needs "
                  f"{'.'.join(map(str, MIN_SERVER_VERSION))} or newer. Install a current MongoDB Community Server.")
            return 1

        # 3. Collections and indexes.
        db = store.db
        present = set(db.list_collection_names())
        missing = [f"{coll}.{m.document['name']}" for coll, models in INDEXES.items() if coll in present
                   for m in models if m.document["name"] not in db[coll].index_information()]
        missing += [coll for coll in INDEXES if coll not in present]
        if missing:
            print(f"FAIL (indexes missing): could not create {', '.join(missing)}. Check that the user in "
                  "RIQ_MONGO_URI has the readWrite role on this database.")
            return 1
        n_indexes = sum(len(m) for m in INDEXES.values())
        users, versions = db.users.count_documents({}), db.datasets.count_documents({})
        if created:
            print(f"  created  : {', '.join(created)}")
        print(f"OK: connected to MongoDB {version}; database '{s.mongo_db}' has all {len(INDEXES)} collections and "
              f"{n_indexes} indexes ({users} account(s), {versions} dataset version(s)).")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(check())
