"""Registry of every KPI / chart / table: pandas implementation + equivalent DuckDB SQL.

"Show calculation" returns:
  * the real source of the pandas function (inspect.getsource, so it cannot drift),
  * the rendered SQL (filters inlined) exactly as executed,
  * both results and a PASS/FAIL comparison using a documented tolerance.
"""
from __future__ import annotations

import inspect
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import pandas as pd

from . import kpis, sql_queries, stats
from .kpis import Context, Filters, apply_filters, cost_guard

REL_TOL = 1e-9
ABS_TOL = 1e-9


class Unavailable(Exception):
    """The metric cannot be computed for this dataset/selection (message explains why)."""


@dataclass
class Calc:
    id: str
    label: str
    definition: str
    func: Callable
    sql: str | Callable[[Context, Filters, dict], str]
    kind: str = "scalar"                        # scalar | table
    requires: list[str] = field(default_factory=list)
    uses_cost: bool = False
    unit: Optional[str] = None
    key: list[str] = field(default_factory=list)
    compare: list[str] = field(default_factory=list)
    extract: Optional[Callable[[Any], Any]] = None   # pandas result -> comparable rows / scalar
    caveat: Optional[str] = None


def _sql(template_id: str):
    def build(ctx: Context, f: Filters, params: dict) -> str:
        return sql_queries.render(sql_queries.SQL[template_id], f, C=ctx.prior.get("C", 0.0),
                                  m=ctx.prior.get("m", 0.0), min_n=ctx.settings["min_group_n"])
    return build


def _opportunity_sql(ctx: Context, f: Filters, params: dict) -> str:
    w = stats.normalize_weights(params.get("weights"))
    return sql_queries.render(sql_queries.SQL["opportunity"], f, min_n=ctx.settings["opportunity_min_n"],
                              w_rating=w["rating"], w_engagement=w["engagement"], w_low_saturation=w["low_saturation"])


def _spearman_sql(ctx: Context, f: Filters, params: dict) -> str:
    pairs = stats.spearman_pairs(ctx, apply_filters(ctx, f))
    parts = [sql_queries.render(sql_queries.SQL["spearman_pair"], f, x=a, y=b) for a, b in pairs]
    return "\nUNION ALL\n".join(f"({p})" for p in parts) if parts else "SELECT NULL AS x WHERE FALSE"


def _mw_sql(ctx: Context, f: Filters, params: dict) -> str:
    groups = [g for g in ("online_order", "table_booking") if ctx.capabilities["fields"][g]]
    parts = [sql_queries.render(sql_queries.SQL["mann_whitney_group"], f, g=g) for g in groups]
    return "\nUNION ALL\n".join(f"({p})" for p in parts) if parts else "SELECT NULL AS group_field WHERE FALSE"


