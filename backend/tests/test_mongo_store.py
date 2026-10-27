"""MongoDB backend tests. They run against a real MongoDB server when RIQ_TEST_MONGO_URI is set, e.g.

    RIQ_TEST_MONGO_URI=mongodb://127.0.0.1:27017

Each test gets a fresh, uniquely named database which is dropped afterwards.
Without the variable the tests are skipped (reported as 'skipped', never as passed).
"""
import hashlib
import io
import os
import uuid

import pandas as pd
import pytest

from app import main
from app.cleaning import CleanSettings, clean_dataset
from app.db import INDEXES, MongoStore
from app.demo_data import DEMO_MAPPING, generate_demo_dataframe
from app.store import DuplicateUser, Store

from .conftest import TINY_MAPPING, sign_up, tiny_raw

URI = os.environ.get("RIQ_TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(not URI, reason="RIQ_TEST_MONGO_URI not set (no MongoDB server for tests)")


@pytest.fixture()
def mongo_store(tmp_path):
    store = MongoStore(URI, f"riq_test_{uuid.uuid4().hex[:8]}", tmp_path / "data", timeout_ms=3000)
    try:
        yield store
    finally:
        if store._client is not None:
            store._client.drop_database(store.db_name)
        store.close()


@pytest.fixture()
def mongo_client(mongo_store, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "store", mongo_store)
    main._ctx_cache.clear()
    with TestClient(main.app) as c:
        sign_up(c)
        yield c
    main._ctx_cache.clear()


def _roundtrip(store, raw, mapping, **kw):
    res = clean_dataset(raw, CleanSettings(mapping=mapping, **kw))
    meta = store.create_dataset(res.cleaned, {**res.metadata, "name": "t", "reconciliation": res.reconciliation,
                                              "quality": res.quality, "log": res.log})
    store._cache.clear()
    return res.cleaned, store.load_cleaned(meta["dataset_id"]), meta


@pytest.mark.parametrize("case", ["demo", "tiny", "odd_columns"])
def test_cleaned_frame_roundtrips_exactly(mongo_store, case):
    if case == "demo":
        raw, mapping = generate_demo_dataframe(), DEMO_MAPPING
    elif case == "tiny":
        raw, mapping = tiny_raw().assign(phone=list("123456")), TINY_MAPPING
    else:   # unmapped source columns whose names MongoDB treats specially
        raw, mapping = tiny_raw().assign(**{"a.b": list("abcdef"), "$price": [1, 2, None, 4, 5, 6]}), TINY_MAPPING
    original, loaded, meta = _roundtrip(mongo_store, raw, mapping, currency="INR")
    pd.testing.assert_frame_equal(original.reset_index(drop=True), loaded, check_dtype=False)
    assert list(loaded.columns) == list(original.columns)


def test_indexes_are_created_once(mongo_store):
    created = mongo_store.ensure_indexes()
    assert sorted(created) == sorted(m.document["name"] for models in INDEXES.values() for m in models)
    assert mongo_store.ensure_indexes() == []                       # idempotent
    db = mongo_store.db
    assert set(INDEXES) <= set(db.list_collection_names())
    assert db.users.index_information()["ux_users_email"]["unique"] is True


def test_versions_active_settings_and_collections(mongo_store):
    _, _, m1 = _roundtrip(mongo_store, tiny_raw(), TINY_MAPPING)
    _, _, m2 = _roundtrip(mongo_store, tiny_raw(), TINY_MAPPING)
    assert (m1["dataset_id"], m2["dataset_id"]) == ("v1", "v2")
    assert [v["dataset_id"] for v in mongo_store.list_datasets()] == ["v2", "v1"]
    assert mongo_store.active_id() == "v2"
    mongo_store.set_active("v1")
    assert mongo_store.active_id() == "v1"
    s = mongo_store.update_settings(min_group_n=5)
    assert s["min_group_n"] == 5 and mongo_store.settings()["revision"] == 1
    db = mongo_store.db
    assert db.cleaning_log.count_documents({"dataset_id": "v1"}) > 0
    assert db.column_quality.count_documents({"dataset_id": "v1"}) == 8
    assert db.restaurants.count_documents({"dataset_id": "v1"}) == 5
    # cuisines are an array per restaurant, in source order (D = "Italian, Chinese")
    assert db.restaurants.find_one({"dataset_id": "v1", "rid": 5})["cuisines"] == ["Italian", "Chinese"]
    # the multikey index answers "restaurants serving Chinese" directly
    assert db.restaurants.count_documents({"dataset_id": "v1", "cuisines": "Chinese"}) == 3   # A, B, D


def test_failed_import_leaves_no_partial_version(mongo_store, monkeypatch):
    from pymongo.collection import Collection
    res = clean_dataset(tiny_raw(), CleanSettings(mapping=TINY_MAPPING))
    original = Collection.insert_many

    def boom(self, docs, *a, **k):   # restaurant rows are written, then the quality report fails
        if self.name == "column_quality":
            raise RuntimeError("disk full")
        return original(self, docs, *a, **k)
    monkeypatch.setattr(Collection, "insert_many", boom)
    with pytest.raises(RuntimeError):
        mongo_store.create_dataset(res.cleaned, {**res.metadata, "name": "t", "quality": res.quality})
    monkeypatch.undo()
    assert mongo_store.list_datasets() == []
    assert mongo_store.db.restaurants.count_documents({}) == 0
    _, _, meta = _roundtrip(mongo_store, tiny_raw(), TINY_MAPPING)
    assert meta["dataset_id"] == "v2"                               # version numbers are never reused


def test_duplicate_email_is_rejected_by_unique_index(mongo_store):
    user = {"id": "u1", "name": "A", "email": "a@example.com", "password_hash": "$2b$12$x", "token_version": 0,
            "is_demo": False, "created_at": "2026-01-01T00:00:00+00:00"}
    mongo_store.create_user(user)
    with pytest.raises(DuplicateUser):
        mongo_store.create_user({**user, "id": "u2"})
    assert mongo_store.get_user_by_email("a@example.com")["id"] == "u1"
    assert mongo_store.get_user("u1")["created_at"] == "2026-01-01T00:00:00+00:00"
    mongo_store.update_user("u1", token_version=3, email="ignored@example.com")
    assert mongo_store.get_user("u1")["token_version"] == 3 and mongo_store.count_users() == 1


def test_api_flow_on_mongodb_matches_file_backend(mongo_client, tmp_path, monkeypatch):
    csv = tiny_raw().to_csv(index=False).encode()
    up = mongo_client.post("/api/uploads", files={"file": ("tiny.csv", io.BytesIO(csv), "text/csv")}).json()
    mapping = [{"source_column": c, "canonical_field": f} for c, f in TINY_MAPPING.items()]
    imp = mongo_client.post(f"/api/uploads/{up['upload_id']}/import", json={"mapping": mapping, "rating_scale_max": 5})
    assert imp.status_code == 200, imp.text
    mongo_dash = mongo_client.get("/api/dashboard").json()
    health = mongo_client.get("/api/health").json()["database"]
    assert health["connected"] is True and health["backend"] == "mongodb"
    raw = mongo_client.get("/api/datasets/v1/raw").content
    assert hashlib.sha256(raw).hexdigest() == hashlib.sha256(csv).hexdigest()
    mongo_client.post("/api/demo/load")
    assert mongo_client.get("/api/datasets").json()["active"] == "v2"

    # The same flow on the file backend must give identical numbers.
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "store", Store(tmp_path / "filedata"))
    main._ctx_cache.clear()
    with TestClient(main.app) as fc:
        sign_up(fc)
        up2 = fc.post("/api/uploads", files={"file": ("tiny.csv", io.BytesIO(csv), "text/csv")}).json()
        fc.post(f"/api/uploads/{up2['upload_id']}/import", json={"mapping": mapping, "rating_scale_max": 5})
        file_dash = fc.get("/api/dashboard").json()
    assert {k["id"]: k["value"] for k in mongo_dash["kpis"]} == {k["id"]: k["value"] for k in file_dash["kpis"]}
    assert mongo_dash["charts"]["top_cuisines"] == file_dash["charts"]["top_cuisines"]


