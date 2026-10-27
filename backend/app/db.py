"""MongoDB storage: the database of record for RestaurantIQ.

What lives where
* MongoDB (this module): user accounts, upload records, immutable dataset versions, every cleaned restaurant
  row with its quality flags (cuisines and restaurant types as arrays), the cleaning log, the per-column
  quality report, analysis settings and the active version of each user.
* Disk (RIQ_DATA_DIR/uploads): the raw uploaded file, byte-for-byte. Files can be very large and must stay
  unmodified, so MongoDB stores their path, size and SHA-256 checksum instead of the bytes; the checksum is
  verified before the raw file is served.

``MongoStore`` exposes the same methods as ``store.Store`` (the file backend used by tests), so the API layer
does not care which backend is active. KPIs and statistics are computed in pandas on the loaded dataset.

Collections and indexes (created on startup by ``ensure_indexes``; idempotent):
  users           _id = user id;            unique email
  uploads         _id = upload id;          owner_id
  datasets        _id = "v1", "v2", ...;    unique version, (owner_id, version), source_upload_id
  restaurants     one document per row;     unique (dataset_id, rid), (dataset_id, include_in_analysis),
                                            (dataset_id, location), (dataset_id, cuisines), (dataset_id, restaurant_type)
  cleaning_log    one document per step;    unique (dataset_id, step_no)
  column_quality  one document per column;  unique (dataset_id, column_name)
  app_state       _id = key;                version_counter, active_dataset:<user id>, settings
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import threading
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import pandas as pd
from pymongo import ASCENDING, DESCENDING, IndexModel, MongoClient, ReturnDocument
from pymongo.errors import (AutoReconnect, CollectionInvalid, ConfigurationError, ConnectionFailure,
                            DuplicateKeyError, InvalidName, InvalidURI, OperationFailure, PyMongoError)

from .store import DEFAULT_SETTINGS, DuplicateUser, NotFound

log = logging.getLogger("restaurantiq.db")
INSERT_CHUNK = 2000
MIN_SERVER_VERSION = (5, 0)   # field names containing "." or "$" (source column names) need MongoDB 5.0+


class DatabaseUnavailable(Exception):
    """MongoDB is not configured or not reachable (message is safe to show)."""


INDEXES: dict[str, list[IndexModel]] = {
    "users": [IndexModel([("email", ASCENDING)], unique=True, name="ux_users_email")],
    "uploads": [IndexModel([("owner_id", ASCENDING)], name="ix_uploads_owner")],
    "datasets": [
        IndexModel([("version", ASCENDING)], unique=True, name="ux_datasets_version"),
        IndexModel([("owner_id", ASCENDING), ("version", DESCENDING)], name="ix_datasets_owner_version"),
        IndexModel([("source_upload_id", ASCENDING)], name="ix_datasets_upload"),
    ],
    "restaurants": [
        IndexModel([("dataset_id", ASCENDING), ("rid", ASCENDING)], unique=True, name="ux_restaurants_dataset_rid"),
        IndexModel([("dataset_id", ASCENDING), ("include_in_analysis", ASCENDING)], name="ix_restaurants_analysis"),
        IndexModel([("dataset_id", ASCENDING), ("location", ASCENDING)], name="ix_restaurants_location"),
        IndexModel([("dataset_id", ASCENDING), ("cuisines", ASCENDING)], name="ix_restaurants_cuisines"),
        IndexModel([("dataset_id", ASCENDING), ("restaurant_type", ASCENDING)], name="ix_restaurants_types"),
    ],
    "cleaning_log": [IndexModel([("dataset_id", ASCENDING), ("step_no", ASCENDING)], unique=True,
                                name="ux_cleaning_log_step")],
    "column_quality": [IndexModel([("dataset_id", ASCENDING), ("column_name", ASCENDING)], unique=True,
                                  name="ux_column_quality_column")],
    "app_state": [],
}
COLLECTIONS = list(INDEXES)

# Canonical restaurant fields stored as top-level document fields (everything else goes to extra_columns).
INT_COLUMNS = ["rid", "source_row"]
FLOAT_COLUMNS = ["rating", "rating_source", "review_count", "cost", "latitude", "longitude"]
FLAG_COLUMNS = ["is_unrated", "rating_invalid", "votes_invalid", "cost_invalid", "is_invalid", "cost_outlier",
                "include_in_analysis"]
NULLABLE_BOOL = ["online_order", "table_booking"]
TEXT_COLUMNS = ["restaurant_name", "address", "location", "locality", "city", "region", "country", "rating_raw",
                "review_count_raw", "cost_raw", "currency", "price_tier", "review_text", "menu_items",
                "opening_hours", "invalid_reason"]
LIST_COLUMNS = ["cuisines", "restaurant_type"]
FIXED_COLUMNS = INT_COLUMNS + FLOAT_COLUMNS + FLAG_COLUMNS + NULLABLE_BOOL + TEXT_COLUMNS + ["source_date"]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _iso(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")


def _py(v):
    """numpy / pandas value -> plain Python value BSON accepts; NaN/NaT -> None; nested dicts/lists converted."""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, dict):
        return {str(k): _py(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, np.ndarray)):
        return [_py(x) for x in v]
    if isinstance(v, pd.Timestamp):
        return v.tz_convert("UTC").tz_localize(None).to_pydatetime() if v.tzinfo else v.to_pydatetime()
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


def _meta_out(meta: dict) -> dict:
    """Meta as the API layer expects it: datetimes rendered as ISO text (they are stored as BSON dates)."""
    return {k: (_iso(v) if isinstance(v, datetime) else v) for k, v in meta.items()}


# ---------------------------------------------------------------------------
# Connection string helpers (the password is never shown)
# ---------------------------------------------------------------------------
def _split_uri(uri: str) -> tuple[str | None, str | None, str | None, str]:
    """(scheme, user, password, rest after the credentials). Credentials end at the LAST "@", so a password
    that was not URL-encoded (contains @ : / #) is still treated as a whole and never partly shown."""
    m = re.match(r"^(mongodb(?:\+srv)?)://(.*)$", (uri or "").strip(), re.S)
    if not m:
        return None, None, None, uri or ""
    scheme, rest = m.groups()
    if "@" not in rest:
        return scheme, None, None, rest
    creds, _, after = rest.rpartition("@")
    user, sep, pw = creds.partition(":")
    return scheme, user, (pw if sep else None), after


def describe_uri(uri: str) -> dict:
    """scheme, user and hosts of a MongoDB URI, parsed without DNS lookups (mongodb+srv is not resolved)."""
    scheme, user, pw, after = _split_uri(uri)
    if scheme is None:
        return {"scheme": None, "user": None, "hosts": "?", "has_password": False}
    hosts = re.split(r"[/?]", after, maxsplit=1)[0]
    return {"scheme": scheme, "user": unquote(user) if user else None, "hosts": hosts or "?", "has_password": bool(pw)}


def redact_uri(uri: str) -> str:
    """The URI with the password replaced by ****, safe to print."""
    scheme, user, pw, after = _split_uri(uri)
    if scheme is None or pw is None:
        return uri or ""
    return f"{scheme}://{user}:****@{after}"


def _redact(text: str, uri: str) -> str:
    """Removes the password from a driver message (defence in depth: driver messages do not contain it)."""
    pw = _split_uri(uri)[2]
    if pw and len(pw) >= 4:          # shorter strings would also match ordinary words
        for secret in {pw, unquote(pw)}:
            text = text.replace(secret, "****")
    return text


class MongoStore:
    backend = "mongodb"

    def __init__(self, uri: str, db_name: str, data_dir: Path | str, timeout_ms: int = 5000):
        self.uri = uri
        self.db_name = db_name
        self.timeout_ms = timeout_ms
        self.base = Path(data_dir)
        (self.base / "uploads").mkdir(parents=True, exist_ok=True)
        self._client: MongoClient | None = None
        self._lock = threading.RLock()
        self._cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self._cache_size = 3
        self._indexes_ready = False

    # ---- connection -----------------------------------------------------------
    @contextmanager
    def _guard(self):
        """Turns driver errors into DatabaseUnavailable with a friendly message (duplicate keys pass through)."""
        try:
            yield
        except DuplicateKeyError:
            raise
        except PyMongoError as exc:
            log.warning("MongoDB error (%s): %s", type(exc).__name__, _redact(str(exc), self.uri)[:300])
            raise DatabaseUnavailable(friendly_db_error(exc, self.uri, self.db_name)) from exc

    def _database(self):
        if self._client is None:
            # The client connects lazily; the first operation fails after timeout_ms if the server is down.
            try:
                self._client = MongoClient(self.uri, serverSelectionTimeoutMS=self.timeout_ms,
                                           connectTimeoutMS=self.timeout_ms, appname="restaurantiq", tz_aware=False)
            except (ValueError, TypeError) as exc:   # e.g. a password with an unencoded @ or : (port parse error)
                raise InvalidURI(str(exc)) from exc
        return self._client[self.db_name]

    @property
    def db(self):
        """The database, with collections and indexes created on first use."""
        with self._guard():
            db = self._database()
            if not self._indexes_ready:
                self._create_indexes(db)
        return db

    def _create_indexes(self, db) -> list[str]:
        """Creates missing collections and indexes. Existing ones are left unchanged. Returns names created."""
        created = []
        existing_collections = set(db.list_collection_names())
        for name, models in INDEXES.items():
            if name not in existing_collections:
                try:
                    db.create_collection(name)
                except CollectionInvalid:
                    pass   # created by another worker in the meantime
            have = set(db[name].index_information())
            todo = [m for m in models if m.document["name"] not in have]
            if todo:
                db[name].create_indexes(todo)
                created += [m.document["name"] for m in todo]
        self._indexes_ready = True
        return created

    def ensure_indexes(self) -> list[str]:
        """Startup step: create collections/indexes now (instead of on the first request)."""
        with self._guard():
            return self._create_indexes(self._database())

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._indexes_ready = False

    def health(self) -> dict:
        try:
            with self._guard():
                db = self.db
                version = self._client.server_info()["version"]
                n = db.datasets.count_documents({})
            return {"backend": "mongodb", "connected": True, "server_version": version,
                    "database": self.db_name, "dataset_versions": int(n)}
        except DatabaseUnavailable as exc:
            return {"backend": "mongodb", "connected": False, "error": str(exc)}

    # ---- uploads --------------------------------------------------------------
    def save_upload(self, fileobj, filename: str, owner_id: str | None = None) -> tuple[str, Path]:
        """Stream the file to disk in 1 MB blocks while hashing it, then record it in MongoDB."""
        upload_id = uuid.uuid4().hex[:12]
        folder = self.base / "uploads" / upload_id
        folder.mkdir(parents=True)
        ext = Path(filename).suffix.lower()
        path = folder / f"original{ext}"
        digest = hashlib.sha256()
        with open(path, "wb") as out:
            while block := fileobj.read(1 << 20):
                digest.update(block)
                out.write(block)
        try:
            self._record_upload(upload_id, owner_id=owner_id, filename=filename, ext=ext, size=path.stat().st_size,
                                sha256=digest.hexdigest(), uploaded_at=_now())
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return upload_id, path

    def _record_upload(self, upload_id: str, *, owner_id, filename, ext, size, sha256, uploaded_at,
                       row_count=None, column_count=None) -> None:
        with self._guard():
            self.db.uploads.insert_one({
                "_id": upload_id, "owner_id": owner_id, "filename": filename[:255], "file_ext": ext[:10],
                "size_bytes": size, "sha256": sha256, "stored_path": f"uploads/{upload_id}/original{ext}",
                "row_count": row_count, "column_count": column_count, "uploaded_at": uploaded_at})

    def upload_meta(self, upload_id: str) -> dict:
        if not upload_id.isalnum():
            raise NotFound("Upload not found.")
        with self._guard():
            doc = self.db.uploads.find_one({"_id": upload_id})
        if doc is None:
            raise NotFound("Upload not found. It may have expired; please upload the file again.")
        meta = {"upload_id": doc.pop("_id"), **doc, "uploaded_at": _iso(doc["uploaded_at"])}
        if meta.get("row_count") is not None:
            meta["profile_summary"] = {"row_count": meta["row_count"], "column_count": meta["column_count"]}
        return meta

    def upload_path(self, upload_id: str) -> Path:
        return self.base / self.upload_meta(upload_id)["stored_path"]

    def verify_upload(self, upload_id: str) -> Path:
        """Raw file path, after checking it still matches the checksum recorded at upload time."""
        meta = self.upload_meta(upload_id)
        path = self.base / meta["stored_path"]
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            while block := fh.read(1 << 20):
                digest.update(block)
        if digest.hexdigest() != meta["sha256"]:
            raise NotFound("The stored original file no longer matches its checksum; it may have been modified.")
        return path

    def update_upload_meta(self, upload_id: str, **fields) -> None:
        summary = fields.get("profile_summary") or {}
        with self._guard():
            self.db.uploads.update_one({"_id": upload_id}, {"$set": {
                "row_count": summary.get("row_count"), "column_count": summary.get("column_count")}})

    def delete_upload(self, upload_id: str) -> None:
        if not upload_id.isalnum():
            return
        with self._guard():
            if self.db.datasets.find_one({"source_upload_id": upload_id}, {"_id": 1}):
                return  # referenced by a dataset version: keep it
            self.db.uploads.delete_one({"_id": upload_id})
        shutil.rmtree(self.base / "uploads" / upload_id, ignore_errors=True)

    # ---- state helpers ---------------------------------------------------------
    def _get_state(self, key, default=None):
        with self._guard():
            doc = self.db.app_state.find_one({"_id": key})
        return default if doc is None or doc.get("v") is None else doc["v"]

    def _set_state(self, key, value) -> None:
        with self._guard():
            self.db.app_state.update_one({"_id": key}, {"$set": {"v": value}}, upsert=True)

    def _next_version(self) -> int:
        """Atomic counter, so two imports at the same moment never get the same version number."""
        with self._guard():
            db = self.db
            latest = db.datasets.find_one({}, {"version": 1}, sort=[("version", DESCENDING)])
            if latest:   # never reuse a number, even if the counter document was removed
                db.app_state.update_one({"_id": "version_counter"}, {"$max": {"v": int(latest["version"])}},
                                        upsert=True)
            doc = db.app_state.find_one_and_update({"_id": "version_counter"}, {"$inc": {"v": 1}}, upsert=True,
                                                   return_document=ReturnDocument.AFTER)
        return int(doc["v"])

    # ---- dataset versions -------------------------------------------------------
    def create_dataset(self, cleaned: pd.DataFrame, meta: dict) -> dict:
        """Writes the rows, log and quality report first and the datasets document last, so a version only
        becomes visible once it is complete (a standalone MongoDB has no multi-document transactions)."""
        meta = _py(meta)
        version = self._next_version()
        dataset_id = f"v{version}"
        created = _now()
        rec = meta.get("reconciliation", {})
        meta = {**meta, "dataset_id": dataset_id, "version": version, "created_at": _iso(created),
                "columns": [str(c) for c in cleaned.columns]}
        try:
            with self._guard():
                db = self.db
                self._insert_rows(db, dataset_id, cleaned)
                if meta.get("log"):
                    db.cleaning_log.insert_many([
                        {"dataset_id": dataset_id, "step_no": i + 1, "step": str(e["step"])[:120],
                         "detail": e["detail"], "rows_affected": e.get("rows")} for i, e in enumerate(meta["log"])])
                if meta.get("quality"):
                    db.column_quality.insert_many([
                        {"dataset_id": dataset_id, "column_name": q["column"], "canonical_field": q["field"],
                         "completeness_pct": q["completeness_pct"], "uniqueness_pct": q["uniqueness_pct"],
                         "validity_pct": q["validity_pct"], "non_null": q["non_null"], "valid_count": q["valid"],
                         "note": q["note"]} for q in meta["quality"]])
                db.datasets.insert_one({
                    "_id": dataset_id, "version": version, "name": str(meta.get("name") or dataset_id)[:255],
                    "is_demo": bool(meta.get("is_demo")), "source_filename": meta.get("source_filename"),
                    "source_upload_id": meta.get("source_upload_id"), "file_type": meta.get("file_type"),
                    "owner_id": meta.get("owner_id"), "raw_rows": int(rec.get("raw_rows", len(cleaned))),
                    "rows_used": int(rec.get("rows_used_in_analysis", 0)), "created_at": created, "meta": meta})
        except Exception:
            self._discard_rows(dataset_id)
            raise
        self._set_state(_active_key(meta.get("owner_id")), dataset_id)
        return meta

    def _discard_rows(self, dataset_id: str) -> None:
        try:
            db = self.db
            for name in ("restaurants", "cleaning_log", "column_quality"):
                db[name].delete_many({"dataset_id": dataset_id})
        except (PyMongoError, DatabaseUnavailable):
            log.warning("Could not remove the partial rows of %s; they are ignored (no datasets document).", dataset_id)

    def _insert_rows(self, db, dataset_id: str, cleaned: pd.DataFrame) -> None:
        fixed = [c for c in FIXED_COLUMNS if c in cleaned.columns]
        lists = [c for c in LIST_COLUMNS if c in cleaned.columns]
        extras = [c for c in cleaned.columns if c not in FIXED_COLUMNS and c not in LIST_COLUMNS]
        base = cleaned[fixed].astype(object).where(cleaned[fixed].notna(), None).to_dict(orient="records")
        extra_records = (cleaned[extras].astype(object).where(cleaned[extras].notna(), None).to_dict(orient="records")
                         if extras else None)
        flags = {c: cleaned[c].astype(bool).to_numpy() for c in FLAG_COLUMNS if c in cleaned}
        batch = []
        for i, rec in enumerate(base):
            # None values are left out of the document (missing field = NULL); lists are stored as arrays.
            doc = {"dataset_id": dataset_id}
            doc.update({k: v for k, v in ((k, _py(v)) for k, v in rec.items()) if v is not None})
            for c in FLAG_COLUMNS:
                doc[c] = bool(flags[c][i]) if c in flags else False
            for c in lists:
                items = cleaned[c].iat[i]
                if isinstance(items, (list, tuple, np.ndarray)):
                    doc[c] = [str(v) for v in items]
            if extra_records:
                doc["extra_columns"] = {str(k): _py(v) for k, v in extra_records[i].items()}
            batch.append(doc)
            if len(batch) >= INSERT_CHUNK:
                db.restaurants.insert_many(batch, ordered=False)
                batch = []
        if batch:
            db.restaurants.insert_many(batch, ordered=False)

    def list_datasets(self, owner_id: str | None = None) -> list[dict]:
        query = {} if owner_id is None else {"owner_id": owner_id}
        fields = {"version": 1, "name": 1, "created_at": 1, "is_demo": 1, "source_filename": 1, "rows_used": 1}
        with self._guard():
            docs = list(self.db.datasets.find(query, fields).sort("version", DESCENDING))
        return [{"dataset_id": d["_id"], "version": d["version"], "name": d["name"], "created_at": _iso(d["created_at"]),
                 "is_demo": bool(d.get("is_demo")), "source_filename": d.get("source_filename"),
                 "rows_used": d.get("rows_used")} for d in docs]

    def dataset_meta(self, dataset_id: str) -> dict:
        if not dataset_id or not dataset_id[1:].isdigit():
            raise NotFound("Dataset version not found.")
        with self._guard():
            doc = self.db.datasets.find_one({"_id": dataset_id}, {"meta": 1})
        if doc is None:
            raise NotFound(f"Dataset version '{dataset_id}' not found.")
        return _meta_out(doc["meta"])

    def load_cleaned(self, dataset_id: str) -> pd.DataFrame:
        with self._lock:
            if dataset_id in self._cache:
                self._cache.move_to_end(dataset_id)
                return self._cache[dataset_id]
        meta = self.dataset_meta(dataset_id)
        with self._guard():
            docs = list(self.db.restaurants.find({"dataset_id": dataset_id}, {"_id": 0, "dataset_id": 0})
                        .sort("rid", ASCENDING).batch_size(10_000))
        df = self._to_frame(docs, meta.get("columns") or [])
        with self._lock:
            self._cache[dataset_id] = df
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return df

    @staticmethod
    def _to_frame(docs: list[dict], columns: list[str]) -> pd.DataFrame:
        frame = pd.DataFrame(docs).reindex(columns=FIXED_COLUMNS + LIST_COLUMNS + ["extra_columns"])
        out = pd.DataFrame(index=range(len(frame)))
        for c in INT_COLUMNS:
            out[c] = frame[c].astype("int64")
        for c in FLOAT_COLUMNS:
            out[c] = pd.to_numeric(frame[c], errors="coerce").astype(float)
        for c in FLAG_COLUMNS:
            out[c] = frame[c].eq(True)
        for c in NULLABLE_BOOL:
            out[c] = frame[c].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else bool(v)).astype(object)
        out["source_date"] = pd.to_datetime(frame["source_date"])
        for c in TEXT_COLUMNS:
            out[c] = frame[c].astype(object).where(frame[c].notna(), None)
        for c in LIST_COLUMNS:
            out[c] = frame[c].map(lambda v: v if isinstance(v, list) else None).astype(object)
        extras = [c for c in columns if c not in out.columns]
        if extras:
            ex = [v if isinstance(v, dict) else {} for v in frame["extra_columns"]]
            for name in extras:   # built as object directly: Series.map would turn None into NaN in numeric columns
                out[name] = pd.Series([d.get(name) for d in ex], dtype=object)
        keep = [c for c in columns if c in out.columns]
        return out[keep].reset_index(drop=True)

    def active_id(self, owner_id: str | None = None) -> str | None:
        active = self._get_state(_active_key(owner_id))
        if active:
            with self._guard():
                if self.db.datasets.find_one({"_id": active}, {"_id": 1}):
                    return active
        return None

    def set_active(self, dataset_id: str, owner_id: str | None = None) -> None:
        self.dataset_meta(dataset_id)
        self._set_state(_active_key(owner_id), dataset_id)

    def claim_unowned(self, owner_id: str) -> list[str]:
        """Give datasets/uploads created before accounts existed to this user (done once)."""
        with self._guard():
            db = self.db
            ids = [d["_id"] for d in db.datasets.find({"owner_id": None}, {"_id": 1})]
            if not ids:
                return []
            db.uploads.update_many({"owner_id": None}, {"$set": {"owner_id": owner_id}})
            db.datasets.update_many({"_id": {"$in": ids}}, {"$set": {"owner_id": owner_id, "meta.owner_id": owner_id}})
        legacy = self._get_state("active_dataset")
        if legacy in ids and not self._get_state(_active_key(owner_id)):
            self._set_state(_active_key(owner_id), legacy)
        self._cache.clear()
        return ids

    # ---- users -----------------------------------------------------------------
    def create_user(self, user: dict) -> dict:
        created = datetime.fromisoformat(user["created_at"])
        if created.tzinfo is not None:
            created = created.astimezone(timezone.utc).replace(tzinfo=None)
        doc = {"_id": user["id"], **{k: user[k] for k in ("name", "email", "password_hash", "token_version", "is_demo")},
               "created_at": created}
        try:
            with self._guard():
                self.db.users.insert_one(doc)
        except DuplicateKeyError as exc:   # unique index on email
            raise DuplicateUser(user["email"]) from exc
        return user

    def _user(self, query: dict) -> dict | None:
        with self._guard():
            doc = self.db.users.find_one(query)
        if doc is None:
            return None
        return {"id": doc.pop("_id"), **doc, "is_demo": bool(doc.get("is_demo")),
                "token_version": int(doc.get("token_version", 0)), "created_at": _iso(doc["created_at"])}

    def get_user(self, user_id: str) -> dict | None:
        return self._user({"_id": user_id})

    def get_user_by_email(self, email: str) -> dict | None:
        return self._user({"email": email})

    def update_user(self, user_id: str, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("name", "password_hash", "token_version")}
        if allowed:
            with self._guard():
                self.db.users.update_one({"_id": user_id}, {"$set": allowed})

    def count_users(self) -> int:
        with self._guard():
            return int(self.db.users.count_documents({}))

    def resolve(self, dataset_id: str | None) -> str:
        ds = dataset_id or self.active_id()
        if not ds:
            raise NotFound("No dataset is loaded yet. Load the sample dataset or import a file on the Data page.")
        self.dataset_meta(ds)
        return ds

    # ---- settings -----------------------------------------------------------------
    def settings(self) -> dict:
        s = self._get_state("settings", {})
        merged = {**DEFAULT_SETTINGS, **{k: v for k, v in s.items() if k in DEFAULT_SETTINGS}}
        merged["revision"] = s.get("revision", 0)
        return merged

    def update_settings(self, **changes) -> dict:
        with self._lock:
            current = self.settings()
            current.update(changes)
            current["revision"] = current.get("revision", 0) + 1
            self._set_state("settings", current)
            return current