CALCS: dict[str, Calc] = {c.id: c for c in [
    # ---- KPIs ----------------------------------------------------------------
    Calc("total_restaurants", "Restaurants analyzed",
         "Number of de-duplicated, valid listings in the current selection.",
         kpis.kpi_total_restaurants, _sql("total_restaurants"), unit="restaurants"),
    Calc("mean_rating", "Mean rating", "Average rating of rated restaurants (unrated excluded), 0-5 scale.",
         kpis.kpi_mean_rating, _sql("mean_rating"), requires=["rating"], unit="/5"),
    Calc("median_rating", "Median rating", "Middle rating of rated restaurants; robust to extreme values.",
         kpis.kpi_median_rating, _sql("median_rating"), requires=["rating"], unit="/5"),
    Calc("weighted_rating", "Weighted rating",
         "Bayesian average that pulls ratings with few votes toward the dataset mean.",
         kpis.kpi_weighted_rating, _sql("weighted_rating"), requires=["weighted_rating"], unit="/5"),
    Calc("mean_cost", "Mean cost", "Average listed cost of restaurants with a cost value.",
         kpis.kpi_mean_cost, _sql("mean_cost"), requires=["cost"], uses_cost=True),
    Calc("median_cost", "Median cost", "Middle listed cost; less affected by a few expensive venues.",
         kpis.kpi_median_cost, _sql("median_cost"), requires=["cost"], uses_cost=True),
    Calc("total_votes", "Total votes", "Sum of review/vote counts; a proxy for online engagement, not visits.",
         kpis.kpi_total_votes, _sql("total_votes"), requires=["votes"], unit="votes"),
    Calc("cuisine_count", "Cuisines", "Distinct cuisines listed by restaurants in the selection.",
         kpis.kpi_cuisine_count, _sql("cuisine_count"), requires=["cuisine"], unit="cuisines"),
    Calc("location_count", "Locations", "Distinct locations with at least one listing in the selection.",
         kpis.kpi_location_count, _sql("location_count"), requires=["location"], unit="locations"),
    # ---- Charts --------------------------------------------------------------
    Calc("top_cuisines", "Top cuisines by listings", "Listings per cuisine (top 15).",
         kpis.chart_top_cuisines, _sql("top_cuisines"), kind="table", requires=["cuisine"],
         key=["label"], compare=["value"],
         caveat="Restaurants with several cuisines are counted once per cuisine, so bars sum to more than the restaurant count."),
    Calc("by_location", "Restaurants by location", "Listings per location (top 15).",
         kpis.chart_by_location, _sql("by_location"), kind="table", requires=["location"],
         key=["label"], compare=["value"], caveat="Listing density, not demand or footfall."),
    Calc("rating_distribution", "Rating distribution", "Rated restaurants per 0.2-point rating band (0-5 scale).",
         kpis.chart_rating_distribution, _sql("rating_distribution"), kind="table", requires=["rating"],
         key=["bin_start"], compare=["value"], caveat="Unrated restaurants are excluded."),
    Calc("price_tiers", "Price tier mix", "Share of restaurants in each price tier (cost terciles).",
         kpis.chart_price_tiers, _sql("price_tiers"), kind="table", requires=["price_tier"],
         key=["label"], compare=["value"], caveat="Tiers are dataset-relative (33rd/67th cost percentiles)."),
    Calc("wr_by_cuisine", "Weighted rating by cuisine",
         "Mean restaurant weighted rating per cuisine; groups below the sample threshold are flagged.",
         kpis.chart_wr_by_cuisine, _sql("wr_by_cuisine"), kind="table", requires=["cuisine", "weighted_rating"],
         key=["cuisine"], compare=["listings", "n_rated", "mean_rating", "weighted_rating", "sufficient_sample"]),
    Calc("median_cost_by_location", "Median cost by location", "Median listed cost per location.",
         kpis.chart_median_cost_by_location, _sql("median_cost_by_location"), kind="table",
         requires=["cost", "location"], uses_cost=True, key=["location"], compare=["n_cost", "median_cost", "mean_cost"]),
    Calc("rating_vs_votes", "Rating vs votes", "Each point is a rated restaurant with a vote count.",
         kpis.chart_rating_vs_votes, _sql("rating_vs_votes"), kind="scalar", requires=["rating", "votes"],
         extract=lambda r: r["total_points"],
         caveat="At most 2,000 points are drawn (deterministic sample). Correlation is not causation."),
    Calc("distribution_profile", "Distribution profile", "Spread and skew of rating, votes and cost.",
         kpis.distribution_profile, _sql("distribution_profile"), kind="table",
         key=["metric"], compare=["n", "mean", "median", "std", "skewness", "min", "max", "p10", "p25", "p75", "p90", "iqr"]),
    # ---- Market analysis -------------------------------------------------------
    Calc("cuisine_popularity", "Cuisine popularity", "Listings, share and ratings per cuisine.",
         stats.market_cuisine_popularity, _sql("cuisine_popularity"), kind="table", requires=["cuisine"],
         key=["cuisine"], compare=["listings", "n_rated", "mean_rating", "weighted_rating", "median_votes", "share_pct"]),
    Calc("location_density", "Location listing density", "Listings and share of listings per location.",
         stats.market_location_density, _sql("location_density"), kind="table", requires=["location"],
         key=["location"], compare=["listings", "mean_rating", "weighted_rating", "share_pct"],
         caveat="Listing density measures supply of listings, not demand."),
    Calc("price_tier_analysis", "Price tier analysis", "Cost and rating by price tier.",
         stats.market_price_tiers, _sql("price_tier_analysis"), kind="table", requires=["price_tier"],
         key=["price_tier"], compare=["listings", "min_cost", "median_cost", "max_cost", "n_rated", "mean_rating",
                                      "median_rating", "weighted_rating", "median_votes"]),
    Calc("saturation", "Cuisine x location saturation", "Location quotient of each cuisine within each location.",
         stats.market_saturation, _sql("saturation"), kind="table", requires=["cuisine", "location"],
         key=["location", "cuisine"], compare=["listings", "location_listings", "cuisine_listings", "location_quotient"],
         caveat="LQ > 1 means the cuisine is over-represented among that location's listings."),
    Calc("market_gaps", "High-rating, low-listing cuisines",
         "Cuisines with weighted rating above the selection mean and fewer listings than the median cuisine.",
         stats.market_gaps, _sql("market_gaps"), kind="table", requires=["cuisine", "weighted_rating"],
         key=["cuisine"], compare=["listings", "n_rated", "weighted_rating"], extract=lambda r: r["rows"]),
    Calc("types_by_tier", "Restaurant types by price tier", "Weighted rating of each type within each tier.",
         stats.types_by_price_tier, _sql("types_by_tier"), kind="table",
         requires=["restaurant_type", "price_tier", "weighted_rating"],
         key=["price_tier", "restaurant_type"], compare=["listings", "n_rated", "weighted_rating"]),
    Calc("opportunity", "Opportunity Score", "Exploratory indicator, not a prediction of success.",
         stats.opportunity_scores, _opportunity_sql, kind="table",
         requires=["cuisine", "location", "weighted_rating"], key=["location", "cuisine"],
         compare=["listings", "n_rated", "weighted_rating", "median_votes", "wr_pct", "votes_pct",
                  "low_saturation_pct", "score"]),
    Calc("spearman", "Spearman correlations", "Rank correlation between numeric fields.",
         stats.spearman_tests, _spearman_sql, kind="table", key=["x", "y"], compare=["n", "rho"],
         caveat="Correlation is not causation."),
    Calc("mann_whitney", "Mann-Whitney U tests", "Do rating distributions differ between Yes and No groups?",
         stats.mann_whitney_tests, _mw_sql, kind="table", requires=["rating"], key=["group_field"],
         compare=["n_yes", "n_no", "u_statistic"],
         caveat="Observational comparison; confounded by type, price and location."),
]}