def test_tampered_raw_file_is_detected(mongo_client):
    csv = tiny_raw().to_csv(index=False).encode()
    up = mongo_client.post("/api/uploads", files={"file": ("tiny.csv", io.BytesIO(csv), "text/csv")}).json()
    mapping = [{"source_column": c, "canonical_field": f} for c, f in TINY_MAPPING.items()]
    mongo_client.post(f"/api/uploads/{up['upload_id']}/import", json={"mapping": mapping, "rating_scale_max": 5})
    path = main.store.upload_path(up["upload_id"])
    path.write_bytes(csv + b"tampered")
    r = mongo_client.get("/api/datasets/v1/raw")
    assert r.status_code == 404 and "checksum" in r.json()["error"]


def test_users_and_ownership_in_mongodb(mongo_store, monkeypatch):
    """Accounts live in the users collection (bcrypt hash only) and datasets are private per user."""
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "store", mongo_store)
    main._ctx_cache.clear()
    with TestClient(main.app) as a, TestClient(main.app) as b:
        sign_up(a, "owner@example.com")
        sign_up(b, "other@example.com")
        assert b.post("/api/auth/register", json={"name": "X", "email": "owner@example.com",
                                                  "password": "Restaurant123"}).status_code == 409
        ds = a.post("/api/demo/load").json()["active"]["dataset_id"]
        assert b.get("/api/datasets").json()["versions"] == []
        assert b.get("/api/dashboard", params={"dataset_id": ds}).status_code == 404
    db = mongo_store.db
    rows = list(db.users.find({}, {"email": 1, "password_hash": 1}).sort("email", 1))
    owner = db.users.find_one({"_id": db.datasets.find_one({"_id": ds})["owner_id"]})["email"]
    assert [r["email"] for r in rows] == ["other@example.com", "owner@example.com"]
    assert all(r["password_hash"].startswith("$2b$") and "Restaurant123" not in r["password_hash"] for r in rows)
    assert owner == "owner@example.com"