def _active_key(owner_id: str | None) -> str:
    return f"active_dataset:{owner_id}" if owner_id else "active_dataset"


# ---------------------------------------------------------------------------
# Error explanations
# ---------------------------------------------------------------------------
_AUTH_CODES = {18, 8000}        # AuthenticationFailed; Atlas "bad auth"
_PRIVILEGE_CODES = {13}         # Unauthorized


def classify_db_error(exc: Exception) -> str:
    """Kind of MongoDB failure: not_running, unknown_host, tls, auth_failed, no_privileges, bad_uri, bad_db_name,
    connection_lost or other. Uses the exception type and server error code."""
    text = str(exc)
    if isinstance(exc, InvalidName):
        return "bad_db_name"
    if isinstance(exc, InvalidURI):
        return "bad_uri"
    if isinstance(exc, ConfigurationError):   # includes mongodb+srv DNS failures
        return "unknown_host" if re.search(r"DNS|resolution lifetime|does not exist|getaddrinfo", text) else "bad_uri"
    if isinstance(exc, OperationFailure):
        if exc.code in _AUTH_CODES or "Authentication failed" in text or "bad auth" in text:
            return "auth_failed"
        if "requires authentication" in text:
            return "auth_required"
        if exc.code in _PRIVILEGE_CODES or "not authorized" in text:
            return "no_privileges"
        return "other"
    if isinstance(exc, ConnectionFailure):
        if re.search(r"getaddrinfo failed|Name or service not known|nodename nor servname|No address associated", text):
            return "unknown_host"
        if re.search(r"SSL|TLS|certificate", text):
            return "tls"
        if type(exc) is AutoReconnect:     # was connected, then the connection dropped
            return "connection_lost"
        return "not_running"
    return "other"