KPI_IDS = ["total_restaurants", "mean_rating", "median_rating", "weighted_rating", "mean_cost", "median_cost",
           "total_votes", "cuisine_count", "location_count"]


# ---------------------------------------------------------------------------
# Running metrics
# ---------------------------------------------------------------------------
def unavailable_reason(ctx: Context, calc: Calc, df: pd.DataFrame) -> Optional[str]:
    fields = ctx.capabilities["fields"]
    labels = {"rating": "a rating column", "votes": "a review/vote count column", "cost": "a cost column",
              "cuisine": "a cuisine column", "location": "a location column", "price_tier": "price tiers (needs cost data)",
              "weighted_rating": "rating and review/vote count columns", "restaurant_type": "a restaurant type column"}
    missing = [labels.get(r, r) for r in calc.requires if not fields.get(r)]
    if missing:
        return "Not available for this dataset: requires " + " and ".join(missing) + "."
    if calc.uses_cost:
        reason = cost_guard(df)
        if reason:
            return reason
    if len(df) == 0:
        return "No restaurants match the current filters."
    return None


def cost_unit(ctx: Context, df: pd.DataFrame) -> Optional[str]:
    cur = df["currency"].dropna().unique() if "currency" in df else []
    return str(cur[0]) if len(cur) == 1 else None


def run(ctx: Context, calc_id: str, df: pd.DataFrame | None = None, f: Filters | None = None, **params):
    calc = CALCS[calc_id]
    if df is None:
        df = apply_filters(ctx, f or Filters())
    reason = unavailable_reason(ctx, calc, df)
    if reason:
        raise Unavailable(reason)
    return calc.func(df, ctx, **params) if params else calc.func(df, ctx)


def safe_run(ctx: Context, calc_id: str, df: pd.DataFrame, **params) -> dict:
    try:
        return {"available": True, "data": run(ctx, calc_id, df, **params), "reason": None}
    except Unavailable as exc:
        return {"available": False, "data": None, "reason": str(exc)}


