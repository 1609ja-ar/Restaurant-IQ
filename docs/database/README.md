# RestaurantIQ database (MongoDB)

MongoDB is the database of record. The backend (`backend/app/db.py`) creates every collection and index itself
when it starts (`ensure_indexes`, idempotent), so there is no schema script to run. Connection settings come from
`backend/.env`:

| Variable | Default |
|---|---|
| `RIQ_MONGO_URI` | `mongodb://127.0.0.1:27017` (local Community Server); for Atlas a `mongodb+srv://user:password@cluster/...` string |
| `RIQ_MONGO_DB` | `restaurantiq` |
| `RIQ_MONGO_TIMEOUT_MS` | `5000` |

MongoDB 5.0 or newer is required (source column names containing `.` or `$` are stored as field names);
6.0+ is recommended.

## Collections

| Collection | One document per | `_id` | Indexes | Contents |
|---|---|---|---|---|
| `users` | account | user id | **unique** `email` | name, email, bcrypt `password_hash` (plain passwords are never stored), `token_version`, `is_demo`, `created_at` |
| `uploads` | uploaded file | upload id | `owner_id` | file name, size, **SHA-256**, path of the raw file on disk, detected rows/columns, `owner_id` |
| `datasets` | imported version | `v1`, `v2`, ... | **unique** `version`; (`owner_id`, `version`); `source_upload_id` | name, source upload, raw/used row counts, `owner_id`, and `meta` (mapping, import settings, reconciliation, capability profile, cleaning log, quality report) |
| `restaurants` | cleaned listing | ObjectId | **unique** (`dataset_id`, `rid`); (`dataset_id`, `include_in_analysis`); (`dataset_id`, `location`); (`dataset_id`, `cuisines`); (`dataset_id`, `restaurant_type`) | canonical fields, the raw text of rating/votes/cost, quality flags (`is_unrated`, `is_invalid`, `cost_outlier`, ...), **`cuisines` and `restaurant_type` as arrays** in source order, `extra_columns` (unmapped source columns, unchanged) |
| `cleaning_log` | cleaning step | ObjectId | **unique** (`dataset_id`, `step_no`) | step, detail, rows affected |
| `column_quality` | source column | ObjectId | **unique** (`dataset_id`, `column_name`) | completeness / uniqueness / validity %, counts, note |
| `app_state` | setting | key | — | `version_counter`, `active_dataset:<user id>` (active version per user), `settings` |

Missing values are left out of a restaurant document (a missing field means "no value"); the flags are always
present. Cuisines and types are arrays rather than bridge tables: the multikey indexes answer "restaurants serving
Chinese" directly (`{"dataset_id": "v1", "cuisines": "Chinese"}`).

**Privacy.** Every `datasets` and `uploads` document carries `owner_id`; the API only returns a user's own
versions and answers 404 for anyone else's.

**Versions are immutable.** An import writes the restaurant rows, the log and the quality report first and the
`datasets` document last, so a version only becomes visible when it is complete; if anything fails, its rows are
removed. Version numbers come from an atomic `$inc` on `app_state.version_counter` and are never reused. (A
standalone MongoDB has no multi-document transactions; this ordering gives the same all-or-nothing result.)

## Where the calculations happen

KPIs, statistics, comparisons and reports are computed in **pandas** on the dataset version loaded from
MongoDB (cached per version), exactly as before; MongoDB stores and returns the data. The in-app SQL Playground
and "Show calculation" use **DuckDB** in memory on the same rows; they never send queries to MongoDB.

## Why raw files stay on disk

Uploaded files can be hundreds of MB and must remain byte-identical. A MongoDB document is limited to 16 MB, so
the database stores each file's path, size and **SHA-256 checksum** (in `uploads`), and the file stays in
`RIQ_DATA_DIR/uploads`. The checksum is verified before the original file is served; a modified file is
reported instead of being returned.

## Setup and checks

```powershell
Get-Service MongoDB                                   # local server must be Running
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
.\.venv\Scripts\python.exe -m app.db_check            # OK, or FAIL (reason) with the fix
.\.venv\Scripts\python.exe -m app.db_import           # optional, once: copy data saved in local-file mode
```

`db_check` connects, creates any missing collections/indexes, and prints `OK: connected to MongoDB <version>;
database 'restaurantiq' has all 7 collections and 12 indexes ...` or the exact failure (`not running`,
`unknown host`, `auth failed`, `auth required`, `no privileges`, `bad uri`, `tls`). The URI is shown with the
password replaced by `****`.

`db_import` copies accounts (same ids and bcrypt hashes, so the same login works), dataset versions with their raw
uploads, each user's active version and the analysis settings from `backend/data` into MongoDB. It is skipped
when MongoDB already contains dataset versions, so running it twice copies nothing more. `backend/data` is not
changed.

## Useful queries (mongosh or MongoDB Compass)

```javascript
use restaurantiq
db.datasets.find({}, {name: 1, raw_rows: 1, rows_used: 1, created_at: 1}).sort({version: 1})
db.restaurants.aggregate([
  {$match: {dataset_id: "v1", include_in_analysis: true}},
  {$group: {_id: "$location", listings: {$sum: 1}, mean_rating: {$avg: "$rating"}}},
  {$sort: {listings: -1}}])
db.restaurants.aggregate([
  {$match: {dataset_id: "v1"}}, {$unwind: "$cuisines"},
  {$group: {_id: "$cuisines", n: {$sum: 1}}}, {$sort: {n: -1}}, {$limit: 10}])
db.cleaning_log.find({dataset_id: "v1"}, {step_no: 1, step: 1, rows_affected: 1}).sort({step_no: 1})
```
