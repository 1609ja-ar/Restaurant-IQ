"""Market analysis and statistical tests.

All functions take the filtered analysis frame ``df`` and the analysis ``ctx``.
Group-level results always carry their sample size and a ``sufficient_sample`` flag;
small groups are reported but never presented as reliable winners.

Observational data only: these results describe listings. They do not measure demand,
revenue, footfall or profit, and correlation is not causation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sps

from .kpis import TIER_ORDER, Context, _records, cost_guard, kpi_weighted_rating

DEFAULT_WEIGHTS = {"rating": 0.4, "engagement": 0.3, "low_saturation": 0.3}
SENSITIVITY_WEIGHTS = {
    "Default (40/30/30)": {"rating": 0.4, "engagement": 0.3, "low_saturation": 0.3},
    "Quality-heavy (60/20/20)": {"rating": 0.6, "engagement": 0.2, "low_saturation": 0.2},
    "Saturation-heavy (20/20/60)": {"rating": 0.2, "engagement": 0.2, "low_saturation": 0.6},
}


def percentile_rank(s: pd.Series) -> pd.Series:
    """(min-rank - 1) / (n - 1), identical to SQL PERCENT_RANK(). One row -> 0."""
    n = s.notna().sum()
    if n <= 1:
        return pd.Series(0.0, index=s.index).where(s.notna())
    return (s.rank(method="min") - 1) / (n - 1)


# ---------------------------------------------------------------------------
# Market analysis
# ---------------------------------------------------------------------------
def market_cuisine_popularity(df: pd.DataFrame, ctx: Context):
    # Listing share = restaurants listing the cuisine / restaurants in selection.
    min_n = ctx.settings["min_group_n"]
    rows = ctx.cuisines.merge(df[["rid", "rating", "weighted_rating", "review_count"]], on="rid")
    g = rows.groupby("cuisine").agg(listings=("rid", "size"), n_rated=("weighted_rating", "count"),
                                    mean_rating=("rating", "mean"), weighted_rating=("weighted_rating", "mean"),
                                    median_votes=("review_count", "median")).reset_index()
    g["share_pct"] = 100.0 * g["listings"] / len(df) if len(df) else np.nan
    g["sufficient_sample"] = g["n_rated"] >= min_n
    g = g.sort_values(["listings", "cuisine"], ascending=[False, True])
    return _records(g)


def market_location_density(df: pd.DataFrame, ctx: Context):
    # Listing density = number of listings per location (not demand).
    min_n = ctx.settings["min_group_n"]
    agg = {"listings": ("rid", "size"), "mean_rating": ("rating", "mean"),
           "weighted_rating": ("weighted_rating", "mean"), "n_rated": ("weighted_rating", "count")}
    if cost_guard(df) is None:
        agg["median_cost"] = ("cost", "median")
    g = df.groupby("location").agg(**agg).reset_index()
    cuisines = ctx.cuisines[ctx.cuisines["rid"].isin(df["rid"])].merge(df[["rid", "location"]], on="rid")
    g = g.merge(cuisines.groupby("location")["cuisine"].nunique().rename("distinct_cuisines").reset_index(),
                on="location", how="left")
    g["share_pct"] = 100.0 * g["listings"] / len(df) if len(df) else np.nan
    g["sufficient_sample"] = g["listings"] >= min_n
    g = g.sort_values(["listings", "location"], ascending=[False, True])
    return _records(g)


def market_price_tiers(df: pd.DataFrame, ctx: Context):
    priced = df[df["price_tier"].notna()]
    g = priced.groupby("price_tier").agg(
        listings=("rid", "size"), min_cost=("cost", "min"), median_cost=("cost", "median"),
        max_cost=("cost", "max"), n_rated=("rating", "count"), mean_rating=("rating", "mean"),
        median_rating=("rating", "median"), weighted_rating=("weighted_rating", "mean"),
        median_votes=("review_count", "median")).reset_index()
    g["order"] = g["price_tier"].map({t: i for i, t in enumerate(TIER_ORDER)})
    g = g.sort_values("order").drop(columns="order")
    g["sufficient_sample"] = g["n_rated"] >= ctx.settings["min_group_n"]
    return _records(g)


def market_saturation(df: pd.DataFrame, ctx: Context):
    # Location quotient (LQ) = cuisine share within the location / cuisine share overall.
    # LQ > 1: cuisine is over-represented in that location's listings; < 1: under-represented.
    pairs = ctx.cuisines.merge(df[["rid", "location"]], on="rid").dropna(subset=["location"])
    total = df["location"].notna().sum()
    loc_listings = df.groupby("location").size().rename("location_listings")
    cuisine_listings = pairs.groupby("cuisine")["rid"].nunique().rename("cuisine_listings")
    g = pairs.groupby(["location", "cuisine"]).size().rename("listings").reset_index()
    g = g.join(loc_listings, on="location").join(cuisine_listings, on="cuisine")
    g["share_in_location"] = g["listings"] / g["location_listings"]
    g["overall_share"] = g["cuisine_listings"] / total
    g["location_quotient"] = g["share_in_location"] / g["overall_share"]
    g = g.sort_values(["location", "cuisine"])
    return _records(g)


def heatmap_view(df: pd.DataFrame, ctx: Context, top: int = 10) -> dict:
    """Top-N locations x top-N cuisines grid built from market_saturation rows."""
    cells = market_saturation(df, ctx)
    if not cells:
        return {"locations": [], "cuisines": [], "cells": []}
    frame = pd.DataFrame(cells)
    locs = (frame.groupby("location")["location_listings"].first().sort_values(ascending=False, kind="stable")
            .head(top).index.tolist())
    cuis = (frame.groupby("cuisine")["cuisine_listings"].first().sort_values(ascending=False, kind="stable")
            .head(top).index.tolist())
    sub = frame[frame["location"].isin(locs) & frame["cuisine"].isin(cuis)]
    return {"locations": locs, "cuisines": cuis, "cells": _records(sub)}


def cuisine_share_by_location(df: pd.DataFrame, ctx: Context, cuisine: str) -> dict:
    """Business question 2: locations where a selected cuisine has the FEWEST listings
    (share of the location's listings). Only locations with >= min_group_n listings."""
    min_n = ctx.settings["min_group_n"]
    locs = df.groupby("location").size().rename("location_listings").reset_index()
    locs = locs[locs["location_listings"] >= min_n]
    rids = ctx.cuisines.loc[ctx.cuisines["cuisine"] == cuisine, "rid"]
    counts = df[df["rid"].isin(rids)].groupby("location").size().rename("listings").reset_index()
    merged = locs.merge(counts, on="location", how="left")
    merged["listings"] = merged["listings"].fillna(0).astype(int)   # no listing of the cuisine is a true 0
    merged["share_in_location"] = merged["listings"] / merged["location_listings"]
    merged = merged.sort_values(["share_in_location", "location"])
    return {"cuisine": cuisine, "min_location_listings": min_n, "rows": _records(merged)}


def market_gaps(df: pd.DataFrame, ctx: Context):
    # Business question 1: weighted rating above the selection's mean weighted rating
    # AND fewer listings than the median cuisine. Only cuisines meeting the sample rule.
    pop = pd.DataFrame(market_cuisine_popularity(df, ctx))
    benchmark = kpi_weighted_rating(df, ctx)
    if pop.empty or benchmark is None:
        return {"benchmark_weighted_rating": benchmark, "median_listings": None, "rows": []}
    median_listings = float(pop["listings"].median())
    gaps = pop[pop["sufficient_sample"] & (pop["weighted_rating"] > benchmark) & (pop["listings"] < median_listings)]
    gaps = gaps.sort_values(["weighted_rating", "cuisine"], ascending=[False, True])
    return {"benchmark_weighted_rating": benchmark, "median_listings": median_listings, "rows": _records(gaps)}


def types_by_price_tier(df: pd.DataFrame, ctx: Context):
    # Business question 5: weighted rating of each restaurant type within each price tier.
    rows = ctx.types.merge(df[["rid", "price_tier", "weighted_rating"]], on="rid").dropna(subset=["price_tier"])
    g = rows.groupby(["price_tier", "restaurant_type"]).agg(
        listings=("rid", "size"), n_rated=("weighted_rating", "count"),
        weighted_rating=("weighted_rating", "mean")).reset_index()
    g["sufficient_sample"] = g["n_rated"] >= ctx.settings["min_group_n"]
    g["order"] = g["price_tier"].map({t: i for i, t in enumerate(TIER_ORDER)})
    g = g.sort_values(["order", "sufficient_sample", "weighted_rating", "restaurant_type"],
                      ascending=[True, False, False, True]).drop(columns="order")
    return _records(g)


# ---------------------------------------------------------------------------
# Opportunity Score (exploratory indicator, not a prediction of success)
# ---------------------------------------------------------------------------
def normalize_weights(weights: dict | None) -> dict:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    w = {k: max(0.0, float(w[k])) for k in DEFAULT_WEIGHTS}
    total = sum(w.values())
    if total == 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in w.items()}