def kpi_cards(ctx: Context, df: pd.DataFrame) -> list[dict]:
    price_unit = ctx.meta.get("price_unit")
    cards = []
    for kid in KPI_IDS:
        calc = CALCS[kid]
        res = safe_run(ctx, kid, df)
        label = calc.label
        if calc.uses_cost and price_unit == "for_two":
            label += " for two"
        elif calc.uses_cost and price_unit == "per_person":
            label += " per person"
        unit = cost_unit(ctx, df) if calc.uses_cost else calc.unit
        cards.append({"id": kid, "label": label, "definition": calc.definition, "unit": unit,
                      "value": res["data"], "available": res["available"], "reason": res["reason"]})
    return cards


# ---------------------------------------------------------------------------
# Show calculation: pandas source + executed SQL + comparison
# ---------------------------------------------------------------------------
def _close(a, b) -> bool:
    if a is None or (isinstance(a, float) and math.isnan(a)):
        return b is None or (isinstance(b, float) and math.isnan(b))
    if b is None or (isinstance(b, float) and math.isnan(b)):
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=REL_TOL, abs_tol=ABS_TOL)
    return str(a) == str(b)


def _norm_key(v):
    return round(float(v), 6) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def compare_results(calc: Calc, pandas_value, sql_rows: list[dict]) -> tuple[bool, list[str]]:
    value = calc.extract(pandas_value) if calc.extract else pandas_value
    if calc.kind == "scalar":
        sql_value = next(iter(sql_rows[0].values())) if sql_rows else None
        ok = _close(value, sql_value)
        return ok, [] if ok else [f"pandas={value!r} sql={sql_value!r}"]
    problems = []
    p_rows = {tuple(_norm_key(r[k]) for k in calc.key): r for r in value}
    s_rows = {tuple(_norm_key(r[k]) for k in calc.key): r for r in sql_rows}
    if set(p_rows) != set(s_rows):
        only_p = list(set(p_rows) - set(s_rows))[:5]
        only_s = list(set(s_rows) - set(p_rows))[:5]
        problems.append(f"Row keys differ (pandas {len(p_rows)}, SQL {len(s_rows)}); only pandas: {only_p}; only SQL: {only_s}")
    for k in set(p_rows) & set(s_rows):
        for col in calc.compare:
            pv, sv = p_rows[k].get(col), s_rows[k].get(col)
            if pv is None and col in ("rho", "u_statistic"):
                continue  # pandas reports "insufficient sample"; SQL still computes the raw statistic
            if not _close(pv, sv):
                problems.append(f"{k} {col}: pandas={pv!r} sql={sv!r}")
                if len(problems) > 20:
                    return False, problems
    return not problems, problems


def show_calculation(ctx: Context, calc_id: str, f: Filters, **params) -> dict:
    if calc_id not in CALCS:
        raise KeyError(calc_id)
    calc = CALCS[calc_id]
    df = apply_filters(ctx, f)
    detail = {
        "id": calc.id, "label": calc.label, "definition": calc.definition, "caveat": calc.caveat,
        "pandas_code": inspect.getsource(calc.func),
        "filter_code": inspect.getsource(kpis.apply_filters),
        "filters": f.describe(), "sample_size": len(df), "dataset_id": ctx.dataset_id,
        "tolerance": f"relative {REL_TOL:g}, absolute {ABS_TOL:g}",
        "prior": ctx.prior if calc_id in ("weighted_rating",) else None,
    }
    reason = unavailable_reason(ctx, calc, df)
    sql = calc.sql(ctx, f, params) if callable(calc.sql) else calc.sql
    detail["sql"] = sql
    if reason:
        detail.update(available=False, reason=reason, pandas_result=None, sql_result=None, match=None, mismatches=[])
        return detail
    pandas_value = calc.func(df, ctx, **params) if params else calc.func(df, ctx)
    con = sql_queries.connect(ctx)
    try:
        sql_rows = sql_queries.execute(con, sql)
    finally:
        con.close()
    match, problems = compare_results(calc, pandas_value, sql_rows)
    detail.update(available=True, reason=None, match=match, mismatches=problems,
                  pandas_result=_preview(calc.extract(pandas_value) if calc.extract else pandas_value),
                  sql_result=_preview(sql_rows if calc.kind == "table" else (sql_rows[0] if sql_rows else None)))
    return detail


def _preview(value, limit: int = 50):
    if isinstance(value, list):
        return {"rows": value[:limit], "total_rows": len(value), "truncated": len(value) > limit}
    return value
