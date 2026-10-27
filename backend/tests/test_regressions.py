"""Regression tests for bugs reported on real data (zomato.csv)."""
import io

import pandas as pd

from app import ingest
from app.kpis import Filters

ZOMATO_LIKE = pd.DataFrame({
    "Unnamed: 0.1": ["0", "1", "2", "3"],
    "Unnamed: 0": ["0", "1", "2", "3"],
    "restaurant name": ["#FeelTheROLL", "#L-81 Cafe", "#refuel", "'@ Biryani Central"],
    "restaurant type": ["Quick Bites", "Quick Bites", "Cafe", "Casual Dining"],
    "rate (out of 5)": ["3.4", "3.9", "3.7", "2.7"],
    "num of ratings": ["7", "48", "37", "135"],
    "avg cost (two people)": ["200.0", "400.0", "400.0", "550.0"],
    "online_order": ["No", "Yes", "Yes", "Yes"],
    "table booking": ["No", "No", "No", "No"],
    "cuisines type": ["Fast Food", "Fast Food, Beverages", "Cafe, Beverages", "Biryani, Mughlai"],
    "area": ["Bellandur", "Byresandra,Tavarekere,Madiwala", "Bannerghatta Road", "Marathahalli"],
    "local address": ["Bellandur", "HSR", "Bannerghatta Road", "Marathahalli"],
})


def test_count_of_ratings_maps_to_review_count_not_rating():
    """Bug: 'num of ratings' was left unmapped, so weighted rating / votes showed N/A everywhere."""
    m = {x["source_column"]: x["suggested_field"] for x in ingest.suggest_mapping(list(ZOMATO_LIKE.columns), ZOMATO_LIKE)}
    assert m["num of ratings"] == "review_count"
    assert m["rate (out of 5)"] == "rating"
    assert m["Unnamed: 0"] is None and m["Unnamed: 0.1"] is None


def test_other_count_headers():
    for header in ("number of reviews", "rating count", "total votes", "No. of Ratings", "user_ratings_total"):
        df = pd.DataFrame({header: ["1", "20", "300"], "stars": ["4.1", "3.5", "4.8"]})
        m = {x["source_column"]: x["suggested_field"] for x in ingest.suggest_mapping(list(df.columns), df)}
        assert m[header] == "review_count", header
        assert m["stars"] == "rating", header


def test_header_states_rating_scale():
    assert ingest.header_rating_scale("rate (out of 5)") == 5
    assert ingest.header_rating_scale("Rating/10") == 10
    assert ingest.header_rating_scale("score_100") == 100
    assert ingest.header_rating_scale("rating") is None


def test_index_column_detection():
    assert ingest.is_index_column("Unnamed: 0", pd.Series(["0", "1", "2"]))
    assert not ingest.is_index_column("Unnamed: 0", pd.Series(["5", "1", "9"]))
    assert not ingest.is_index_column("votes", pd.Series(["0", "1", "2"]))


def test_remap_creates_new_version_with_votes(client):
    csv = ZOMATO_LIKE.to_csv(index=False).encode()
    up = client.post("/api/uploads", files={"file": ("zomato.csv", io.BytesIO(csv), "text/csv")}).json()
    # Import WITHOUT the vote column (what happened originally)
    first = [{"source_column": c, "canonical_field": f} for c, f in {
        "restaurant name": "restaurant_name", "rate (out of 5)": "rating", "cuisines type": "cuisines",
        "area": "locality", "local address": "address"}.items()]
    v1 = client.post(f"/api/uploads/{up['upload_id']}/import", json={"mapping": first}).json()["active"]["dataset_id"]
    kp = {k["id"]: k for k in client.get("/api/dashboard").json()["kpis"]}
    assert kp["weighted_rating"]["value"] is None and "review/vote count" in kp["weighted_rating"]["reason"]

    remap = client.get(f"/api/datasets/{v1}/remap").json()
    sugg = {m["source_column"]: m["suggested_field"] for m in remap["profile"]["suggested_mapping"]}
    assert remap["remap_of"] == v1 and sugg["num of ratings"] == "review_count" and sugg["area"] == "locality"
    assert remap["profile"]["rating_scale"]["max"] == 5 and remap["profile"]["rating_scale"]["confident"]
    mapping = [{"source_column": c, "canonical_field": f} for c, f in sugg.items()]
    v2 = client.post(f"/api/uploads/{remap['upload_id']}/import", json={"mapping": mapping}).json()["active"]["dataset_id"]
    assert v2 != v1
    kp2 = {k["id"]: k for k in client.get("/api/dashboard").json()["kpis"]}
    assert kp2["weighted_rating"]["value"] is not None and kp2["total_votes"]["value"] == 7 + 48 + 37 + 135
    # the old version is unchanged
    old = {k["id"]: k for k in client.get("/api/dashboard", params={"dataset_id": v1}).json()["kpis"]}
    assert old["weighted_rating"]["value"] is None


def test_remap_rejected_for_demo(client):
    ds = client.post("/api/demo/load").json()["active"]["dataset_id"]
    assert client.get(f"/api/datasets/{ds}/remap").status_code == 422


def test_select_all_filters_give_values_not_na(client):
    """Selecting every location, cuisine and type must return the same KPIs as no filter."""
    client.post("/api/demo/load")
    opts = client.get("/api/filters/options").json()
    params = [(k, o["value"]) for k in ("location", "cuisine", "restaurant_type") for o in opts[k]]
    every = {k["id"]: k["value"] for k in client.get("/api/dashboard", params=params).json()["kpis"]}
    none = {k["id"]: k["value"] for k in client.get("/api/dashboard").json()["kpis"]}
    assert every == none and all(v is not None for v in every.values())


def test_long_filter_selection_is_summarized():
    f = Filters(location=[f"L{i}" for i in range(26)], cuisine=["A", "B"])
    assert f.describe() == ["Location: 26 selected (L0, L1, L2, ...)", "Cuisine: A, B"]