def friendly_db_error(exc: Exception, uri: str, db_name: str) -> str:
    """User-facing explanation and fix. Never includes the password: only scheme, user and host are used."""
    kind = classify_db_error(exc)
    info = describe_uri(uri)
    hosts = info["hosts"]
    if kind == "not_running":
        return (f"Cannot reach MongoDB at {hosts}: the server is not running or listens on another port. Start the "
                "MongoDB service (services.msc -> MongoDB Server -> Start, or as administrator: net start MongoDB) "
                "and check RIQ_MONGO_URI in backend/.env.")
    if kind == "unknown_host":
        return (f"The MongoDB host '{hosts}' in RIQ_MONGO_URI could not be found. Check the address in backend/.env "
                "(for MongoDB Atlas, paste the full mongodb+srv:// connection string).")
    if kind == "tls":
        return (f"The secure (TLS) connection to MongoDB at {hosts} failed. For Atlas, allow your IP address under "
                "Network Access and check that the connection string is complete.")
    if kind == "auth_failed":
        who = f"user '{info['user']}'" if info["user"] else "the connection"
        return (f"MongoDB rejected the login for {who} at {hosts} (wrong user name or password in RIQ_MONGO_URI). "
                "Check the credentials; special characters in the password must be URL-encoded (@ -> %40, : -> %3A, "
                "/ -> %2F, # -> %23).")
    if kind == "auth_required":
        return (f"MongoDB at {hosts} requires a user name and password, but RIQ_MONGO_URI has none. Use "
                "mongodb://<user>:<password>@host:port/?authSource=admin in backend/.env.")
    if kind == "no_privileges":
        return (f"The MongoDB user '{info['user'] or '?'}' is not allowed to use database '{db_name}'. Give it the "
                "readWrite role on that database (Atlas: Database Access -> Edit user).")
    if kind == "bad_uri":
        return ("RIQ_MONGO_URI in backend/.env is not a valid MongoDB connection string. Use for example "
                "mongodb://127.0.0.1:27017 (local) or mongodb+srv://user:password@cluster.example.mongodb.net "
                "(Atlas; URL-encode special characters in the password).")
    if kind == "bad_db_name":
        return f"RIQ_MONGO_DB '{db_name}' is not a valid database name (no spaces or . / \\ \" $ characters)."
    if kind == "connection_lost":
        return f"The connection to MongoDB at {hosts} was lost. Check that the MongoDB service is running."
    return f"MongoDB at {hosts} returned an error ({type(exc).__name__}). Run: python -m app.db_check for details."
