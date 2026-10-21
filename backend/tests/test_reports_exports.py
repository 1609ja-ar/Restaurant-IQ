"""Reports and exports must carry current computed values for the active version and filters."""
import io
import zipfile

import pandas as pd
import pytest


@pytest.fixture()
def demo(client):
    client.post("/api/demo/load")
    return client


def test_report_preview_uses_current_numbers(demo):
    params = {"location": "HSR"}
    dash = {k["id"]: k for k in demo.get("/api/dashboard", params=params).json()["kpis"]}
    rep = demo.post("/api/reports/preview", json={"report_type": "market_overview", "length": "detailed",
                                                   "use_filters": True, "filters": {"location": ["HSR"]}}).json()
    assert rep["scope"]["sample_size"] == dash["total_restaurants"]["value"]
    assert rep["scope"]["filters"] == ["Location: HSR"]
    mean = next(k for k in rep["kpis"] if k["label"] == "Mean rating")["value"]
    assert mean == f"{dash['mean_rating']['value']:.2f} / 5"
    assert any("Sample data" in lim for lim in rep["limitations"])
    assert {"Distribution profile", "Price tiers"} <= {s["heading"] for s in rep["sections"]}
    for needed in ("Snapshot data", "No revenue, footfall", "approximate listed prices"):
        assert any(needed in lim for lim in rep["limitations"]), needed


@pytest.mark.parametrize("body", [
    {"report_type": "market_overview", "length": "executive"},
    {"report_type": "cuisine", "length": "detailed", "focus": "Biryani"},
    {"report_type": "location", "length": "executive", "focus": "Indiranagar"},
    {"report_type": "comparison", "length": "detailed", "compare_kind": "location", "compare_items": ["HSR", "BTM"]},
])
def test_pdf_generation(demo, body):
    r = demo.post("/api/reports/pdf", json=body)
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF") and len(r.content) > 3000


def test_report_validation(demo):
    assert demo.post("/api/reports/pdf", json={"report_type": "comparison"}).status_code == 422
    assert demo.post("/api/reports/pdf", json={"report_type": "cuisine"}).status_code == 422


def test_filtered_and_bi_exports_match_filters(demo):
    params = {"cuisine": "Chinese", "online_order": "true"}
    n = demo.get("/api/dashboard", params=params).json()["context"]["sample_size"]
    filt = pd.read_csv(io.BytesIO(demo.get("/api/export/filtered.csv", params=params).content))
    flat = pd.read_csv(io.BytesIO(demo.get("/api/export/bi-flat.csv", params=params).content))
    assert len(filt) == len(flat) == n
    assert filt["cuisines"].str.contains("Chinese").all() and "dish_liked" not in filt.columns  # mapped to menu_items
    assert "menu_items" in filt.columns and "weighted_rating" in flat.columns


def test_star_schema_integrity(demo):
    z = zipfile.ZipFile(io.BytesIO(demo.get("/api/export/star-schema.zip").content))
    assert set(z.namelist()) == {"fact_restaurants.csv", "dim_location.csv", "dim_cuisine.csv",
                                 "bridge_restaurant_cuisine.csv", "README.md", "metadata.json"}
    fact = pd.read_csv(z.open("fact_restaurants.csv"))
    loc = pd.read_csv(z.open("dim_location.csv"))
    cui = pd.read_csv(z.open("dim_cuisine.csv"))
    bridge = pd.read_csv(z.open("bridge_restaurant_cuisine.csv"))
    assert fact["restaurant_key"].is_unique and len(fact) == 774
    assert set(fact["location_key"].dropna()) <= set(loc["location_key"])
    assert set(bridge["cuisine_key"]) <= set(cui["cuisine_key"]) and set(bridge["restaurant_key"]) <= set(fact["restaurant_key"])
    assert loc["listings"].sum() == fact["location_key"].notna().sum()
    assert "Sample data" in z.read("README.md").decode()
