"""MySQL backend tests. They run against a real MySQL server when RIQ_TEST_MYSQL_URL is set, e.g.

    RIQ_TEST_MYSQL_URL=mysql+pymysql://root:@127.0.0.1:3307/

Each test gets a fresh, uniquely named database which is dropped afterwards.
Without the variable the tests are skipped (reported as 'skipped', never as passed).
"""
import hashlib
import io
import os
import uuid

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import main
from app.cleaning import CleanSettings, clean_dataset
from app.db import MySQLStore, schema_sql
from app.demo_data import DEMO_MAPPING, generate_demo_dataframe
from app.store import Store

from .conftest import TINY_MAPPING, tiny_raw

URL = os.environ.get("RIQ_TEST_MYSQL_URL")
pytestmark = pytest.mark.skipif(not URL, reason="RIQ_TEST_MYSQL_URL not set (no MySQL server for tests)")


@pytest.fixture()
def mysql_store(tmp_path):
    server = make_url(URL)
    name = f"riq_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(server.set(database=None))
    with admin.begin() as con:
        con.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"))
    store = MySQLStore(server.set(database=name, query={"charset": "utf8mb4"}), tmp_path / "data")
    try:
        yield store
    finally:
        store.engine.dispose()
        with admin.begin() as con:
            con.execute(text(f"DROP DATABASE `{name}`"))
        admin.dispose()


@pytest.fixture()
def mysql_client(mysql_store, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "store", mysql_store)
    main._ctx_cache.clear()
    with TestClient(main.app) as c:
        yield c
    main._ctx_cache.clear()


def _roundtrip(store, raw, mapping, **kw):
    res = clean_dataset(raw, CleanSettings(mapping=mapping, **kw))
    meta = store.create_dataset(res.cleaned, {**res.metadata, "name": "t", "reconciliation": res.reconciliation,
                                              "quality": res.quality, "log": res.log})
    store._cache.clear()
    return res.cleaned, store.load_cleaned(meta["dataset_id"]), meta


@pytest.mark.parametrize("case", ["demo", "tiny"])
def test_cleaned_frame_roundtrips_exactly(mysql_store, case):
    raw, mapping = (generate_demo_dataframe(), DEMO_MAPPING) if case == "demo" else (tiny_raw().assign(phone=list("123456")), TINY_MAPPING)
    original, loaded, meta = _roundtrip(mysql_store, raw, mapping, currency="INR")
    pd.testing.assert_frame_equal(original.reset_index(drop=True), loaded, check_dtype=False)
    assert list(loaded.columns) == list(original.columns)


def test_versions_active_and_settings(mysql_store):
    _, _, m1 = _roundtrip(mysql_store, tiny_raw(), TINY_MAPPING)
    _, _, m2 = _roundtrip(mysql_store, tiny_raw(), TINY_MAPPING)
    assert (m1["dataset_id"], m2["dataset_id"]) == ("v1", "v2")
    assert [v["dataset_id"] for v in mysql_store.list_datasets()] == ["v2", "v1"]
    assert mysql_store.active_id() == "v2"
    mysql_store.set_active("v1")
    assert mysql_store.active_id() == "v1"
    s = mysql_store.update_settings(min_group_n=5)
    assert s["min_group_n"] == 5 and mysql_store.settings()["revision"] == 1
    with mysql_store.engine.begin() as con:
        assert con.execute(text("SELECT COUNT(*) FROM cleaning_log WHERE dataset_id='v1'")).scalar() > 0
        assert con.execute(text("SELECT COUNT(*) FROM column_quality WHERE dataset_id='v1'")).scalar() == 8
        assert con.execute(text("SELECT COUNT(*) FROM restaurants WHERE dataset_id='v1'")).scalar() == 5
        # bridge rows: B, C, a, D(2), E -> 6 cuisine rows; preserved order for D
        assert con.execute(text("SELECT GROUP_CONCAT(cuisine ORDER BY pos) FROM restaurant_cuisines "
                                "WHERE dataset_id='v1' AND rid=5")).scalar() == "Italian,Chinese"


def test_api_flow_on_mysql_matches_file_backend(mysql_client, tmp_path, monkeypatch):
    csv = tiny_raw().to_csv(index=False).encode()
    up = mysql_client.post("/api/uploads", files={"file": ("tiny.csv", io.BytesIO(csv), "text/csv")}).json()
    mapping = [{"source_column": c, "canonical_field": f} for c, f in TINY_MAPPING.items()]
    imp = mysql_client.post(f"/api/uploads/{up['upload_id']}/import", json={"mapping": mapping, "rating_scale_max": 5})
    assert imp.status_code == 200, imp.text
    mysql_dash = mysql_client.get("/api/dashboard").json()
    assert mysql_client.get("/api/health").json()["database"]["connected"] is True
    raw = mysql_client.get("/api/datasets/v1/raw").content
    assert hashlib.sha256(raw).hexdigest() == hashlib.sha256(csv).hexdigest()
    mysql_client.post("/api/demo/load")
    assert mysql_client.get("/api/datasets").json()["active"] == "v2"

    # The same flow on the file backend must give identical numbers.
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "store", Store(tmp_path / "filedata"))
    main._ctx_cache.clear()
    with TestClient(main.app) as fc:
        up2 = fc.post("/api/uploads", files={"file": ("tiny.csv", io.BytesIO(csv), "text/csv")}).json()
        fc.post(f"/api/uploads/{up2['upload_id']}/import", json={"mapping": mapping, "rating_scale_max": 5})
        file_dash = fc.get("/api/dashboard").json()
    assert {k["id"]: k["value"] for k in mysql_dash["kpis"]} == {k["id"]: k["value"] for k in file_dash["kpis"]}
    assert mysql_dash["charts"]["top_cuisines"] == file_dash["charts"]["top_cuisines"]


def test_tampered_raw_file_is_detected(mysql_client):
    csv = tiny_raw().to_csv(index=False).encode()
    up = mysql_client.post("/api/uploads", files={"file": ("tiny.csv", io.BytesIO(csv), "text/csv")}).json()
    mapping = [{"source_column": c, "canonical_field": f} for c, f in TINY_MAPPING.items()]
    mysql_client.post(f"/api/uploads/{up['upload_id']}/import", json={"mapping": mapping, "rating_scale_max": 5})
    path = main.store.upload_path(up["upload_id"])
    path.write_bytes(csv + b"tampered")
    r = mysql_client.get("/api/datasets/v1/raw")
    assert r.status_code == 404 and "checksum" in r.json()["error"]


def test_unreachable_database_gives_friendly_503(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    bad = MySQLStore(make_url("mysql+pymysql://nobody:wrong@127.0.0.1:1/none"), tmp_path)
    monkeypatch.setattr(main, "store", bad)
    main._ctx_cache.clear()
    with TestClient(main.app) as c:
        h = c.get("/api/health").json()
        assert h["status"] == "ok" and h["database"]["connected"] is False
        r = c.get("/api/datasets")
        assert r.status_code == 503 and "MySQL" in r.json()["error"] and "wrong" not in r.json()["error"]


def test_schema_sql_is_mysql_ddl():
    ddl = schema_sql()
    for table in ("uploads", "datasets", "restaurants", "restaurant_cuisines", "restaurant_types", "cleaning_log",
                  "column_quality", "app_state"):
        assert f"CREATE TABLE {table}" in ddl
    assert "ENGINE=InnoDB" in ddl and "FOREIGN KEY" in ddl
