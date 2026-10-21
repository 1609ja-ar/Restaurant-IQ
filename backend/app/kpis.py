"""Descriptive KPIs, chart data and filters. The single source of truth for numbers.

Every metric is a small, readable pandas function. ``calculations.py`` registers each
function next to its equivalent DuckDB SQL, and the "Show calculation" feature
displays the function's real source (via ``inspect.getsource``) and executes the SQL.

Conventions
* ``df`` is the *filtered analysis frame*: de-duplicated rows with invalid rows removed.
* Unavailable metrics return ``None`` (shown as "N/A"); never 0 unless 0 is the true answer.
* Values are returned at full precision; rounding happens only in the UI / exports.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

TIER_ORDER = ["Budget", "Mid-range", "Premium"]
SCATTER_MAX_POINTS = 2000
SCATTER_SEED = 42
RATING_BIN_WIDTH = 0.2
CORE_NUMERIC = ["rating", "review_count", "cost", "latitude", "longitude"]
CORE_OBJECT = ["restaurant_name", "address", "location", "currency", "price_tier", "online_order", "table_booking"]


# ---------------------------------------------------------------------------
# Analysis context (built once per dataset version + settings revision)
# ---------------------------------------------------------------------------
@dataclass
class Context:
    dataset_id: str
    meta: dict
    settings: dict
    frame: pd.DataFrame              # analysis rows (include_in_analysis) + weighted_rating
    cuisines: pd.DataFrame           # bridge: rid, cuisine
    types: pd.DataFrame              # bridge: rid, restaurant_type
    prior: dict                      # Bayesian prior: C, m and how they were chosen
    capabilities: dict


def explode_list(frame: pd.DataFrame, column: str, name: str) -> pd.DataFrame:
    """One row per (restaurant, list item). A restaurant is counted once per item."""
    if column not in frame:
        return pd.DataFrame({"rid": pd.Series(dtype=int), name: pd.Series(dtype=object)})
    s = frame[["rid", column]].dropna(subset=[column]).explode(column)
    s = s.rename(columns={column: name}).dropna(subset=[name])
    return s.reset_index(drop=True)


def bayes_prior(frame: pd.DataFrame, settings: dict) -> dict:
    """C = mean rating of rated analysis rows (0-5 scale);
    m = median of positive vote counts among rated rows, unless overridden in Settings."""
    if frame["rating"].notna().sum() == 0 or frame["review_count"].notna().sum() == 0:
        return {"available": False, "reason": "Requires both a rating and a review/vote count column."}
    rated = frame[frame["rating"].notna()]
    if rated.empty:
        return {"available": False, "reason": "No rated restaurants in the dataset."}
    C = float(rated["rating"].mean())
    positive = rated["review_count"][rated["review_count"] > 0]
    if settings.get("bayes_m_override") is not None:
        m, m_source = float(settings["bayes_m_override"]), "manual override in Settings"
    elif len(positive):
        m, m_source = float(positive.median()), "median of positive vote counts among rated restaurants"
    else:
        m, m_source = 0.0, "no positive vote counts; m = 0 (weighted rating equals raw rating)"
    return {"available": True, "C": C, "m": m, "m_source": m_source, "n_rated": int(len(rated))}


def weighted_rating_series(frame: pd.DataFrame, prior: dict) -> pd.Series:
    """WR = v/(v+m) * R + m/(v+m) * C.
    Null rating or null votes -> WR is null. If v + m = 0 the raw rating is used."""
    if not prior.get("available"):
        return pd.Series(np.nan, index=frame.index)
    v, R = frame["review_count"], frame["rating"]
    C, m = prior["C"], prior["m"]
    denom = v + m
    wr = (v / denom) * R + (m / denom) * C
    wr = wr.where(denom != 0, R)
    return wr.where(R.notna() & v.notna())


def capability_profile(frame: pd.DataFrame, meta: dict) -> dict:
    def has(col):
        return bool(col in frame and frame[col].notna().any())

    caps = {
        "name": has("restaurant_name"), "rating": has("rating"), "votes": has("review_count"),
        "cost": has("cost"), "cuisine": has("cuisines"), "restaurant_type": has("restaurant_type"),
        "location": has("location"), "online_order": has("online_order"), "table_booking": has("table_booking"),
        "coordinates": has("latitude") and has("longitude"), "date": has("source_date"),
        "price_tier": has("price_tier"),
    }
    caps["weighted_rating"] = bool(caps["rating"] and caps["votes"])
    currencies = meta.get("currencies", [])
    caps["mixed_currency"] = len(currencies) > 1
    requirements = {
        "rating_analysis": ("rating", "a rating column"),
        "weighted_rating": ("weighted_rating", "both a rating and a review/vote count column"),
        "cost_analysis": ("cost", "a numeric cost/price column"),
        "cuisine_analysis": ("cuisine", "a cuisines/category column"),
        "location_analysis": ("location", "a locality, city or region column"),
        "price_tiers": ("price_tier", "a cost column with at least 10 values and 3 distinct amounts"),
        "online_order_test": ("online_order", "an online ordering / delivery Yes/No column"),
        "table_booking_test": ("table_booking", "a table booking / reservation Yes/No column"),
        "map": ("coordinates", "valid latitude and longitude columns"),
        "time_trend": ("date", "a validated date column"),
    }
    features = {k: {"available": bool(caps[c]), "requires": req} for k, (c, req) in requirements.items()}
    features["opportunity_score"] = {
        "available": bool(caps["cuisine"] and caps["location"] and caps["weighted_rating"]),
        "requires": "cuisine, location, rating and review/vote count columns"}
    return {"fields": caps, "features": features, "currencies": currencies}


def build_context(dataset_id: str, cleaned: pd.DataFrame, meta: dict, settings: dict) -> Context:
    frame = cleaned[cleaned["include_in_analysis"]].copy()
    # Core columns always exist (all-null when unmapped) so every metric and SQL query has a
    # stable schema; availability is decided by the capability profile, not by column presence.
    for col in CORE_NUMERIC:
        if col not in frame:
            frame[col] = np.nan
    for col in CORE_OBJECT:
        if col not in frame:
            frame[col] = None
    if "cost_outlier" not in frame:
        frame["cost_outlier"] = False
    prior = bayes_prior(frame, settings)
    frame["weighted_rating"] = weighted_rating_series(frame, prior)
    return Context(
        dataset_id=dataset_id, meta=meta, settings=settings, frame=frame,
        cuisines=explode_list(frame, "cuisines", "cuisine"),
        types=explode_list(frame, "restaurant_type", "restaurant_type"),
        prior=prior, capabilities=capability_profile(frame, meta),
    )


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
@dataclass
class Filters:
    location: list[str] = field(default_factory=list)
    cuisine: list[str] = field(default_factory=list)
    restaurant_type: list[str] = field(default_factory=list)
    price_tier: list[str] = field(default_factory=list)
    rating_min: Optional[float] = None
    rating_max: Optional[float] = None
    online_order: Optional[bool] = None
    table_booking: Optional[bool] = None
    currency: Optional[str] = None
    search: Optional[str] = None
    exclude_outliers: bool = False

    def is_empty(self) -> bool:
        return self == Filters()

    def describe(self) -> list[str]:
        out = []
        if self.location: out.append("Location: " + ", ".join(self.location))
        if self.cuisine: out.append("Cuisine: " + ", ".join(self.cuisine))
        if self.restaurant_type: out.append("Type: " + ", ".join(self.restaurant_type))
        if self.price_tier: out.append("Price tier: " + ", ".join(self.price_tier))
        if self.rating_min is not None or self.rating_max is not None:
            out.append(f"Rating {self.rating_min if self.rating_min is not None else 0:g}-"
                       f"{self.rating_max if self.rating_max is not None else 5:g} (unrated excluded)")
        if self.online_order is not None: out.append(f"Online order: {'Yes' if self.online_order else 'No'}")
        if self.table_booking is not None: out.append(f"Table booking: {'Yes' if self.table_booking else 'No'}")
        if self.currency: out.append(f"Currency: {self.currency}")
        if self.search: out.append(f"Name contains '{self.search}'")
        if self.exclude_outliers: out.append("Cost outliers excluded")
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Filters":
        d = d or {}
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d and d[k] not in ("", None)}
        return cls(**known)


def apply_filters(ctx: Context, f: Filters) -> pd.DataFrame:
    df = ctx.frame
    mask = pd.Series(True, index=df.index)
    if f.location and "location" in df:
        mask &= df["location"].isin(f.location)
    if f.cuisine:
        mask &= df["rid"].isin(ctx.cuisines.loc[ctx.cuisines["cuisine"].isin(f.cuisine), "rid"])
    if f.restaurant_type:
        mask &= df["rid"].isin(ctx.types.loc[ctx.types["restaurant_type"].isin(f.restaurant_type), "rid"])
    if f.price_tier and "price_tier" in df:
        mask &= df["price_tier"].isin(f.price_tier)
    if f.rating_min is not None and "rating" in df:
        mask &= df["rating"] >= f.rating_min
    if f.rating_max is not None and "rating" in df:
        mask &= df["rating"] <= f.rating_max
    if f.online_order is not None and "online_order" in df:
        mask &= df["online_order"] == f.online_order
    if f.table_booking is not None and "table_booking" in df:
        mask &= df["table_booking"] == f.table_booking
    if f.currency and "currency" in df:
        mask &= df["currency"] == f.currency
    if f.search and "restaurant_name" in df:
        mask &= df["restaurant_name"].str.contains(f.search, case=False, regex=False, na=False)
    if f.exclude_outliers:
        mask &= ~df["cost_outlier"]
    return df[mask]


def filter_options(ctx: Context) -> dict:
    df = ctx.frame

    def sorted_counts(series: pd.Series) -> list[dict]:
        vc = series.value_counts()
        return [{"value": k, "count": int(v)} for k, v in sorted(vc.items(), key=lambda kv: (-kv[1], str(kv[0])))]

    return {
        "location": sorted_counts(df["location"].dropna()) if "location" in df else [],
        "cuisine": sorted_counts(ctx.cuisines["cuisine"]),
        "restaurant_type": sorted_counts(ctx.types["restaurant_type"]),
        "price_tier": [t for t in TIER_ORDER if "price_tier" in df and (df["price_tier"] == t).any()],
        "price_tier_cutoffs": ctx.meta.get("price_tier_cutoffs", {}),
        "currencies": ctx.capabilities["currencies"],
        "has_online_order": ctx.capabilities["fields"]["online_order"],
        "has_table_booking": ctx.capabilities["fields"]["table_booking"],
        "has_rating": ctx.capabilities["fields"]["rating"],
    }


def cost_guard(df: pd.DataFrame) -> Optional[str]:
    """Reason cost metrics cannot be computed for this frame, or None if they can."""
    if "cost" not in df or df["cost"].notna().sum() == 0:
        return "No cost values in the current selection."
    if "currency" in df:
        cur = df.loc[df["cost"].notna(), "currency"].dropna().unique()
        if len(cur) > 1:
            return f"Mixed currencies ({', '.join(sorted(cur))}); choose a currency filter to compare costs."
    return None


# ---------------------------------------------------------------------------
# KPI functions (scalar)
# ---------------------------------------------------------------------------
def kpi_total_restaurants(df: pd.DataFrame, ctx: Context):
    # Restaurants analyzed = de-duplicated, valid rows in the current filter.
    return int(len(df))


def kpi_mean_rating(df: pd.DataFrame, ctx: Context):
    rated = df["rating"].dropna()            # unrated rows are excluded
    return float(rated.mean()) if len(rated) else None


def kpi_median_rating(df: pd.DataFrame, ctx: Context):
    rated = df["rating"].dropna()
    return float(rated.median()) if len(rated) else None


def kpi_weighted_rating(df: pd.DataFrame, ctx: Context):
    # Mean of restaurant-level Bayesian weighted ratings (needs rating AND votes).
    wr = df["weighted_rating"].dropna()
    return float(wr.mean()) if len(wr) else None


def kpi_mean_cost(df: pd.DataFrame, ctx: Context):
    costs = df["cost"].dropna()              # missing costs are excluded, never treated as 0
    return float(costs.mean()) if len(costs) else None


def kpi_median_cost(df: pd.DataFrame, ctx: Context):
    costs = df["cost"].dropna()
    return float(costs.median()) if len(costs) else None


def kpi_total_votes(df: pd.DataFrame, ctx: Context):
    votes = df["review_count"].dropna()
    return float(votes.sum()) if len(votes) else None


def kpi_cuisine_count(df: pd.DataFrame, ctx: Context):
    bridge = ctx.cuisines[ctx.cuisines["rid"].isin(df["rid"])]
    return int(bridge["cuisine"].nunique())


def kpi_location_count(df: pd.DataFrame, ctx: Context):
    return int(df["location"].dropna().nunique())


# ---------------------------------------------------------------------------
# Chart / table functions
# ---------------------------------------------------------------------------
def chart_top_cuisines(df: pd.DataFrame, ctx: Context):
    # Each restaurant is counted once per cuisine it lists.
    bridge = ctx.cuisines[ctx.cuisines["rid"].isin(df["rid"])]
    counts = bridge.groupby("cuisine").size().reset_index(name="value").rename(columns={"cuisine": "label"})
    counts = counts.sort_values(["value", "label"], ascending=[False, True]).head(15)
    return counts.to_dict(orient="records")


def chart_by_location(df: pd.DataFrame, ctx: Context):
    counts = df.groupby("location").size().reset_index(name="value").rename(columns={"location": "label"})
    counts = counts.sort_values(["value", "label"], ascending=[False, True]).head(15)
    return counts.to_dict(orient="records")


def chart_rating_distribution(df: pd.DataFrame, ctx: Context):
    # 0.2-wide bins on the 0-5 scale; 5.0 falls in the last bin (4.8-5.0).
    rated = df["rating"].dropna()
    bin_index = np.minimum(np.floor(np.round(rated * 5, 6)), 24)
    counts = bin_index.value_counts().sort_index()
    return [{"bin_start": round(i / 5, 1), "bin_end": round(i / 5 + RATING_BIN_WIDTH, 1),
             "label": f"{i / 5:.1f}-{i / 5 + RATING_BIN_WIDTH:.1f}", "value": int(c)} for i, c in counts.items()]


def chart_price_tiers(df: pd.DataFrame, ctx: Context):
    tiers = df["price_tier"].dropna()
    counts = tiers.value_counts()
    return [{"label": t, "value": int(counts.get(t, 0))} for t in TIER_ORDER if counts.get(t, 0) > 0]


def chart_wr_by_cuisine(df: pd.DataFrame, ctx: Context):
    min_n = ctx.settings["min_group_n"]
    rows = ctx.cuisines.merge(df[["rid", "rating", "weighted_rating"]], on="rid")
    g = rows.groupby("cuisine").agg(listings=("rid", "size"), n_rated=("weighted_rating", "count"),
                                    mean_rating=("rating", "mean"), weighted_rating=("weighted_rating", "mean"))
    g = g.reset_index()
    g["sufficient_sample"] = g["n_rated"] >= min_n
    g = g.sort_values(["sufficient_sample", "weighted_rating", "cuisine"], ascending=[False, False, True])
    return _records(g)


def chart_median_cost_by_location(df: pd.DataFrame, ctx: Context):
    min_n = ctx.settings["min_group_n"]
    priced = df[df["cost"].notna()]
    g = priced.groupby("location").agg(n_cost=("cost", "size"), median_cost=("cost", "median"),
                                       mean_cost=("cost", "mean")).reset_index()
    g["sufficient_sample"] = g["n_cost"] >= min_n
    g = g.sort_values(["sufficient_sample", "median_cost", "location"], ascending=[False, False, True])
    return _records(g)


def chart_rating_vs_votes(df: pd.DataFrame, ctx: Context):
    # Deterministic sample of at most 2,000 points keeps the browser responsive.
    points = df.loc[df["rating"].notna() & df["review_count"].notna(),
                    ["rid", "restaurant_name", "rating", "review_count"] if "restaurant_name" in df
                    else ["rid", "rating", "review_count"]]
    total = len(points)
    if total > SCATTER_MAX_POINTS:
        points = points.sample(n=SCATTER_MAX_POINTS, random_state=SCATTER_SEED)
    return {"total_points": total, "shown_points": len(points), "points": _records(points)}


def distribution_profile(df: pd.DataFrame, ctx: Context):
    # Mean sits beside median because votes and cost are typically right-skewed.
    rows = []
    for col, label in (("rating", "Rating (0-5)"), ("review_count", "Votes / reviews"), ("cost", "Cost")):
        if col not in df:
            continue
        s = df[col].dropna()
        n = len(s)
        q = s.quantile([0.10, 0.25, 0.50, 0.75, 0.90]) if n else None
        rows.append({
            "metric": col, "label": label, "n": n,
            "mean": float(s.mean()) if n else None,
            "median": float(s.median()) if n else None,
            "std": float(s.std()) if n > 1 else None,
            "skewness": float(s.skew()) if n > 2 and s.nunique() > 1 else None,
            "min": float(s.min()) if n else None, "max": float(s.max()) if n else None,
            "p10": float(q[0.10]) if n else None, "p25": float(q[0.25]) if n else None,
            "p75": float(q[0.75]) if n else None, "p90": float(q[0.90]) if n else None,
            "iqr": float(q[0.75] - q[0.25]) if n else None,
        })
    return rows


def _records(frame: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe records with NaN converted to None."""
    clean = frame.astype(object).where(frame.notna(), None)
    out = clean.to_dict(orient="records")
    for row in out:
        for k, v in row.items():
            if isinstance(v, (np.integer,)):
                row[k] = int(v)
            elif isinstance(v, (np.floating,)):
                row[k] = float(v)
            elif isinstance(v, np.bool_):
                row[k] = bool(v)
    return out


def cost_outlier_impact(ctx: Context, f: Filters) -> Optional[dict]:
    """Rule 2: show which cost statistics change when IQR outliers are excluded."""
    with_out = apply_filters(ctx, Filters(**{**f.to_dict(), "exclude_outliers": False}))
    without = with_out[~with_out["cost_outlier"]]
    if cost_guard(with_out):
        return None
    def stats(frame):
        c = frame["cost"].dropna()
        return {"n": int(len(c)), "mean": float(c.mean()) if len(c) else None,
                "median": float(c.median()) if len(c) else None, "std": float(c.std()) if len(c) > 1 else None}
    return {"with_outliers": stats(with_out), "without_outliers": stats(without),
            "outliers": int(with_out["cost_outlier"].sum())}
