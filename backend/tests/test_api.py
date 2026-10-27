"""API integration: upload -> profile -> validate -> import -> active version -> analytics -> export."""
import io

import pandas as pd
import pytest
from openpyxl import Workbook

from app import ingest, main

from .conftest import tiny_raw

MAPPING = [{"source_column": c, "canonical_field": f} for c, f in {
    "name": "restaurant_name", "address": "address", "area": "locality", "cuisines": "cuisines", "rate": "rating",
    "votes": "review_count", "cost": "cost", "online": "online_order"}.items()]


def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _xlsx_bytes(df: pd.DataFrame) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and pd.isna(v)) else v for v in row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(client, name, content, mime="text/csv"):
    return client.post("/api/uploads", files={"file": (name, content, mime)})


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["database"]["connected"] is True


def test_no_dataset_gives_friendly_error(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 404 and "No dataset is loaded" in r.json()["error"]


def test_csv_upload_profile_and_import_flow(client):
    raw_bytes = _csv_bytes(tiny_raw())
    r = _upload(client, "tiny.csv", raw_bytes)
    assert r.status_code == 200, r.text
    body = r.json()
    prof = body["profile"]
    assert prof["row_count"] == 6 and prof["column_count"] == 8 and len(prof["preview"]) == 6
    suggested = {m["source_column"]: m["suggested_field"] for m in prof["suggested_mapping"]}
    assert suggested["name"] == "restaurant_name" and suggested["rate"] == "rating" and suggested["votes"] == "review_count"
    assert prof["rating_scale"]["max"] == 5

    v = client.post(f"/api/uploads/{body['upload_id']}/validate", json={"mapping": MAPPING, "rating_scale_max": 5})
    assert v.status_code == 200 and v.json()["reconciliation"]["rows_used_in_analysis"] == 4

    imp = client.post(f"/api/uploads/{body['upload_id']}/import", json={"mapping": MAPPING, "rating_scale_max": 5,
                                                                      "currency": "INR"})
    assert imp.status_code == 200, imp.text
    ds = imp.json()["active"]["dataset_id"]
    assert ds == "v1"

    dash = client.get("/api/dashboard", params={"dataset_id": ds}).json()
    kp = {k["id"]: k for k in dash["kpis"]}
    assert kp["total_restaurants"]["value"] == 4 and kp["median_cost"]["value"] == 800
    assert kp["mean_rating"]["value"] == pytest.approx(12.5 / 3)
    assert dash["context"]["sample_size"] == 4

    filtered = client.get("/api/dashboard", params={"dataset_id": ds, "location": "North"}).json()
    assert filtered["context"]["sample_size"] == 2 and filtered["context"]["filters"] == ["Location: North"]

    # raw download is byte-identical to the upload; cleaned CSV keeps flags
    assert client.get(f"/api/datasets/{ds}/raw").content == raw_bytes
    cleaned = pd.read_csv(io.BytesIO(client.get(f"/api/datasets/{ds}/cleaned.csv").content))
    assert len(cleaned) == 5 and {"include_in_analysis", "is_unrated", "cost_outlier"} <= set(cleaned.columns)

    # every import is a new version; the old one still exists
    imp2 = client.post(f"/api/uploads/{body['upload_id']}/import", json={"mapping": MAPPING, "rating_scale_max": 5})
    assert imp2.json()["active"]["dataset_id"] == "v2"
    versions = client.get("/api/datasets").json()
    assert [v["dataset_id"] for v in versions["versions"]] == ["v2", "v1"] and versions["active"] == "v2"
    assert client.put("/api/datasets/active", json={"dataset_id": "v1"}).json()["active"]["dataset_id"] == "v1"


def test_xlsx_upload_and_import(client):
    r = _upload(client, "tiny.xlsx", _xlsx_bytes(tiny_raw()),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.status_code == 200, r.text
    prof = r.json()["profile"]
    assert prof["file_type"] == "xlsx" and prof["row_count"] == 6
    imp = client.post(f"/api/uploads/{r.json()['upload_id']}/import", json={"mapping": MAPPING, "rating_scale_max": 5})
    assert imp.status_code == 200
    assert imp.json()["active"]["reconciliation"]["rows_used_in_analysis"] == 4


def test_unsupported_file_type_rejected(client):
    r = _upload(client, "data.json", b'{"a": 1}', "application/json")
    assert r.status_code == 415 and "Unsupported file type" in r.json()["error"]


def test_binary_disguised_as_csv_rejected(client):
    r = _upload(client, "data.csv", b"PK\x03\x04garbage\x00\x00")
    assert r.status_code == 422 and "binary" in r.json()["error"]


def test_malformed_csv_rejected_with_line_number(client):
    content = b"name,rate,votes\nA,4/5,10\nB,3/5,4,extra,fields\n"
    r = _upload(client, "bad.csv", content)
    assert r.status_code == 422
    err = r.json()["error"]
    assert "line 3" in err and "No rows were imported" in err and "Traceback" not in err


def test_malformed_xlsx_rejected(client):
    r = _upload(client, "bad.xlsx", b"PK\x03\x04this is not really a workbook")
    assert r.status_code == 422 and "workbook could not be opened" in r.json()["error"]


def test_empty_and_header_only_files(client):
    assert "empty" in _upload(client, "empty.csv", b"").json()["error"]
    assert "no data rows" in _upload(client, "header.csv", b"name,rate\n").json()["error"]


def test_upload_processing_error_is_friendly(client, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(ingest, "profile_file", boom)
    r = _upload(client, "tiny.csv", _csv_bytes(tiny_raw()))
    assert r.status_code == 422
    assert "secret" not in r.json()["error"] and "could not be processed" in r.json()["error"]


def test_non_restaurant_mapping_rejected(client):
    df = pd.DataFrame({"employee": ["a", "b"], "department": ["x", "y"], "salary": ["1", "2"]})
    up = _upload(client, "hr.csv", _csv_bytes(df)).json()
    r = client.post(f"/api/uploads/{up['upload_id']}/import",
                    json={"mapping": [{"source_column": "employee", "canonical_field": "restaurant_name"}]})
    assert r.status_code == 422 and "does not look like restaurant data" in r.json()["error"]


def test_summary_table_rejected_with_specific_message(client):
    df = pd.DataFrame({"cuisine": ["Chinese", "Indian"], "listings": [578, 428]})
    up = _upload(client, "query.csv", _csv_bytes(df)).json()
    r = client.post(f"/api/uploads/{up['upload_id']}/import",
                    json={"mapping": [{"source_column": "cuisine", "canonical_field": "cuisines"}]})
    assert r.status_code == 422 and "summary table" in r.json()["error"]


def test_csv_larger_than_former_50mb_limit_is_accepted(client, tmp_path):
    """Regression for the removed 50 MB cap: ~55 MB valid CSV must not be rejected and no rows may vanish."""
    n = 60_000
    pad = "x" * 900
    path = tmp_path / "big.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("name,address,rate,votes,notes\n")
        for i in range(n):
            fh.write(f"R{i},{i} Main St,{3 + (i % 20) / 10:.1f}/5,{i % 500},{pad}\n")
    size = path.stat().st_size
    assert size > 52_428_800
    with open(path, "rb") as fh:
        r = client.post("/api/uploads", files={"file": ("big.csv", fh, "text/csv")})
    assert r.status_code == 200, r.text[:300]
    assert r.json()["profile"]["row_count"] == n and r.json()["size_bytes"] == size
    mapping = [{"source_column": "name", "canonical_field": "restaurant_name"},
               {"source_column": "address", "canonical_field": "address"},
               {"source_column": "rate", "canonical_field": "rating"},
               {"source_column": "votes", "canonical_field": "review_count"}]
    try:
        imp = client.post(f"/api/uploads/{r.json()['upload_id']}/import", json={"mapping": mapping, "rating_scale_max": 5})
        assert imp.status_code == 200
        rec = imp.json()["active"]["reconciliation"]
        assert rec["raw_rows"] == n and rec["rows_used_in_analysis"] == n and rec["balanced"]
    finally:
        # ~110 MB of generated files (CSV + stored copy + cleaned data): free the disk right away
        import shutil
        path.unlink(missing_ok=True)
        shutil.rmtree(tmp_path / "data", ignore_errors=True)


def test_no_50mb_limit_anywhere_in_source():
    import pathlib
    root = pathlib.Path(main.__file__).resolve().parents[2]
    hits = []
    for p in list(root.joinpath("backend", "app").rglob("*.py")) + list(root.joinpath("frontend", "src").rglob("*.ts*")):
        text = p.read_text(encoding="utf-8")
        if "52428800" in text or "50MB" in text or "50 MB" in text:
            hits.append(str(p))
    assert hits == []


def test_demo_load_and_sample_download(client):
    r = client.post("/api/demo/load")
    assert r.status_code == 200
    active = r.json()["active"]
    assert active["is_demo"] and "illustrative" in active["name"]
    assert active["reconciliation"]["raw_rows"] == 804
    sample = client.get("/api/demo/sample.csv")
    assert sample.status_code == 200 and sample.content.startswith(b"name,address,location")


def test_dashboard_consistency_with_calculation_endpoint(client):
    client.post("/api/demo/load")
    params = {"location": ["Indiranagar", "HSR"], "online_order": "true"}
    dash = client.get("/api/dashboard", params=params).json()
    for card in dash["kpis"]:
        detail = client.get(f"/api/calculations/{card['id']}", params=params).json()
        assert detail["match"] is True, detail["mismatches"]
        if card["value"] is not None:
            assert detail["pandas_result"] == pytest.approx(card["value"])
    for cid, chart in dash["charts"].items():
        detail = client.get(f"/api/calculations/{cid}", params=params).json()
        assert detail["match"] is True, (cid, detail["mismatches"])


def test_explorer_pagination_sort_and_detail(client):
    client.post("/api/demo/load")
    p1 = client.get("/api/restaurants", params={"sort": "rating", "order": "desc", "page": 1}).json()
    assert p1["page_size"] == 50 and len(p1["items"]) == 50 and p1["total"] == 774
    ratings = [i["rating"] for i in p1["items"]]
    assert ratings == sorted(ratings, reverse=True)
    last = client.get("/api/restaurants", params={"sort": "rating", "page": p1["pages"]}).json()
    assert last["items"][-1]["rating"] is None   # nulls last
    names = [i["restaurant_name"].lower() for i in client.get("/api/restaurants", params={"sort": "name", "order": "asc"}).json()["items"]]
    assert names == sorted(names)
    rid = p1["items"][0]["rid"]
    detail = client.get(f"/api/restaurants/{rid}").json()["restaurant"]
    assert detail["rid"] == rid and "menu_items" in detail and "include_in_analysis" in detail
    assert client.get("/api/restaurants", params={"sort": "bogus"}).status_code == 422


def test_sql_endpoint(client):
    client.post("/api/demo/load")
    ok = client.post("/api/sql", json={"sql": "SELECT COUNT(*) AS n FROM restaurants"}).json()
    assert ok["rows"] == [[774]]
    bad = client.post("/api/sql", json={"sql": "DROP TABLE restaurants"})
    assert bad.status_code == 400 and "read-only" in bad.json()["error"]
    schema = client.get("/api/sql/schema").json()
    assert {t["table"] for t in schema["tables"]} == {"restaurants", "restaurant_cuisines", "restaurant_types"}
    assert len(schema["examples"]) == 5


def test_settings_change_invalidates_cached_results(client):
    client.post("/api/demo/load")
    before = {k["id"]: k["value"] for k in client.get("/api/dashboard").json()["kpis"]}
    client.put("/api/settings", json={"bayes_m_override": 0})
    after = {k["id"]: k["value"] for k in client.get("/api/dashboard").json()["kpis"]}
    assert after["weighted_rating"] == pytest.approx(after["mean_rating"]) != before["weighted_rating"]
    client.put("/api/settings", json={"clear_bayes_m_override": True})
    again = {k["id"]: k["value"] for k in client.get("/api/dashboard").json()["kpis"]}
    assert again["weighted_rating"] == pytest.approx(before["weighted_rating"])


def test_market_endpoint(client):
    client.post("/api/demo/load")
    m = client.get("/api/market", params={"focus_cuisine": "Thai"}).json()
    assert m["opportunity"]["available"] and m["heatmap"]["data"]["locations"]
    assert len(m["sensitivity"]) == 3 and m["focus_cuisine"]["cuisine"] == "Thai"
    w = client.get("/api/market", params={"w_rating": 1, "w_engagement": 0, "w_low_saturation": 0}).json()
    assert w["opportunity"]["weights"] == {"rating": 1.0, "engagement": 0.0, "low_saturation": 0.0}


def test_validation_errors_are_friendly(client):
    r = client.get("/api/dashboard", params={"rating_min": 9})
    assert r.status_code == 422 and r.json()["error"].startswith("Invalid request")


def test_root_points_to_app_and_docs(client):
    r = client.get("/")
    assert r.status_code == 200 and r.json()["app"] == "http://localhost:5173" and r.json()["api_docs"] == "/docs"
    assert client.get("/favicon.ico").status_code == 204
