# Assumptions log

Decisions that affect numbers, with the reason and how to change them.

| # | Assumption / decision | Why | Where | Change by |
|---|---|---|---|---|
| A1 | Empty and whitespace-only cells are missing (null). "NA", "None" text stays text and is parsed by field rules. | Distinguish missing from real values without guessing | `ingest.py`, `cleaning.py` | Code |
| A2 | Rating scale is confirmed by the user at import; suggestions come from `x/y` denominators or the 95th percentile of numeric values. Ratings are normalized to 0-5 only after confirmation. | Avoid assuming a 0-5 scale | Data page mapping | Import setting |
| A3 | Unparseable ratings ("NEW", "-", text) are **unrated**, not invalid. Out-of-scale numbers are **invalid**. | Matches the documented rule 1 / rule 6 split | `cleaning.py` | Code |
| A4 | Invalid rows (rating outside scale, negative votes, negative cost) are excluded from **all** analysis, not just the affected metric. | Keeps one consistent population; counts reconcile | `cleaning.py` | Code |
| A5 | Unparseable votes/costs become null (missing) and lower validity %, but do not make the row invalid. | Rule 6 lists only out-of-range values as invalid | `cleaning.py` | Code |
| A6 | Duplicate key = normalized name + address (fallback: name + locality/city; no name → exact duplicates). Keep most votes, ties → earliest row. Rows without a name are not de-duplicated. | Deterministic, explainable rule | `cleaning._deduplicate` | Code |
| A7 | De-duplication happens before invalid-row exclusion; negative votes rank lowest. | A valid listing should win over an invalid copy | `cleaning._deduplicate` | Code |
| A8 | Bayesian prior C and m come from the whole dataset version, not the filtered slice. | A restaurant's WR is stable across filters | `kpis.bayes_prior` | Settings (m) |
| A9 | Group sample threshold n ≥ 10 (Opportunity Score n ≥ 8). | Avoid ranking tiny groups | Settings | Settings |
| A10 | Price tiers are terciles of analysis-row costs per currency, computed once per version (not per filter). | Tier labels mean the same thing everywhere | `cleaning.py` | Code |
| A11 | IQR outliers are computed per currency and flagged only. | Never delete data silently | `cleaning.py` | "Exclude cost outliers" filter |
| A12 | Mixed currencies: cost metrics return N/A unless a single currency is selected; no exchange-rate conversion. | No documented exchange-rate source | `kpis.cost_guard` | Currency filter |
| A13 | Location for grouping = locality, else city, else region, else country. | Most granular available label | `cleaning.py` | Mapping |
| A14 | Rating filter (min/max) excludes unrated rows. | An unrated row cannot satisfy a rating range | `kpis.apply_filters` | — |
| A15 | Scatter plot shows at most 2,000 points (pandas sample, seed 42); statistics use all rows. | Browser responsiveness | `kpis.chart_rating_vs_votes` | Code |
| A16 | XLSX: only the first sheet with data is read (a warning lists other sheets). | Predictable import | `ingest.py` | Re-save sheet |
| A17 | Non-UTF-8 CSV files are read as Windows-1252 with a warning. | Common for Excel-exported CSV | `ingest.py` | Re-save as UTF-8 |
| A18 | No fixed upload size limit in the app. Practical limits: RAM (whole cleaned dataset is held in memory), disk (raw file + cleaned pickle per version), processing time. XLSX needs much more memory than CSV. | Requirement: no arbitrary 50 MB cap | `main.py`, `store.py` | Infrastructure |
| A19 | AI Analyst answers on the full active dataset (no filters). | Answers must be reproducible from the question | `analyst.py` | — |
| A20 | The LLM (when configured) only receives the computed JSON result, never raw data. | Numbers must come from the analysis | `analyst.py` | `.env` |
| A21 | MongoDB is the database of record (accounts, versions, cleaned rows with cuisines/types as arrays, log, quality, settings). Raw uploads stay byte-identical on disk; MongoDB stores their SHA-256, verified before download. | Large files exceed the 16 MB document limit; integrity check | `db.py` | `RIQ_STORAGE`, `RIQ_MONGO_URI` |
| A22 | Selecting every value of a filter keeps only rows that **have** a value for that field (e.g. all price tiers excludes restaurants without a cost). | A filter means "is one of these values"; missing is not a value | `kpis.apply_filters` | — |
| A23 | Sessions are HS256 JWTs (60 min) in an HttpOnly, SameSite=Lax cookie (`riq_session`), not in localStorage/sessionStorage. | Page scripts (and any XSS) cannot read the token; SameSite blocks cross-site form posts. Tradeoff: needs same-site frontend/API (Vite proxy) and HTTPS + `COOKIE_SECURE=true` in production. | `auth.py` | `.env` |
| A24 | Logout and password changes revoke tokens via an in-memory jti list and a per-user `token_version`. | Stateless JWTs cannot be withdrawn otherwise. The jti list resets on restart (tokens still expire within 60 min); `token_version` is persistent. | `auth.py` | — |
| A25 | Failed sign-ins are limited to 5 per 15 minutes per email and per client IP (HTTP 429), in memory. | Slows password guessing without extra infrastructure. Not shared across several backend processes; resets on restart. | `auth.LoginLimiter` | Code |
| A26 | Multi-user ownership: every dataset version and upload stores `owner_id`; other users get 404 (not 403) so existence is not revealed. Active version is per user. Analysis settings stay global. | Real isolation of data between accounts with minimal change to the analytics code. | `main.owned_meta`, stores | — |
| A27 | Data imported before accounts existed is given to the demo account (if `DEMO_USER_EMAIL` is set) or otherwise to the first registered account. | Keeps the existing single-user data usable after login is added. | `auth.seed_demo_user`, `auth.register` | `.env` |
| A28 | Users are stored in the storage backend (MongoDB `users` collection with a unique email index, or `users.json` in file mode). | One place for all data; the unique index makes duplicate sign-ups impossible even when two arrive at once. | `db.py`, `store.py` | — |
| A29 | A standalone MongoDB has no multi-document transactions, so an import writes rows, log and quality report first and the `datasets` document last (removing the rows on failure); version numbers come from an atomic counter and are never reused. If MongoDB is down the API still starts and answers 503 with the reason. | All-or-nothing versions without requiring a replica set; a clear message instead of a dead backend. | `db.MongoStore.create_dataset`, `main.lifespan` | — |
