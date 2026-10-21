"""Step 2 requirement: a generated 50,000-row dataset stays fast and consistent."""
import time

import numpy as np
import pandas as pd

from app import calculations as calc
from app.kpis import Filters, apply_filters

from .conftest import make_ctx


def big_raw(n=50_000, seed=7):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "name": [f"Venue {i}" for i in range(n)],
        "address": [f"{i} Road" for i in range(n)],
        "area": rng.choice([f"Area {i}" for i in range(60)], size=n),
        "cuisines": [", ".join(rng.choice(["Thai", "Cafe", "Chinese", "Pizza", "Biryani", "Bakery"], size=2, replace=False)) for _ in range(n)],
        "type": rng.choice(["Cafe", "Quick Bites", "Casual Dining"], size=n),
        "rate": np.where(rng.random(n) < 0.08, "NEW", [f"{v:.1f}/5" for v in rng.uniform(2.5, 4.9, size=n)]),
        "votes": rng.lognormal(3.5, 1.5, size=n).astype(int).astype(str),
        "cost": rng.integers(100, 3000, size=n).astype(str),
        "online": rng.choice(["Yes", "No"], size=n),
    })


MAPPING = {"name": "restaurant_name", "address": "address", "area": "locality", "cuisines": "cuisines",
           "type": "restaurant_type", "rate": "rating", "votes": "review_count", "cost": "cost", "online": "online_order"}


def test_50k_rows_clean_and_compute_quickly():
    t0 = time.perf_counter()
    ctx, res = make_ctx(big_raw(), MAPPING, currency="INR")
    clean_s = time.perf_counter() - t0
    assert res.reconciliation["raw_rows"] == 50_000 and res.reconciliation["balanced"]
    t1 = time.perf_counter()
    df = apply_filters(ctx, Filters())
    cards = calc.kpi_cards(ctx, df)
    for cid in ("top_cuisines", "wr_by_cuisine", "rating_vs_votes", "opportunity", "spearman"):
        calc.run(ctx, cid, df)
    compute_s = time.perf_counter() - t1
    assert clean_s < 30 and compute_s < 10, (clean_s, compute_s)
    assert next(c for c in cards if c["id"] == "total_restaurants")["value"] == 50_000
    scatter = calc.run(ctx, "rating_vs_votes", df)
    assert scatter["shown_points"] == 2000 and scatter["total_points"] > 2000


def test_50k_rows_pandas_matches_duckdb():
    ctx, _ = make_ctx(big_raw(), MAPPING, currency="INR")
    for cid in ("total_restaurants", "mean_rating", "median_cost", "weighted_rating", "top_cuisines", "distribution_profile", "opportunity"):
        d = calc.show_calculation(ctx, cid, Filters(location=["Area 3", "Area 7"]))
        assert d["match"], (cid, d["mismatches"])
