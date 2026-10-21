"""Statistical methods: hand-checkable inputs, guards and the Opportunity Score."""
import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from app import stats
from app.kpis import Filters, apply_filters

from .conftest import make_ctx


def _ctx(n=30, seed=0, **settings):
    rng = np.random.default_rng(seed)
    raw = pd.DataFrame({
        "name": [f"R{i}" for i in range(n)],
        "area": rng.choice(["North", "South", "East"], size=n),
        "cuisine": rng.choice(["Thai", "Cafe", "Chinese, Thai"], size=n),
        "rate": [f"{v:.1f}/5" for v in rng.uniform(3, 5, size=n)],
        "votes": [str(int(v)) for v in rng.integers(0, 500, size=n)],
        "cost": [str(int(v)) for v in rng.integers(100, 2000, size=n)],
        "online": rng.choice(["Yes", "No"], size=n),
    })
    mapping = {"name": "restaurant_name", "area": "locality", "cuisine": "cuisines", "rate": "rating",
               "votes": "review_count", "cost": "cost", "online": "online_order"}
    return make_ctx(raw, mapping, settings=settings, currency="INR")[0]


def test_percentile_rank_matches_sql_definition():
    s = pd.Series([10, 20, 20, 40])
    assert stats.percentile_rank(s).tolist() == [0.0, 1 / 3, 1 / 3, 1.0]
    assert stats.percentile_rank(pd.Series([5.0])).tolist() == [0.0]


def test_weights_normalized():
    assert stats.normalize_weights({"rating": 2, "engagement": 1, "low_saturation": 1}) == \
        {"rating": 0.5, "engagement": 0.25, "low_saturation": 0.25}
    assert stats.normalize_weights({"rating": 0, "engagement": 0, "low_saturation": 0}) == stats.DEFAULT_WEIGHTS


def test_spearman_hand_checkable():
    ctx = _ctx()
    df = ctx.frame.copy()
    df["review_count"] = df["rating"] * 10          # perfectly monotonic -> rho = 1
    rows = {(r["x"], r["y"]): r for r in stats.spearman_tests(df, ctx)}
    assert rows[("rating", "review_count")]["rho"] == pytest.approx(1.0)
    assert "not causation" in rows[("rating", "review_count")]["note"]


def test_spearman_guards_small_and_constant():
    ctx = _ctx()
    small = ctx.frame.head(5)
    assert all(r["rho"] is None and "Insufficient" in r["note"] for r in stats.spearman_tests(small, ctx))
    const = ctx.frame.copy()
    const["cost"] = 500.0
    row = [r for r in stats.spearman_tests(const, ctx) if r["y"] == "cost"][0]
    assert row["rho"] is None and "constant" in row["note"]


def test_mann_whitney_hand_calculated_u():
    ctx = _ctx()
    df = pd.DataFrame({"rating": [1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10] * 2 + [0.5] * 10,
                       "online_order": [True] * 20 + [False] * 10, "table_booking": [None] * 30})
    df["rid"] = range(len(df))
    row = stats.mann_whitney_tests(df, ctx)[0]
    # Every Yes value (1..10) beats every No value (0.5): U = n_yes * n_no = 200, r = 1
    assert row["u_statistic"] == 200 and row["effect_size_r"] == pytest.approx(1.0)
    assert row["p_value"] == pytest.approx(sps.mannwhitneyu([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10] * 2, [0.5] * 10).pvalue)
    assert "does not show that the feature causes" in row["note"]


def test_mann_whitney_insufficient_and_unknown_excluded():
    ctx = _ctx()
    df = pd.DataFrame({"rid": range(6), "rating": [4.0, 3, 5, 4, 3, 2],
                       "online_order": [True, False, None, True, False, None], "table_booking": [None] * 6})
    row = stats.mann_whitney_tests(df, ctx)[0]
    assert row["n_yes"] == 2 and row["n_no"] == 2 and row["p_value"] is None   # nulls excluded, too small


def test_opportunity_score_formula():
    ctx = _ctx(n=300, opportunity_min_n=8)
    rows = stats.opportunity_scores(ctx.frame, ctx)
    assert rows, "expected eligible pairs"
    for r in rows:
        assert r["n_rated"] >= 8
        expected = 100 * (0.4 * r["wr_pct"] + 0.3 * r["votes_pct"] + 0.3 * r["low_saturation_pct"])
        assert r["score"] == pytest.approx(expected)
        assert 0 <= r["score"] <= 100
    assert [r["score"] for r in rows] == sorted((r["score"] for r in rows), reverse=True)
    sens = stats.opportunity_sensitivity(ctx.frame, ctx)
    assert [s["scenario"] for s in sens] == list(stats.SENSITIVITY_WEIGHTS) and all(len(s["top"]) <= 5 for s in sens)


def test_market_gaps_rule():
    ctx = _ctx(n=300, min_group_n=5)
    res = stats.market_gaps(ctx.frame, ctx)
    for r in res["rows"]:
        assert r["weighted_rating"] > res["benchmark_weighted_rating"]
        assert r["listings"] < res["median_listings"] and r["sufficient_sample"]


def test_saturation_location_quotient_hand_calculated():
    raw = pd.DataFrame({"name": list("ABCD"), "area": ["N", "N", "S", "S"],
                        "cuisine": ["Thai", "Cafe", "Thai", "Thai"], "rate": ["4/5"] * 4})
    ctx = make_ctx(raw, {"name": "restaurant_name", "area": "locality", "cuisine": "cuisines", "rate": "rating"})[0]
    rows = {(r["location"], r["cuisine"]): r for r in stats.market_saturation(ctx.frame, ctx)}
    # Thai: 3 of 4 overall (0.75). In N: 1 of 2 (0.5) -> LQ 0.667; in S: 2 of 2 -> LQ 1.333
    assert rows[("N", "Thai")]["location_quotient"] == pytest.approx(0.5 / 0.75)
    assert rows[("S", "Thai")]["location_quotient"] == pytest.approx(1.0 / 0.75)
    assert rows[("N", "Cafe")]["location_quotient"] == pytest.approx(0.5 / 0.25)


def test_one_row_groups_and_ties():
    raw = pd.DataFrame({"name": list("ABC"), "area": ["N", "S", "E"], "cuisine": ["Thai", "Thai", "Cafe"],
                        "rate": ["4/5", "4/5", "4/5"], "votes": ["10", "10", "10"]})
    ctx = make_ctx(raw, {"name": "restaurant_name", "area": "locality", "cuisine": "cuisines", "rate": "rating",
                         "votes": "review_count"}, settings={"opportunity_min_n": 1})[0]
    rows = stats.opportunity_scores(ctx.frame, ctx)
    assert len(rows) == 3 and all(r["wr_pct"] == 0.0 for r in rows)   # ties share the minimum rank
    assert stats.market_location_density(apply_filters(ctx, Filters(location=["N"])), ctx)[0]["listings"] == 1
