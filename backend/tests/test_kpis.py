"""KPI formulas against hand-calculated answers on the tiny fixture.

After cleaning, the analysis rows are (name, rating, votes, cost, cuisines, area):
  B  3.0   0    500  [Chinese]           North
  C  NEW   2    -    [Italian]           South   (unrated)
  a  4.5  100   800  [Chinese]           North   (duplicate of A, kept: most votes)
  D  5.0   30  2000  [Italian, Chinese]  South
E (6/5) is invalid and excluded; A is the removed duplicate.
"""
import numpy as np
import pandas as pd
import pytest

from app import calculations as calc
from app import kpis
from app.kpis import Filters, apply_filters

from .conftest import TINY_MAPPING, make_ctx, tiny_raw

C_HAND = (3.0 + 4.5 + 5.0) / 3          # mean of rated rows
M_HAND = (30 + 100) / 2                 # median of positive votes among rated rows (0 excluded)


def wr(v, r):
    return v / (v + M_HAND) * r + M_HAND / (v + M_HAND) * C_HAND


@pytest.fixture()
def ctx():
    return make_ctx(tiny_raw(), TINY_MAPPING)[0]


def test_prior_hand_calculated(ctx):
    assert ctx.prior["C"] == pytest.approx(C_HAND) and ctx.prior["m"] == pytest.approx(M_HAND)


def test_scalar_kpis_hand_calculated(ctx):
    df = ctx.frame
    assert kpis.kpi_total_restaurants(df, ctx) == 4
    assert kpis.kpi_mean_rating(df, ctx) == pytest.approx(12.5 / 3)
    assert kpis.kpi_median_rating(df, ctx) == pytest.approx(4.5)
    assert kpis.kpi_weighted_rating(df, ctx) == pytest.approx((wr(0, 3.0) + wr(100, 4.5) + wr(30, 5.0)) / 3)
    assert kpis.kpi_mean_cost(df, ctx) == pytest.approx(1100)
    assert kpis.kpi_median_cost(df, ctx) == pytest.approx(800)
    assert kpis.kpi_total_votes(df, ctx) == 132
    assert kpis.kpi_cuisine_count(df, ctx) == 2
    assert kpis.kpi_location_count(df, ctx) == 2


def test_weighted_rating_edge_cases():
    prior = {"available": True, "C": 4.0, "m": 10.0}
    frame = pd.DataFrame({"rating": [3.0, 5.0, np.nan, 4.5], "review_count": [0, 10, 50, np.nan]})
    s = kpis.weighted_rating_series(frame, prior)
    assert s.iloc[0] == pytest.approx(4.0)              # zero votes -> prior mean
    assert s.iloc[1] == pytest.approx(0.5 * 5 + 0.5 * 4)
    assert np.isnan(s.iloc[2]) and np.isnan(s.iloc[3])  # null rating / null votes -> null, never 0
    s0 = kpis.weighted_rating_series(frame, {"available": True, "C": 4.0, "m": 0.0})
    assert s0.iloc[0] == pytest.approx(3.0)             # v + m = 0 -> raw rating (no divide by zero)


def test_charts_hand_calculated(ctx):
    df = ctx.frame
    assert kpis.chart_top_cuisines(df, ctx) == [{"label": "Chinese", "value": 3}, {"label": "Italian", "value": 2}]
    assert kpis.chart_by_location(df, ctx) == [{"label": "North", "value": 2}, {"label": "South", "value": 2}]
    bins = {b["label"]: b["value"] for b in kpis.chart_rating_distribution(df, ctx)}
    assert bins == {"3.0-3.2": 1, "4.4-4.6": 1, "4.8-5.0": 1}   # 5.0 falls in the last bin


def test_rating_bins_float_safety():
    # 4.6 * 5 = 22.999999999999996 in floating point; it must land in the 4.6-4.8 bin.
    frame = pd.DataFrame({"rating": [4.6, 4.2, 3.4]})
    labels = [b["label"] for b in kpis.chart_rating_distribution(frame, None)]
    assert labels == ["3.4-3.6", "4.2-4.4", "4.6-4.8"]


def test_filters_apply_consistently(ctx):
    north = apply_filters(ctx, Filters(location=["North"]))
    assert sorted(north["restaurant_name"]) == ["B", "a"]
    italian = apply_filters(ctx, Filters(cuisine=["Italian"]))
    assert sorted(italian["restaurant_name"]) == ["C", "D"]
    # rating filter excludes unrated rows
    assert len(apply_filters(ctx, Filters(rating_min=0))) == 3
    # unknown online-order values are excluded from both Yes and No
    assert sorted(apply_filters(ctx, Filters(online_order=False))["restaurant_name"]) == ["B", "a"]
    assert sorted(apply_filters(ctx, Filters(online_order=True))["restaurant_name"]) == ["C"]
    assert list(apply_filters(ctx, Filters(search="A"))["restaurant_name"]) == ["a"]


