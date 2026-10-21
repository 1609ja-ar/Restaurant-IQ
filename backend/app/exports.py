"""Data exports: filtered CSV, BI-ready flat CSV and a Power BI / Tableau star schema.

All exports are generated on request from the active dataset version (never cached), and
carry the dataset version and generation time in their file names / metadata.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

import pandas as pd

from .kpis import Context, Filters, apply_filters

FLAT_COLUMNS = ["rid", "source_row", "restaurant_name", "address", "location", "locality", "city", "region", "country",
                "cuisines", "restaurant_type", "rating", "weighted_rating", "is_unrated", "review_count", "cost",
                "currency", "price_tier", "cost_outlier", "online_order", "table_booking", "latitude", "longitude"]


def _flatten(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in out.columns:
        if out[col].map(lambda v: isinstance(v, list)).any():
            out[col] = out[col].map(lambda v: ", ".join(v) if isinstance(v, list) else v)
    return out


def filtered_csv(ctx: Context, f: Filters) -> pd.DataFrame:
    """Analysis rows matching the filters, with every preserved source column."""
    df = apply_filters(ctx, f)
    drop = [c for c in df.columns if c.startswith("__")]
    return _flatten(df.drop(columns=drop))


def bi_flat(ctx: Context, f: Filters) -> pd.DataFrame:
    """Tidy, typed, one-row-per-restaurant table for BI tools (analysis rows only)."""
    df = apply_filters(ctx, f)
    cols = [c for c in FLAT_COLUMNS if c in df]
    return _flatten(df[cols])


def star_schema_zip(ctx: Context, f: Filters) -> bytes:
    df = apply_filters(ctx, f)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    locations = sorted(df["location"].dropna().unique().tolist())
    dim_location = pd.DataFrame({"location_key": range(1, len(locations) + 1), "location": locations})
    loc_counts = df.groupby("location").size()
    dim_location["listings"] = dim_location["location"].map(loc_counts).astype("Int64")
    loc_key = dict(zip(dim_location["location"], dim_location["location_key"]))

    bridge = ctx.cuisines[ctx.cuisines["rid"].isin(df["rid"])]
    cuisines = sorted(bridge["cuisine"].unique().tolist())
    dim_cuisine = pd.DataFrame({"cuisine_key": range(1, len(cuisines) + 1), "cuisine": cuisines})
    cuisine_key = dict(zip(dim_cuisine["cuisine"], dim_cuisine["cuisine_key"]))
    bridge_out = pd.DataFrame({"restaurant_key": bridge["rid"].astype(int).to_numpy(),
                               "cuisine_key": bridge["cuisine"].map(cuisine_key).astype(int).to_numpy()})

    fact = pd.DataFrame({
        "restaurant_key": df["rid"].astype(int).to_numpy(),
        "location_key": df["location"].map(loc_key).astype("Int64").to_numpy(),
        "restaurant_name": df["restaurant_name"].to_numpy(),
        "restaurant_type": df["restaurant_type"].map(lambda v: ", ".join(v) if isinstance(v, list) else v).to_numpy()
        if "restaurant_type" in df else None,
        "rating": df["rating"].to_numpy(), "weighted_rating": df["weighted_rating"].to_numpy(),
        "review_count": df["review_count"].to_numpy(), "cost": df["cost"].to_numpy(),
        "currency": df["currency"].to_numpy(), "price_tier": df["price_tier"].to_numpy(),
        "online_order": df["online_order"].to_numpy(), "table_booking": df["table_booking"].to_numpy(),
        "is_unrated": df["is_unrated"].to_numpy(), "cost_outlier": df["cost_outlier"].to_numpy(),
    })
    meta = {"dataset_id": ctx.dataset_id, "dataset_name": ctx.meta.get("name"), "is_sample_data": bool(ctx.meta.get("is_demo")),
            "generated_at": generated, "filters": f.describe() or ["None"], "rows": int(len(fact)),
            "bayesian_prior": ctx.prior, "price_unit": ctx.meta.get("price_unit"),
            "rating_scale": "0-5 (normalized)"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, frame in (("fact_restaurants.csv", fact), ("dim_location.csv", dim_location),
                            ("dim_cuisine.csv", dim_cuisine), ("bridge_restaurant_cuisine.csv", bridge_out)):
            z.writestr(name, frame.to_csv(index=False))
        z.writestr("metadata.json", json.dumps(meta, indent=2, default=str))
        z.writestr("README.md", _star_readme(meta))
    return buf.getvalue()


def _star_readme(meta: dict) -> str:
    sample = "\n> Sample data - illustrative only. Not real market evidence.\n" if meta["is_sample_data"] else ""
    return f"""# RestaurantIQ star schema export
{sample}
Dataset: {meta['dataset_name']} ({meta['dataset_id']}) - generated {meta['generated_at']} - {meta['rows']} restaurants.
Filters: {'; '.join(meta['filters'])}

## Tables
| File | Grain | Keys |
|---|---|---|
| fact_restaurants.csv | one row per restaurant (analysis rows) | restaurant_key (PK), location_key (FK) |
| dim_location.csv | one row per location | location_key (PK) |
| dim_cuisine.csv | one row per cuisine | cuisine_key (PK) |
| bridge_restaurant_cuisine.csv | one row per restaurant x cuisine | restaurant_key, cuisine_key |

## Relationships
- fact_restaurants.location_key -> dim_location.location_key (many-to-one)
- bridge_restaurant_cuisine.restaurant_key -> fact_restaurants.restaurant_key (many-to-one)
- bridge_restaurant_cuisine.cuisine_key -> dim_cuisine.cuisine_key (many-to-one)

The restaurant-cuisine relationship is many-to-many, so it goes through the bridge table.

## Power BI
1. Get Data -> Text/CSV, load all four CSV files.
2. Model view: create the three relationships above. For bridge -> fact set cross-filter direction to **Both**
   so a cuisine slicer filters restaurants.
3. Example measures:
   - Restaurants = DISTINCTCOUNT(fact_restaurants[restaurant_key])
   - Median rating = MEDIAN(fact_restaurants[rating])   (blank ratings are unrated, not zero)
   - Weighted rating = AVERAGE(fact_restaurants[weighted_rating])

## Tableau
1. Connect -> Text file -> fact_restaurants.csv; drag the other files onto the canvas.
2. Use relationships (not joins): fact <-> dim_location on location_key, fact <-> bridge on restaurant_key,
   bridge <-> dim_cuisine on cuisine_key.
3. Use COUNTD([Restaurant Key]) for counts so multi-cuisine restaurants are not double counted.

## Notes
- rating is normalized to 0-5; empty means unrated (excluded from rating averages), never zero.
- cost is in the listed currency and unit ({meta['price_unit']}); do not sum costs across currencies.
- Duplicates and invalid rows are already excluded.
"""
