# KPI and metric definitions

Every metric below is implemented once in the backend (`backend/app/kpis.py` or `backend/app/stats.py`) and
registered in `backend/app/calculations.py` together with its equivalent DuckDB SQL (`backend/app/sql_queries.py`).
The **Show calculation** button shows the real pandas source and executes the SQL with the active filters; the two
results are compared with a relative and absolute tolerance of `1e-9` (also enforced by `tests/test_sql.py`).

General rules for every metric:

- **Population.** The *analysis rows*: de-duplicated rows with invalid rows removed, after the active filters.
- **Missing values.** Excluded from the metric, never treated as 0. A metric with no valid input shows **N/A**.
- **Precision.** Computed at full precision; rounded only for display (ratings 2 dp, costs 0 dp).
- **Currency.** Cost metrics are N/A when the selection contains more than one currency (choose a currency filter).
- **Sample size.** Group rankings require `n >= 10` rated restaurants by default (Settings → minimum group size).
  Smaller groups are shown with a "small n" marker and never ranked as winners.

## Headline KPIs

| KPI | Formula | Business meaning | Caveat |
|---|---|---|---|
| Restaurants analyzed | `COUNT(*)` of analysis rows | Size of the market slice being analysed | Listings, not open/active businesses |
| Mean rating | `mean(R)` over rated rows, R on 0-5 | Typical platform score | Unrated rows excluded; ratings are not revenue |
| Median rating | `median(R)` (linear interpolation) | Middle score, robust to extremes | Ratings cluster, so differences are small |
| Weighted rating | `mean(WR_i)`, `WR = v/(v+m)·R + m/(v+m)·C` | Score adjusted for how many votes back it | Needs rating **and** vote count; see below |
| Mean cost | `mean(cost)` over rows with cost | Average listed price (unit shown, e.g. for two) | Pulled up by expensive outliers |
| Median cost | `median(cost)` | "Typical" listed price | Listed/approximate prices, not spend |
| Total votes | `sum(votes)` | Volume of online engagement | Not visits or orders |
| Cuisines | `COUNT(DISTINCT cuisine)` via bridge table | Breadth of the cuisine mix | Depends on source labelling |
| Locations | `COUNT(DISTINCT location)` | Geographic coverage | Uses locality, else city, else region |

### Weighted (Bayesian) rating

`WR = v/(v+m)·R + m/(v+m)·C`

- `v` = vote/review count of the restaurant, `R` = its rating (0-5 scale),
- `C` = mean rating of all rated analysis rows **in the dataset version** (not the filtered slice, so a
  restaurant's WR does not change when filters change),
- `m` = prior strength: median of positive vote counts among rated rows (overridable in Settings).

Edge cases: `v = 0 → WR = C`; `v + m = 0 → WR = R`; missing `R` or `v` → WR is null. Group WR = mean of
restaurant-level WR within the group. Not computed when the dataset lacks a rating or a vote column.

## Chart and table metrics

| Metric | Definition | Caveat |
|---|---|---|
| Top cuisines | Listings per cuisine, top 15, ties by name | A restaurant is counted once per cuisine it lists |
| Restaurants by location | Listings per location, top 15 | Listing density, not demand |
| Rating distribution | Rated rows per 0.2-wide band; 5.0 falls in 4.8-5.0 | Float-safe binning (`floor(round(R·5, 6))`) |
| Price tier mix | Budget ≤ P33 < Mid-range ≤ P67 < Premium (per currency) | Dataset-relative tiers |
| Weighted rating by cuisine | Mean WR per cuisine + n rated + sufficiency flag | Small groups flagged |
| Median cost by location | Median, mean and n of cost per location | Mixed currencies → N/A |
| Rating vs votes | Scatter of rated rows with votes; ≤ 2,000 points (seeded sample) | Visual only; see Spearman |
| Distribution profile | n, mean, median, std, skewness, min, max, P10/25/75/90, IQR | Skewness is bias-corrected |
| Cost outlier impact | n, mean, median, std with vs without IQR outliers | Outliers are flagged, never deleted |

## Market analysis

| Metric | Definition | Caveat |
|---|---|---|
| Cuisine popularity | Listings, share (% of restaurants in selection), n rated, mean rating, WR, median votes | Shares add to > 100% |
| Location listing density | Listings and share per location, distinct cuisines, median cost | Supply of listings only |
| Price tier analysis | Per tier: listings, min/median/max cost, mean/median rating, WR, median votes | Tiers are terciles |
| Saturation (location quotient) | `LQ = (listings of cuisine in location / listings in location) / (listings of cuisine overall / all listings)` | LQ > 1 over-represented; not demand |
| High-rating, low-listing cuisines | WR > selection mean WR **and** listings < median cuisine listings **and** n ≥ min group size | Suggestion to investigate |
| Types by price tier | Mean WR per restaurant type within each tier | Small groups flagged |
| Fewer listings for a cuisine | Cuisine share of listings per location (locations with ≥ min group size listings), ascending | Few listings ≠ unmet demand |

## Opportunity Score (exploratory)

For each (location, cuisine) pair with at least `opportunity_min_n` (default 8) rated listings:

```
pct(x)  = (rank_min(x) − 1) / (n − 1)        # identical to SQL PERCENT_RANK(); one pair → 0
score   = 100 × (w1·pct(WR) + w2·pct(median votes) + w3·(1 − pct(listings)))
weights = 40 / 30 / 30 by default, normalized to sum to 1
```

Sensitivity view: top 5 under Default (40/30/30), Quality-heavy (60/20/20) and Saturation-heavy (20/20/60).
**Exploratory indicator, not a prediction of success.**

## Statistical tests

| Test | Definition | Requirements | Reported |
|---|---|---|---|
| Spearman rho | Pearson correlation of average ranks (scipy `spearmanr`) for rating, votes, cost pairs | n ≥ 10, both variables non-constant, cost only with one currency | rho, p, n, strength, "correlation is not causation" |
| Mann-Whitney U | Two-sided test of rating for Yes vs No (online ordering, table booking); unknown excluded | n ≥ 10 per group, not all ratings identical | U, p, rank-biserial `r = 2U/(n1·n2) − 1`, medians, n, confounding caveat |

SQL equivalents compute the same ranks / U statistic; p-values come from scipy (not available in SQL), which the
calculation dialog states explicitly.

## Data-quality metrics (per column, de-duplicated rows)

- **Completeness %** = non-empty source values / rows
- **Uniqueness %** = distinct non-empty values / non-empty values
- **Validity %** = parseable and in-range values / non-empty values (not assessed for unmapped columns)