def opportunity_scores(df: pd.DataFrame, ctx: Context, weights: dict | None = None):
    # Score = 100 * (w1*WR percentile + w2*median-votes percentile + w3*(1 - listings percentile))
    # over (location, cuisine) pairs with at least `opportunity_min_n` rated listings.
    w = normalize_weights(weights)
    min_n = ctx.settings["opportunity_min_n"]
    pairs = ctx.cuisines.merge(df[["rid", "location", "weighted_rating", "review_count"]], on="rid")
    pairs = pairs.dropna(subset=["location"])
    g = pairs.groupby(["location", "cuisine"]).agg(
        listings=("rid", "size"), n_rated=("weighted_rating", "count"),
        weighted_rating=("weighted_rating", "mean"), median_votes=("review_count", "median")).reset_index()
    g = g[g["n_rated"] >= min_n].copy()
    g["wr_pct"] = percentile_rank(g["weighted_rating"])
    g["votes_pct"] = percentile_rank(g["median_votes"])
    g["low_saturation_pct"] = 1 - percentile_rank(g["listings"])
    g["score"] = 100 * (w["rating"] * g["wr_pct"] + w["engagement"] * g["votes_pct"]
                        + w["low_saturation"] * g["low_saturation_pct"])
    g = g.sort_values(["score", "location", "cuisine"], ascending=[False, True, True])
    return _records(g)


