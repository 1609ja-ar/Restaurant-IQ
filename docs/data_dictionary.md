# Data dictionary

RestaurantIQ maps any reasonably structured restaurant file onto a flexible canonical model. **Every field is
optional.** Unmapped source columns are preserved unchanged (renamed with a `src_` prefix only if their name
collides with a canonical or internal name). Features that need a missing field are disabled with an explanation.

## Canonical fields (set by the column mapping)

| Field | Kind | Parsing rule | Example source headers |
|---|---|---|---|
| restaurant_name | text | trimmed; blank → null | name, restaurant, business_name |
| address | text | trimmed | address, full_address |
| locality | text | trimmed | location, locality, neighborhood, area |
| city / region / country | text | trimmed | city, state, country |
| cuisines | list | split on `, \| ;`, trimmed, title-cased, de-duplicated | cuisines, cuisine |
| restaurant_type | list | same as cuisines | rest_type, category, type |
| rating | number | `x/y` or plain number; NEW / - / blank / text → null (unrated); normalized to 0-5 | rate, rating, stars, aggregate_rating |
| review_count | number ≥ 0 | thousands separators removed; negative → invalid | votes, review_count, num_reviews |
| cost | number ≥ 0 | currency symbols/codes and separators removed; negative → invalid | approx_cost(for two people), price, average_cost_for_two |
| currency | text | upper-cased; else dataset-level currency chosen at import | currency |
| online_order / table_booking | true/false/null | Yes/Y/True/1 and No/N/False/0; anything else → null | online_order, has_online_delivery, book_table |
| latitude / longitude | number | must be within ±90 / ±180, else null | lat, lng |
| review_text, menu_items, opening_hours | text | trimmed | reviews_list, dish_liked, hours |
| source_date | date | parsed if possible, else null | date, listing_date |

## Derived and audit columns (cleaned dataset)

| Column | Type | Meaning |
|---|---|---|
| rid, source_row | int | 1-based data row number in the raw file; `rid` is the restaurant id everywhere |
| location | text | Grouping location: locality, else city, else region, else country |
| rating_source | number | Rating on the original scale (before normalization) |
| rating_raw, review_count_raw, cost_raw | text | Values exactly as written in the file |
| is_unrated | bool | Rating missing/unparseable (kept for non-rating analysis) |
| rating_invalid, votes_invalid, cost_invalid | bool | Out-of-range values (rule 6) |
| is_invalid, invalid_reason | bool, text | Any invalid flag and the reason(s) |
| include_in_analysis | bool | `not is_invalid` |
| cost_outlier | bool | Outside Q1 − 1.5·IQR … Q3 + 1.5·IQR within its currency |
| price_tier | text | Budget / Mid-range / Premium (cost terciles per currency) |
| weighted_rating | number | Computed at analysis time from the active Bayesian prior (exports include it) |

Duplicates are removed from the cleaned dataset; their source row numbers and the row kept instead are listed in
the reconciliation (`duplicate_examples`). The original upload is always available unchanged.

## DuckDB tables (SQL Playground and Show calculation)

| Table | Grain | Notes |
|---|---|---|
| restaurants | one row per analysis row | lists joined as "A, B"; NULL = missing |
| restaurant_cuisines | restaurant × cuisine | bridge table (`rid`, `cuisine`) |
| restaurant_types | restaurant × type | bridge table (`rid`, `restaurant_type`) |

## Star-schema export

`fact_restaurants` (restaurant_key, location_key, measures), `dim_location`, `dim_cuisine`,
`bridge_restaurant_cuisine`, plus `README.md` and `metadata.json` describing version, filters and load steps.

## Demo dataset (synthetic, illustrative only)

`backend/app/demo_data.py` generates 804 raw rows (780 listings + 24 duplicates) with seed 42 using
Zomato-style column names: `name, address, location, rest_type, cuisines, rate, votes,
approx_cost(for two people), online_order, book_table, dish_liked`. Bangalore locations, cuisines and cost ranges
apply to this demo only.
