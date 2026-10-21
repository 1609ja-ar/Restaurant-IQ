"""Side-by-side comparison of 2-4 restaurants, cuisines or locations.

Group metrics reuse the same KPI functions as the Dashboard, so "Thai" here equals the
Dashboard filtered to cuisine = Thai. Summaries are templated from computed values and
make no causal claims.
"""
from __future__ import annotations

import pandas as pd

from . import kpis
from .kpis import Context, Filters, apply_filters, cost_guard

GROUP_METRICS = [
    {"key": "listings", "label": "Listings", "format": "int"},
    {"key": "n_rated", "label": "Rated restaurants", "format": "int"},
    {"key": "mean_rating", "label": "Mean rating", "format": "rating"},
    {"key": "median_rating", "label": "Median rating", "format": "rating"},
    {"key": "weighted_rating", "label": "Weighted rating", "format": "rating"},
    {"key": "median_cost", "label": "Median cost", "format": "money"},
    {"key": "mean_cost", "label": "Mean cost", "format": "money"},
    {"key": "median_votes", "label": "Median votes", "format": "int"},
    {"key": "online_order_share", "label": "Online ordering (of known)", "format": "pct"},
    {"key": "table_booking_share", "label": "Table booking (of known)", "format": "pct"},
]
RESTAURANT_METRICS = [
    {"key": "rating", "label": "Rating", "format": "rating"},
    {"key": "weighted_rating", "label": "Weighted rating", "format": "rating"},
    {"key": "review_count", "label": "Votes", "format": "int"},
    {"key": "cost", "label": "Cost", "format": "money"},
    {"key": "price_tier", "label": "Price tier", "format": "text"},
    {"key": "location", "label": "Location", "format": "text"},
    {"key": "cuisines", "label": "Cuisines", "format": "text"},
    {"key": "restaurant_type", "label": "Type", "format": "text"},
    {"key": "online_order", "label": "Online ordering", "format": "bool"},
    {"key": "table_booking", "label": "Table booking", "format": "bool"},
]


def _share_true(series: pd.Series):
    known = series.dropna()
    return float((known == True).mean()) if len(known) else None  # noqa: E712


def group_profile(df: pd.DataFrame, ctx: Context) -> dict:
    """Metrics for one group, computed with the shared KPI functions."""
    cost_ok = cost_guard(df) is None
    rated = df["rating"].dropna()
    return {
        "listings": kpis.kpi_total_restaurants(df, ctx),
        "n_rated": int(len(rated)),
        "mean_rating": kpis.kpi_mean_rating(df, ctx),
        "median_rating": kpis.kpi_median_rating(df, ctx),
        "weighted_rating": kpis.kpi_weighted_rating(df, ctx),
        "median_cost": kpis.kpi_median_cost(df, ctx) if cost_ok else None,
        "mean_cost": kpis.kpi_mean_cost(df, ctx) if cost_ok else None,
        "median_votes": float(df["review_count"].median()) if df["review_count"].notna().any() else None,
        "online_order_share": _share_true(df["online_order"]),
        "table_booking_share": _share_true(df["table_booking"]),
    }


def compare(ctx: Context, kind: str, items: list[str], base: Filters | None = None) -> dict:
    base = base or Filters()
    min_n = ctx.settings["min_group_n"]
    entities = []
    if kind == "restaurant":
        frame = apply_filters(ctx, base)
        for item in items:
            try:
                rid = int(item)
            except ValueError:
                raise ValueError(f"'{item}' is not a restaurant id.")
            row = frame[frame["rid"] == rid]
            if row.empty:
                raise ValueError(f"Restaurant {rid} is not in the analysis rows of this dataset version.")
            rec = kpis._records(row)[0]
            entities.append({"id": str(rid), "name": rec.get("restaurant_name") or f"Row {rid}",
                             "values": {m["key"]: rec.get(m["key"]) for m in RESTAURANT_METRICS},
                             "sample_size": 1, "sufficient_sample": None})
        metrics = RESTAURANT_METRICS
    else:
        field = "cuisine" if kind == "cuisine" else "location"
        if not ctx.capabilities["fields"][field]:
            raise ValueError(f"This dataset has no {field} column to compare.")
        for item in items:
            f = Filters(**{**base.to_dict(), field: [item]})
            df = apply_filters(ctx, f)
            if df.empty:
                raise ValueError(f"No restaurants found for {field} '{item}' in the current selection.")
            prof = group_profile(df, ctx)
            entities.append({"id": item, "name": item, "values": prof, "sample_size": prof["listings"],
                             "sufficient_sample": prof["n_rated"] >= min_n})
        metrics = GROUP_METRICS
    currencies = sorted(set(ctx.capabilities["currencies"]))
    return {"kind": kind, "metrics": metrics, "entities": entities, "summary": _summary(kind, entities, min_n),
            "cost_unit": currencies[0] if len(currencies) == 1 else base.currency,
            "caveats": ["Comparisons describe listings; they do not show why one option rates or costs more.",
                        "Ratings are platform scores, not revenue, demand, footfall or profit.",
                        f"Groups with fewer than {min_n} rated restaurants are marked as small samples."]}


def _summary(kind: str, entities: list[dict], min_n: int) -> list[str]:
    out = []

    def best(key, highest=True):
        vals = [(e["values"].get(key), e["name"]) for e in entities if isinstance(e["values"].get(key), (int, float))
                and not isinstance(e["values"].get(key), bool)]
        if len(vals) < 2:
            return None
        return (max if highest else min)(vals)

    wr = best("weighted_rating")
    if wr:
        out.append(f"Highest weighted rating: {wr[1]} ({wr[0]:.2f}).")
    cost = best("median_cost" if kind != "restaurant" else "cost", highest=False)
    if cost:
        out.append(f"Lowest {'median ' if kind != 'restaurant' else ''}cost: {cost[1]} ({cost[0]:,.0f}).")
    if kind != "restaurant":
        listings = best("listings")
        if listings:
            out.append(f"Most listings: {listings[1]} ({listings[0]:,}).")
        small = [e["name"] for e in entities if e["sufficient_sample"] is False]
        if small:
            out.append(f"Small samples (fewer than {min_n} rated): {', '.join(small)}; treat their ratings as indicative only.")
    else:
        votes = best("review_count")
        if votes:
            out.append(f"Most votes: {votes[1]} ({votes[0]:,.0f}); more votes make a rating more reliable, not better.")
    return out
