# Interview notes: RestaurantIQ

Ten likely questions with concise answers.

**1. Why a Bayesian (weighted) rating instead of the average rating?**
A 4.9 from 3 votes is less trustworthy than a 4.5 from 3,000. `WR = v/(v+m)·R + m/(v+m)·C` blends each
restaurant's rating R with the dataset mean C, weighted by its votes v against a prior strength m (here the median
of positive vote counts, 33 in the sample). Few votes → close to C; many votes → close to R. C and m come from the
whole dataset version so a restaurant's score doesn't change when you filter. m is adjustable in Settings, and
m = 0 gives back the raw rating.

**2. Why Mann-Whitney U and not a t-test?**
Ratings are bounded, discrete and not normally distributed, and group sizes differ. Mann-Whitney compares rank
distributions without assuming normality. I report the p-value *and* an effect size (rank-biserial
r = 2U/(n₁n₂) − 1), because with large n a tiny, irrelevant difference can be "significant". Unknown Yes/No values
are excluded, each group needs n ≥ 10, and I state the confounding caveat: table-booking restaurants are also more
expensive and more often casual or fine dining.

**3. Why show the median next to the mean?**
Votes (skewness 10.4) and cost (4.8) are right-skewed: a few huge values pull the mean up. In the sample, mean cost
is INR 681 but the median is INR 450; removing 37 IQR outliers moves the mean to INR 573 while the median stays at
INR 450. The median is the better "typical" value; the mean is still useful for totals.

**4. How do you handle duplicates?**
Key = restaurant name + address after lower-casing and removing punctuation and extra spaces, so "SPICE KITCHEN"
and "spice kitchen." match. I keep the row with the most votes (the most complete listing); ties keep the earliest
row, so the result is deterministic. The reconciliation shows how many were removed and lists source row pairs.
Without a name column, only exact duplicate rows are removed. I avoid fuzzy matching because false merges would
silently delete real restaurants.

**5. How do you know your numbers are right?**
Three layers. (a) Hand-calculated unit tests on tiny fixtures for every cleaning rule and KPI. (b) Every metric
has a pandas implementation and an equivalent DuckDB SQL query; tests run both for 26 calculations under 7 filter
combinations and require agreement within 1e-9, and the UI's "Show calculation" re-runs the SQL live. (c) An
independent notebook re-implements cleaning and KPIs from the written rules and compares with the API: 19/19 PASS.

**6. What's the difference between unrated and invalid rows?**
Unrated means no usable rating ("NEW", "-", blank). The restaurant is real, so it stays in counts, cost and
location analysis but is excluded from rating statistics. Invalid means an impossible value (rating 6.2/5,
negative votes or cost). Those rows are kept in the cleaned file with flags but excluded from all analysis.
Reconciliation: raw 804 − 24 duplicates − 6 invalid = 774 used, of which 46 are unrated.

**7. How does the app work with datasets other than Zomato?**
Nothing is hard-coded to one schema. On upload it profiles every column (type, missingness, samples) and suggests
a canonical field with a confidence and reason from header synonyms plus value checks. The user confirms or
changes the mapping, the rating scale and the currency. A capability profile then switches features on or off:
no vote column means no weighted rating, and the UI says why instead of showing zeros.

**8. What does the Opportunity Score mean, and what are its weaknesses?**
For each cuisine × location pair with at least 8 rated listings it combines percentiles of weighted rating (40%),
median votes as engagement (30%) and low listing count (30%). It is an exploratory ranking: it depends on the
weights, uses ratings rather than demand, and small pairs are noisy. That's why there are sliders, a sensitivity
view across three weightings, and the label "not a prediction of success".

**9. Why DuckDB in addition to pandas?**
Analysts think in SQL, and BI tools consume SQL-shaped data. DuckDB runs in-process on the same DataFrames with
no server. I use it for the read-only SQL Playground (single SELECT only, external file access disabled,
configuration locked, 5 s timeout, 1,000-row cap) and to independently verify every pandas metric.

**10. How did you remove the 50 MB upload limit safely?**
I removed the hard-coded check and message in the frontend, and confirmed the backend and Vite proxy impose no
body limit. Uploads stream to disk in 1 MB blocks, CSVs are read in 100k-row chunks, and malformed files are
rejected with the exact line number, never truncated. A regression test uploads a ~55 MB, 60,000-row CSV and
asserts that all rows are imported. The README documents the real limits that remain: RAM, disk, processing time,
XLSX memory use and any reverse-proxy body limit.
