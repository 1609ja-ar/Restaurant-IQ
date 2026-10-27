# Case study: RestaurantIQ

> All numbers below were computed by RestaurantIQ from its **synthetic sample dataset** (seed 42, dataset
> "Sample data — illustrative only"). They demonstrate the method; they are not real market evidence about
> Bangalore. Re-running the app on the sample data reproduces them exactly.

## Business problem

Entrepreneurs and restaurant operators deciding *what* to open and *where* usually look at listing platforms
informally. They need a structured, honest view: which segments look strong, where listings are crowded, how
price relates to rating, and which conclusions the data can and cannot support.

## Stakeholders

- **Prospective restaurant founders**: shortlist cuisine and location combinations to investigate.
- **Operators / chains**: benchmark a cuisine or location against the market.
- **Analysts**: need reproducible numbers, visible calculations and exports for Power BI / Tableau.

## Dataset

The demo file mimics a Zomato-style export: 804 raw rows, 11 columns (name, address, location, type, cuisines,
rating text like "4.1/5", votes, "approx cost for two" with thousands separators, Yes/No flags, dishes). It
deliberately contains unrated rows, duplicates, invalid values and cost outliers. The app is dataset-agnostic:
uploads with other headers, scales (e.g. 0-10) and currencies are mapped and validated at import.

## Cleaning decisions and impact

| Step | Rows | Impact |
|---|---|---|
| Raw rows | 804 | |
| Duplicates removed (normalized name + address, keep most votes) | −24 | 780 unique listings |
| Invalid rows excluded (rating outside 0-5: 3, negative votes: 2, negative cost: 1) | −6 | |
| **Rows used in analysis** | **774** | reconciliation balances |
| Unrated rows kept (NEW / - / blank) | 46 | excluded only from rating statistics → 728 rated |
| Cost outliers flagged (1.5 × IQR, kept) | 37 | mean cost INR 681 → 573 without them; median stays INR 450 |

Missing costs and unknown Yes/No values stay null rather than 0 / "No", so they cannot distort averages or test groups.

## Methods

Descriptive KPIs (mean *and* median, because votes are heavily skewed: skewness 10.4; cost skewness 4.8),
a Bayesian weighted rating (C = 3.95, m = 33 votes), listing share and location quotients, cost terciles
(Budget ≤ INR 350 < Mid-range ≤ INR 700 < Premium), Spearman correlations, Mann-Whitney U tests with rank-biserial
effect sizes, and an exploratory Opportunity Score with a sensitivity check. Every metric is computed in pandas and
cross-checked against DuckDB SQL; an independent notebook re-implements the cleaning and KPIs (19/19 checks PASS).

Each import is stored in MongoDB as an immutable, numbered version: one document per cleaned listing (with its quality flags and its cuisines as an array), plus the cleaning log and column-quality report, all private to the account that imported it. The raw file stays byte-identical on disk with a SHA-256 checksum, so any number in this case study can be traced back to the exact source file and cleaning run.

## Five key insights (computed) and recommended actions

1. **North Indian dominates listings.** 146 of 774 restaurants (18.9%) list North Indian; Chinese follows with 136.
   *Action:* treat North Indian and Chinese as crowded categories; a new entrant needs a clear differentiator,
   so look at the location quotient before choosing a site.

2. **Some under-listed cuisines rate above average.** Japanese (weighted rating 4.03, 11 listings, n = 10),
   Burger (4.02, 42 listings) and Arabian (4.02, 22 listings) beat the dataset's mean weighted rating of 3.96 while
   having fewer listings than the median cuisine (45). *Action:* shortlist these for demand validation (search
   trends, delivery-app category volumes, competitor visits). Japanese sits exactly at the n = 10 threshold, so
   treat it as the least reliable of the three.

3. **Premium venues rate slightly higher, but the effect is small.** Mean rating is 3.90 (Budget, median cost
   INR 300), 3.94 (Mid-range, INR 500) and 4.01 (Premium, INR 1,100); Spearman rho between rating and cost is
   0.16 (n = 717, p < 0.001). This is a weak association, not evidence that charging more improves ratings.
   *Action:* don't price up to chase ratings; position price on concept and location economics.

4. **Table booking shows a small rating difference; online ordering shows none.** Table-booking restaurants have a
   median rating of 4.0 vs 3.9 (Mann-Whitney p = 0.019, rank-biserial r = 0.11, weak). For online ordering,
   p = 0.156 and r = −0.06 (no significant difference). Table booking is confounded with restaurant type and
   price. *Action:* decide on reservations from the format (casual/fine dining), not because of the rating gap.

5. **The top exploratory opportunity is robust to the weights.** Desserts in Marathahalli scores 85/100
   (n = 8 rated listings) and stays first under all three weightings (40/30/30, 60/20/20, 20/20/60). North Indian in
   Brigade Road and Whitefield also appear in two of three lists. *Action:* this is the first candidate for field
   research: footfall, rents and dessert-shop competition in Marathahalli. The small n means the score is only
   a pointer.

## Limitations

- Synthetic sample data in this case study; real conclusions need a real dataset.
- Snapshot of listings; no time trend.
- Ratings are user-generated platform scores; votes measure online engagement, not visits.
- No revenue, footfall, demand or profit data; costs are approximate listed prices for two.
- Observational analysis: correlation is not causation, and group comparisons are confounded.

## Next steps

1. Import a real export (Zomato, Google Maps, Yelp) and repeat the analysis with the same rules.
2. Add monthly snapshots to measure openings, closures and rating trends.
3. Join delivery-order or POS data to move from ratings to demand.
4. Add geographic coordinates to replace location labels with distance-based catchments.