def test_import_keeps_accounts_ownership_and_remap(mongo_store, tmp_path, monkeypatch):
    """File-mode data (with accounts) imported into MongoDB: same login works, datasets keep their owner,
    Re-map works on an imported upload, and running the import twice copies nothing more."""
    from fastapi.testclient import TestClient
    from app.db_import import import_file_store
    file_store = Store(tmp_path / "filedata")
    monkeypatch.setattr(main, "store", file_store)
    main._ctx_cache.clear()
    csv = tiny_raw().to_csv(index=False).encode()
    mapping = [{"source_column": c, "canonical_field": f} for c, f in TINY_MAPPING.items()]
    with TestClient(main.app) as fc:
        sign_up(fc, "mig@example.com")
        up = fc.post("/api/uploads", files={"file": ("tiny.csv", io.BytesIO(csv), "text/csv")}).json()["upload_id"]
        fc.post(f"/api/uploads/{up}/import", json={"mapping": mapping, "rating_scale_max": 5})
        fc.post("/api/demo/load")
    mongo_store.base = file_store.base            # raw files stay where they are on disk
    assert import_file_store(mongo_store, file_store.base) == 2
    assert import_file_store(mongo_store, file_store.base) == 0          # second run copies nothing
    assert [d["dataset_id"] for d in mongo_store.list_datasets()] == ["v2", "v1"]

    monkeypatch.setattr(main, "store", mongo_store)
    main._ctx_cache.clear()
    with TestClient(main.app) as c:
        r = c.post("/api/auth/login", json={"email": "mig@example.com", "password": "Restaurant123"})
        assert r.status_code == 200, r.text                    # account (bcrypt hash) was imported
        versions = c.get("/api/datasets").json()
        assert [v["dataset_id"] for v in versions["versions"]] == ["v2", "v1"] and versions["active"] == "v2"
        assert c.get("/api/datasets/v1/remap").status_code == 200   # imported upload kept its owner
        assert c.get("/api/datasets/v1/raw").content == csv


def test_db_check_ok(monkeypatch, capsys):
    from app import db_check
    from app.config import reload_settings
    name = f"riq_test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("RIQ_MONGO_URI", URI)
    monkeypatch.setenv("RIQ_MONGO_DB", name)
    reload_settings()
    try:
        assert db_check.check() == 0
        out = capsys.readouterr().out
        assert "OK: connected to MongoDB" in out and f"database '{name}'" in out
        assert db_check.check() == 0 and "created" not in capsys.readouterr().out   # second run: nothing to create
    finally:
        from pymongo import MongoClient
        MongoClient(URI).drop_database(name)