def opportunity_sensitivity(df: pd.DataFrame, ctx: Context) -> list[dict]:
    out = []
    for name, w in SENSITIVITY_WEIGHTS.items():
        top = opportunity_scores(df, ctx, w)[:5]
        out.append({"scenario": name, "weights": w,
                    "top": [{"location": r["location"], "cuisine": r["cuisine"], "score": r["score"]} for r in top]})
    return out


# ---------------------------------------------------------------------------
# Statistical tests
# ---------------------------------------------------------------------------
MIN_TEST_N = 10


def _strength(rho: float) -> str:
    a = abs(rho)
    return "negligible" if a < 0.1 else "weak" if a < 0.3 else "moderate" if a < 0.5 else "strong"


def spearman_pairs(ctx: Context, df: pd.DataFrame) -> list[tuple[str, str]]:
    cols = [c for c in ("rating", "review_count", "cost") if c in df and df[c].notna().any()]
    if "cost" in cols and cost_guard(df):
        cols.remove("cost")
    return [(a, b) for i, a in enumerate(cols) for b in cols[i + 1:]]


def spearman_tests(df: pd.DataFrame, ctx: Context):
    # Spearman rank correlation on rows where both values are present.
    labels = {"rating": "Rating", "review_count": "Votes", "cost": "Cost"}
    out = []
    for a, b in spearman_pairs(ctx, df):
        pair = df[[a, b]].dropna()
        n = len(pair)
        row = {"x": a, "y": b, "label": f"{labels[a]} vs {labels[b]}", "n": n, "rho": None, "p_value": None}
        if n < MIN_TEST_N:
            row["note"] = f"Insufficient sample (n={n}, need at least {MIN_TEST_N})."
        elif pair[a].nunique() < 2 or pair[b].nunique() < 2:
            row["note"] = "One variable is constant; correlation is undefined."
        else:
            res = sps.spearmanr(pair[a], pair[b])
            row["rho"], row["p_value"] = float(res.statistic), float(res.pvalue)
            direction = "positive" if row["rho"] > 0 else "negative"
            sig = "statistically significant at 5%" if row["p_value"] < 0.05 else "not statistically significant at 5%"
            row["note"] = (f"{_strength(row['rho']).capitalize()} {direction} monotonic association "
                           f"(rho = {row['rho']:.2f}, n = {n:,}); {sig}. Correlation is not causation.")
        out.append(row)
    return out


def mann_whitney_tests(df: pd.DataFrame, ctx: Context):
    # Rating distributions for Yes vs No groups; unknown (null) group values are excluded.
    out = []
    for field, label in (("online_order", "Online ordering"), ("table_booking", "Table booking")):
        if field not in df or df[field].notna().sum() == 0 or "rating" not in df:
            continue
        d = df.loc[df["rating"].notna() & df[field].notna(), ["rating", field]]
        yes = d.loc[d[field] == True, "rating"]   # noqa: E712 - object column with True/False
        no = d.loc[d[field] == False, "rating"]   # noqa: E712
        row = {"group_field": field, "label": f"Rating: {label} Yes vs No", "n_yes": int(len(yes)), "n_no": int(len(no)),
               "median_yes": float(yes.median()) if len(yes) else None,
               "median_no": float(no.median()) if len(no) else None,
               "mean_yes": float(yes.mean()) if len(yes) else None,
               "mean_no": float(no.mean()) if len(no) else None,
               "u_statistic": None, "p_value": None, "effect_size_r": None}
        if len(yes) < MIN_TEST_N or len(no) < MIN_TEST_N:
            row["note"] = f"Insufficient sample (need at least {MIN_TEST_N} per group)."
        elif pd.concat([yes, no]).nunique() < 2:
            row["note"] = "All ratings are identical; the test is undefined."
        else:
            res = sps.mannwhitneyu(yes, no, alternative="two-sided")
            u = float(res.statistic)
            r = 2 * u / (len(yes) * len(no)) - 1   # rank-biserial correlation, -1..1
            row.update(u_statistic=u, p_value=float(res.pvalue), effect_size_r=r)
            sig = "a statistically significant difference" if res.pvalue < 0.05 else "no statistically significant difference"
            row["note"] = (f"{sig.capitalize()} at 5% (p = {res.pvalue:.3g}); rank-biserial r = {r:.2f} "
                           f"({_strength(r)} effect). Groups differ in many ways (type, price, location), so this "
                           "does not show that the feature causes higher or lower ratings.")
        out.append(row)
    return out