def test_zero_row_filter_returns_na_not_zero(ctx):
    df = apply_filters(ctx, Filters(location=["Nowhere"]))
    assert kpis.kpi_total_restaurants(df, ctx) == 0
    assert kpis.kpi_mean_rating(df, ctx) is None and kpis.kpi_total_votes(df, ctx) is None
    cards = {c["id"]: c for c in calc.kpi_cards(ctx, df)}
    assert cards["mean_rating"]["available"] is False and cards["mean_rating"]["value"] is None
    assert "No restaurants match" in cards["mean_rating"]["reason"]


def test_all_null_ratings_dataset():
    raw = pd.DataFrame({"name": ["A", "B", "C"], "rate": ["NEW", "-", None], "cuisine": ["Thai", "Thai", "Cafe"]})
    ctx, res = make_ctx(raw, {"name": "restaurant_name", "rate": "rating", "cuisine": "cuisines"})
    assert ctx.capabilities["fields"]["rating"] is False
    cards = {c["id"]: c for c in calc.kpi_cards(ctx, ctx.frame)}
    assert cards["mean_rating"]["value"] is None and not cards["mean_rating"]["available"]
    assert cards["total_restaurants"]["value"] == 3
    assert ctx.prior["available"] is False


def test_missing_columns_disable_features():
    raw = pd.DataFrame({"name": ["A", "B"], "cuisine": ["Thai", "Cafe"]})
    ctx, _ = make_ctx(raw, {"name": "restaurant_name", "cuisine": "cuisines"})
    feats = ctx.capabilities["features"]
    assert feats["cuisine_analysis"]["available"] and not feats["cost_analysis"]["available"]
    assert not feats["weighted_rating"]["available"] and not feats["map"]["available"]
    cards = {c["id"]: c for c in calc.kpi_cards(ctx, ctx.frame)}
    assert "requires a cost column" in cards["median_cost"]["reason"]


def test_mixed_currency_guard():
    raw = pd.DataFrame({"name": ["A", "B", "C"], "cost": ["10", "800", "20"], "cur": ["USD", "INR", "USD"],
                        "rate": ["4/5", "3/5", "5/5"]})
    ctx, _ = make_ctx(raw, {"name": "restaurant_name", "cost": "cost", "cur": "currency", "rate": "rating"})
    cards = {c["id"]: c for c in calc.kpi_cards(ctx, ctx.frame)}
    assert cards["mean_cost"]["value"] is None and "Mixed currencies" in cards["mean_cost"]["reason"]
    usd = apply_filters(ctx, Filters(currency="USD"))
    cards = {c["id"]: c for c in calc.kpi_cards(ctx, usd)}
    assert cards["mean_cost"]["value"] == pytest.approx(15) and cards["mean_cost"]["unit"] == "USD"


def test_distribution_profile_hand_calculated(ctx):
    prof = {r["metric"]: r for r in kpis.distribution_profile(ctx.frame, ctx)}
    cost = prof["cost"]                       # 500, 800, 2000
    assert cost["n"] == 3 and cost["mean"] == pytest.approx(1100) and cost["median"] == pytest.approx(800)
    assert cost["p25"] == pytest.approx(650) and cost["p75"] == pytest.approx(1400) and cost["iqr"] == pytest.approx(750)
    assert cost["std"] == pytest.approx(np.std([500, 800, 2000], ddof=1))


def test_constant_column_skew_is_none():
    frame = pd.DataFrame({"rating": [4.0] * 5, "review_count": [1.0, 2, 3, 4, 5], "cost": [100.0] * 5})
    prof = {r["metric"]: r for r in kpis.distribution_profile(frame, None)}
    assert prof["rating"]["skewness"] is None and prof["cost"]["std"] == 0


def test_group_sample_threshold(ctx):
    rows = kpis.chart_wr_by_cuisine(ctx.frame, ctx)
    assert all(r["sufficient_sample"] is False for r in rows)   # n < 10 everywhere
    ctx2 = make_ctx(tiny_raw(), TINY_MAPPING, settings={"min_group_n": 2})[0]
    rows2 = {r["cuisine"]: r for r in kpis.chart_wr_by_cuisine(ctx2.frame, ctx2)}
    assert rows2["Chinese"]["sufficient_sample"] and rows2["Chinese"]["n_rated"] == 3
    assert rows2["Italian"]["n_rated"] == 1 and not rows2["Italian"]["sufficient_sample"]


def test_bayes_m_override():
    ctx = make_ctx(tiny_raw(), TINY_MAPPING, settings={"bayes_m_override": 0})[0]
    # m = 0 -> weighted rating equals raw rating
    assert kpis.kpi_weighted_rating(ctx.frame, ctx) == pytest.approx(12.5 / 3)
