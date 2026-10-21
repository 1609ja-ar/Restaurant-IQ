"""DuckDB layer: tables, filter -> SQL translation, metric SQL and the read-only Playground.

DuckDB sees three tables built from the active dataset's analysis rows:
  restaurants          one row per restaurant (lists joined as "A, B" text)
  restaurant_cuisines  bridge: rid, cuisine          (one row per restaurant x cuisine)
  restaurant_types     bridge: rid, restaurant_type

The SQL shown by "Show calculation" is rendered from the templates below with the
active filters inlined as escaped literals, and is the exact text that gets executed.
"""
from __future__ import annotations

import re
import threading
import time

import duckdb
import numpy as np
import pandas as pd

from .kpis import Context, Filters

SQL_TIMEOUT_SECONDS = 5
SQL_MAX_ROWS = 1000

TABLE_COLUMNS = ["rid", "source_row", "restaurant_name", "address", "location", "locality", "city", "region",
                 "country", "cuisines", "restaurant_type", "rating", "rating_source", "review_count",
                 "weighted_rating", "cost", "currency", "price_tier", "cost_outlier", "is_unrated",
                 "online_order", "table_booking", "latitude", "longitude", "source_date"]
BOOL_COLUMNS = {"cost_outlier", "is_unrated", "online_order", "table_booking"}


class SqlError(Exception):
    """User-facing SQL problem (message is safe to show)."""


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
def flat_restaurants(frame: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in TABLE_COLUMNS if c in frame]
    flat = frame[cols].copy()
    for c in ("cuisines", "restaurant_type"):
        if c in flat:
            flat[c] = flat[c].map(lambda v: ", ".join(v) if isinstance(v, list) else None)
    for c in BOOL_COLUMNS & set(flat.columns):
        flat[c] = flat[c].astype("boolean")
    for c in ("rating", "rating_source", "review_count", "weighted_rating", "cost", "latitude", "longitude"):
        if c in flat:
            flat[c] = pd.to_numeric(flat[c], errors="coerce").astype("Float64")  # NaN -> SQL NULL
    for c in ("restaurant_name", "address", "location", "locality", "city", "region", "country", "currency",
              "price_tier"):
        if c in flat:
            flat[c] = flat[c].astype("string")
    return flat


def connect(ctx: Context, read_only_sandbox: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.register("restaurants_df", flat_restaurants(ctx.frame))
    con.register("cuisines_df", ctx.cuisines.astype({"cuisine": "string"}))
    con.register("types_df", ctx.types.astype({"restaurant_type": "string"}))
    # Materialize as real tables so the schema browser and DESCRIBE show clean types.
    con.execute("CREATE TABLE restaurants AS SELECT * FROM restaurants_df")
    con.execute("CREATE TABLE restaurant_cuisines AS SELECT rid, cuisine FROM cuisines_df")
    con.execute("CREATE TABLE restaurant_types AS SELECT rid, restaurant_type FROM types_df")
    for name in ("restaurants_df", "cuisines_df", "types_df"):
        con.unregister(name)
    if read_only_sandbox:
        con.execute("SET enable_external_access = false")   # no file or network access
        con.execute("SET lock_configuration = true")        # user SQL cannot re-enable it
    return con


# ---------------------------------------------------------------------------
# Filters -> SQL
# ---------------------------------------------------------------------------
def lit(value) -> str:
    """Escape a Python value as a SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, np.integer, np.floating)):
        return repr(float(value)) if isinstance(value, (float, np.floating)) else str(int(value))
    return "'" + str(value).replace("'", "''") + "'"


def in_list(values) -> str:
    return "(" + ", ".join(lit(v) for v in values) + ")"


def filter_conditions(f: Filters) -> list[str]:
    """Same semantics as kpis.apply_filters, expressed as SQL on alias r."""
    conds = []
    if f.location:
        conds.append(f"r.location IN {in_list(f.location)}")
    if f.cuisine:
        conds.append(f"r.rid IN (SELECT rid FROM restaurant_cuisines WHERE cuisine IN {in_list(f.cuisine)})")
    if f.restaurant_type:
        conds.append(f"r.rid IN (SELECT rid FROM restaurant_types WHERE restaurant_type IN {in_list(f.restaurant_type)})")
    if f.price_tier:
        conds.append(f"r.price_tier IN {in_list(f.price_tier)}")
    if f.rating_min is not None:
        conds.append(f"r.rating >= {lit(float(f.rating_min))}")
    if f.rating_max is not None:
        conds.append(f"r.rating <= {lit(float(f.rating_max))}")
    if f.online_order is not None:
        conds.append(f"r.online_order = {lit(f.online_order)}")
    if f.table_booking is not None:
        conds.append(f"r.table_booking = {lit(f.table_booking)}")
    if f.currency:
        conds.append(f"r.currency = {lit(f.currency)}")
    if f.search:
        escaped = f.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conds.append(f"r.restaurant_name ILIKE {lit('%' + escaped + '%')} ESCAPE '\\'")
    if f.exclude_outliers:
        conds.append("NOT r.cost_outlier")
    return conds


def render(template: str, f: Filters, **params) -> str:
    conds = filter_conditions(f)
    where = ("WHERE " + "\n  AND ".join(conds)) if conds else ""
    and_filters = ("\n  AND " + "\n  AND ".join(conds)) if conds else ""
    rids = f"(SELECT r.rid FROM restaurants r {where})" if conds else "(SELECT rid FROM restaurants)"
    fmt = {k: (lit(v) if not isinstance(v, str) else v) for k, v in params.items()}
    return template.format(where=where, and_filters=and_filters, rids=rids, **fmt).strip()


def execute(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, _py_row(row))) for row in cur.fetchall()]


def _py_row(row):
    out = []
    for v in row:
        if isinstance(v, float) and np.isnan(v):
            out.append(None)
        elif hasattr(v, "isoformat"):
            out.append(v.isoformat())
        else:
            out.append(v)
    return out


# ---------------------------------------------------------------------------
# Metric SQL templates (placeholders: where, and_filters, rids, C, m, min_n, w_*)
# ---------------------------------------------------------------------------
SQL = {
    "total_restaurants": "SELECT COUNT(*) AS value\nFROM restaurants r\n{where}",
    "mean_rating": "SELECT AVG(r.rating) AS value  -- AVG ignores NULL (unrated)\nFROM restaurants r\n{where}",
    "median_rating": "SELECT MEDIAN(r.rating) AS value\nFROM restaurants r\n{where}",
    "weighted_rating": (
        "-- WR = v/(v+m)*R + m/(v+m)*C with C = {C}, m = {m}\n"
        "SELECT AVG(CASE WHEN r.review_count + {m} = 0 THEN r.rating\n"
        "                ELSE r.review_count / (r.review_count + {m}) * r.rating\n"
        "                   + {m} / (r.review_count + {m}) * {C} END) AS value\n"
        "FROM restaurants r\nWHERE r.rating IS NOT NULL AND r.review_count IS NOT NULL{and_filters}"),
    "mean_cost": "SELECT AVG(r.cost) AS value\nFROM restaurants r\n{where}",
    "median_cost": "SELECT MEDIAN(r.cost) AS value\nFROM restaurants r\n{where}",
    "total_votes": "SELECT SUM(r.review_count) AS value\nFROM restaurants r\n{where}",
    "cuisine_count": "SELECT COUNT(DISTINCT c.cuisine) AS value\nFROM restaurant_cuisines c\nWHERE c.rid IN {rids}",
    "location_count": "SELECT COUNT(DISTINCT r.location) AS value\nFROM restaurants r\n{where}",
    "top_cuisines": (
        "SELECT c.cuisine AS label, COUNT(*) AS value\nFROM restaurant_cuisines c\nWHERE c.rid IN {rids}\n"
        "GROUP BY c.cuisine\nORDER BY value DESC, label ASC\nLIMIT 15"),
    "by_location": (
        "SELECT r.location AS label, COUNT(*) AS value\nFROM restaurants r\nWHERE r.location IS NOT NULL{and_filters}\n"
        "GROUP BY r.location\nORDER BY value DESC, label ASC\nLIMIT 15"),
    "rating_distribution": (
        "SELECT LEAST(FLOOR(ROUND(r.rating * 5, 6)), 24) / 5 AS bin_start, COUNT(*) AS value\n"
        "FROM restaurants r\nWHERE r.rating IS NOT NULL{and_filters}\nGROUP BY bin_start\nORDER BY bin_start"),
    "price_tiers": (
        "SELECT r.price_tier AS label, COUNT(*) AS value\nFROM restaurants r\nWHERE r.price_tier IS NOT NULL{and_filters}\n"
        "GROUP BY r.price_tier\nORDER BY CASE r.price_tier WHEN 'Budget' THEN 1 WHEN 'Mid-range' THEN 2 ELSE 3 END"),
    "wr_by_cuisine": (
        "SELECT c.cuisine, COUNT(*) AS listings, COUNT(r.weighted_rating) AS n_rated,\n"
        "       AVG(r.rating) AS mean_rating, AVG(r.weighted_rating) AS weighted_rating,\n"
        "       COUNT(r.weighted_rating) >= {min_n} AS sufficient_sample\n"
        "FROM restaurant_cuisines c\nJOIN restaurants r ON r.rid = c.rid\n{where}\nGROUP BY c.cuisine\n"
        "ORDER BY sufficient_sample DESC, weighted_rating DESC, c.cuisine"),
    "median_cost_by_location": (
        "SELECT r.location, COUNT(*) AS n_cost, MEDIAN(r.cost) AS median_cost, AVG(r.cost) AS mean_cost,\n"
        "       COUNT(*) >= {min_n} AS sufficient_sample\n"
        "FROM restaurants r\nWHERE r.cost IS NOT NULL{and_filters}\nGROUP BY r.location\n"
        "ORDER BY sufficient_sample DESC, median_cost DESC, r.location"),
    "rating_vs_votes": (
        "-- All eligible points; the chart shows a deterministic pandas sample of at most 2,000\n"
        "SELECT COUNT(*) AS total_points\nFROM restaurants r\n"
        "WHERE r.rating IS NOT NULL AND r.review_count IS NOT NULL{and_filters}"),
    "distribution_profile": "\nUNION ALL\n".join(
        f"SELECT '{col}' AS metric, COUNT(r.{col}) AS n, AVG(r.{col}) AS mean, MEDIAN(r.{col}) AS median,\n"
        f"       STDDEV_SAMP(r.{col}) AS std, SKEWNESS(r.{col}) AS skewness, MIN(r.{col}) AS min, MAX(r.{col}) AS max,\n"
        f"       QUANTILE_CONT(r.{col}, 0.10) AS p10, QUANTILE_CONT(r.{col}, 0.25) AS p25,\n"
        f"       QUANTILE_CONT(r.{col}, 0.75) AS p75, QUANTILE_CONT(r.{col}, 0.90) AS p90,\n"
        f"       QUANTILE_CONT(r.{col}, 0.75) - QUANTILE_CONT(r.{col}, 0.25) AS iqr\n"
        f"FROM restaurants r\n{{where}}" for col in ("rating", "review_count", "cost")),
    "cuisine_popularity": (
        "SELECT c.cuisine, COUNT(*) AS listings, COUNT(r.weighted_rating) AS n_rated,\n"
        "       AVG(r.rating) AS mean_rating, AVG(r.weighted_rating) AS weighted_rating,\n"
        "       MEDIAN(r.review_count) AS median_votes,\n"
        "       100.0 * COUNT(*) / (SELECT COUNT(*) FROM restaurants r {where}) AS share_pct\n"
        "FROM restaurant_cuisines c\nJOIN restaurants r ON r.rid = c.rid\n{where}\nGROUP BY c.cuisine\n"
        "ORDER BY listings DESC, c.cuisine"),
    "location_density": (
        "SELECT r.location, COUNT(*) AS listings, AVG(r.rating) AS mean_rating,\n"
        "       AVG(r.weighted_rating) AS weighted_rating,\n"
        "       100.0 * COUNT(*) / (SELECT COUNT(*) FROM restaurants r {where}) AS share_pct\n"
        "FROM restaurants r\nWHERE r.location IS NOT NULL{and_filters}\nGROUP BY r.location\n"
        "ORDER BY listings DESC, r.location"),
    "price_tier_analysis": (
        "SELECT r.price_tier, COUNT(*) AS listings, MIN(r.cost) AS min_cost, MEDIAN(r.cost) AS median_cost,\n"
        "       MAX(r.cost) AS max_cost, COUNT(r.rating) AS n_rated, AVG(r.rating) AS mean_rating,\n"
        "       MEDIAN(r.rating) AS median_rating, AVG(r.weighted_rating) AS weighted_rating,\n"
        "       MEDIAN(r.review_count) AS median_votes\n"
        "FROM restaurants r\nWHERE r.price_tier IS NOT NULL{and_filters}\nGROUP BY r.price_tier\n"
        "ORDER BY CASE r.price_tier WHEN 'Budget' THEN 1 WHEN 'Mid-range' THEN 2 ELSE 3 END"),
    "saturation": (
        "WITH sel AS (SELECT r.rid, r.location FROM restaurants r WHERE r.location IS NOT NULL{and_filters}),\n"
        "pairs AS (SELECT s.location, c.cuisine, c.rid FROM restaurant_cuisines c JOIN sel s ON s.rid = c.rid),\n"
        "loc AS (SELECT location, COUNT(*) AS location_listings FROM sel GROUP BY location),\n"
        "cui AS (SELECT cuisine, COUNT(DISTINCT rid) AS cuisine_listings FROM pairs GROUP BY cuisine),\n"
        "tot AS (SELECT COUNT(*) AS total FROM sel)\n"
        "SELECT p.location, p.cuisine, COUNT(*) AS listings, loc.location_listings, cui.cuisine_listings,\n"
        "       COUNT(*) / loc.location_listings AS share_in_location,\n"
        "       cui.cuisine_listings / tot.total AS overall_share,\n"
        "       (COUNT(*) / loc.location_listings) / (cui.cuisine_listings / tot.total) AS location_quotient\n"
        "FROM pairs p JOIN loc USING (location) JOIN cui USING (cuisine), tot\n"
        "GROUP BY p.location, p.cuisine, loc.location_listings, cui.cuisine_listings, tot.total\n"
        "ORDER BY p.location, p.cuisine"),
    "market_gaps": (
        "WITH pop AS (\n  SELECT c.cuisine, COUNT(*) AS listings, COUNT(r.weighted_rating) AS n_rated,\n"
        "         AVG(r.weighted_rating) AS weighted_rating\n"
        "  FROM restaurant_cuisines c JOIN restaurants r ON r.rid = c.rid\n  {where}\n  GROUP BY c.cuisine),\n"
        "bench AS (SELECT AVG(r.weighted_rating) AS benchmark FROM restaurants r {where}),\n"
        "med AS (SELECT MEDIAN(listings) AS median_listings FROM pop)\n"
        "SELECT pop.cuisine, pop.listings, pop.n_rated, pop.weighted_rating, bench.benchmark, med.median_listings\n"
        "FROM pop, bench, med\n"
        "WHERE pop.n_rated >= {min_n} AND pop.weighted_rating > bench.benchmark AND pop.listings < med.median_listings\n"
        "ORDER BY pop.weighted_rating DESC, pop.cuisine"),
    "types_by_tier": (
        "SELECT r.price_tier, t.restaurant_type, COUNT(*) AS listings, COUNT(r.weighted_rating) AS n_rated,\n"
        "       AVG(r.weighted_rating) AS weighted_rating\n"
        "FROM restaurant_types t\nJOIN restaurants r ON r.rid = t.rid\n"
        "WHERE r.price_tier IS NOT NULL{and_filters}\nGROUP BY r.price_tier, t.restaurant_type\n"
        "ORDER BY r.price_tier, t.restaurant_type"),
    "opportunity": (
        "WITH pairs AS (\n  SELECT r.location, c.cuisine, COUNT(*) AS listings, COUNT(r.weighted_rating) AS n_rated,\n"
        "         AVG(r.weighted_rating) AS weighted_rating, MEDIAN(r.review_count) AS median_votes\n"
        "  FROM restaurant_cuisines c JOIN restaurants r ON r.rid = c.rid\n"
        "  WHERE r.location IS NOT NULL{and_filters}\n  GROUP BY r.location, c.cuisine),\n"
        "eligible AS (SELECT * FROM pairs WHERE n_rated >= {min_n}),\n"
        "ranked AS (\n  SELECT *, PERCENT_RANK() OVER (ORDER BY weighted_rating) AS wr_pct,\n"
        "            PERCENT_RANK() OVER (ORDER BY median_votes) AS votes_pct,\n"
        "            1 - PERCENT_RANK() OVER (ORDER BY listings) AS low_saturation_pct\n  FROM eligible)\n"
        "SELECT *, 100 * ({w_rating} * wr_pct + {w_engagement} * votes_pct + {w_low_saturation} * low_saturation_pct) AS score\n"
        "FROM ranked\nORDER BY score DESC, location, cuisine"),
    "spearman_pair": (
        "WITH d AS (SELECT r.{x} AS x, r.{y} AS y FROM restaurants r\n"
        "           WHERE r.{x} IS NOT NULL AND r.{y} IS NOT NULL{and_filters}),\n"
        "ranked AS (SELECT RANK() OVER (ORDER BY x) + (COUNT(*) OVER (PARTITION BY x) - 1) / 2.0 AS rx,\n"
        "                  RANK() OVER (ORDER BY y) + (COUNT(*) OVER (PARTITION BY y) - 1) / 2.0 AS ry FROM d)\n"
        "-- Spearman rho = Pearson correlation of average ranks (p-value comes from scipy)\n"
        "SELECT '{x}' AS x, '{y}' AS y, COUNT(*) AS n, CORR(rx, ry) AS rho FROM ranked"),
    "mann_whitney_group": (
        "WITH d AS (SELECT r.rating AS y, r.{g} AS g FROM restaurants r\n"
        "           WHERE r.rating IS NOT NULL AND r.{g} IS NOT NULL{and_filters}),\n"
        "ranked AS (SELECT g, RANK() OVER (ORDER BY y) + (COUNT(*) OVER (PARTITION BY y) - 1) / 2.0 AS rnk FROM d)\n"
        "-- U(yes) = rank sum of the Yes group - n_yes*(n_yes+1)/2 (p-value comes from scipy)\n"
        "SELECT '{g}' AS group_field, COUNT(*) FILTER (WHERE g) AS n_yes, COUNT(*) FILTER (WHERE NOT g) AS n_no,\n"
        "       SUM(rnk) FILTER (WHERE g) - COUNT(*) FILTER (WHERE g) * (COUNT(*) FILTER (WHERE g) + 1) / 2.0 AS u_statistic\n"
        "FROM ranked"),
}


# ---------------------------------------------------------------------------
# Read-only SQL Playground
# ---------------------------------------------------------------------------
FORBIDDEN = ["INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "COPY", "ATTACH", "DETACH", "PRAGMA",
             "INSTALL", "LOAD", "EXPORT", "IMPORT", "CALL", "SET", "RESET", "VACUUM", "CHECKPOINT", "TRUNCATE",
             "GRANT", "REVOKE", "BEGIN", "COMMIT", "ROLLBACK", "USE", "MERGE", "UPSERT"]
FORBIDDEN_FUNCS = ["read_csv", "read_csv_auto", "read_parquet", "parquet_scan", "read_json", "read_json_auto",
                   "read_ndjson", "read_text", "read_blob", "glob", "sniff_csv", "read_xlsx", "query_table",
                   "getenv", "duckdb_secrets"]


def _strip_literals_and_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)
    return sql


def validate_select(sql: str) -> str:
    text = sql.strip()
    if not text:
        raise SqlError("Enter a SELECT statement to run.")
    body = _strip_literals_and_comments(text).strip().rstrip(";").strip()
    if ";" in body:
        raise SqlError("Only one statement can be run at a time. Remove extra semicolons.")
    first = re.match(r"\(?\s*(\w+)", body)
    if not first or first.group(1).upper() not in {"SELECT", "WITH", "FROM"}:
        raise SqlError("Only read-only SELECT queries are allowed (statements must start with SELECT or WITH).")
    upper = body.upper()
    for kw in FORBIDDEN:
        if re.search(rf"\b{kw}\b", upper):
            raise SqlError(f"'{kw}' is not allowed. The SQL Playground is read-only: use SELECT statements only.")
    for fn in FORBIDDEN_FUNCS:
        if re.search(rf"\b{fn}\s*\(", body, flags=re.I):
            raise SqlError(f"'{fn}()' is not allowed. Queries can only read the restaurants tables.")
    return text.rstrip().rstrip(";")


def run_playground(ctx: Context, sql: str, timeout: float = SQL_TIMEOUT_SECONDS, max_rows: int = SQL_MAX_ROWS) -> dict:
    statement = validate_select(sql)
    con = connect(ctx, read_only_sandbox=True)
    result: dict = {}

    def target():
        try:
            cur = con.execute(statement)
            result["columns"] = [d[0] for d in cur.description]
            result["rows"] = [_py_row(r) for r in cur.fetchmany(max_rows + 1)]
        except Exception as exc:  # reported below as a friendly message
            result["error"] = exc

    started = time.perf_counter()
    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        con.interrupt()
        worker.join(2)
        con.close()
        raise SqlError(f"The query took longer than {timeout:g} seconds and was cancelled. Add filters or a LIMIT.")
    con.close()
    if "error" in result:
        raise SqlError(_friendly_duckdb_error(result["error"]))
    rows = result["rows"]
    truncated = len(rows) > max_rows
    return {"columns": result["columns"], "rows": rows[:max_rows], "row_count": min(len(rows), max_rows),
            "truncated": truncated, "max_rows": max_rows,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}


def _friendly_duckdb_error(exc: Exception) -> str:
    msg = str(exc).split("\n")[0]
    msg = re.sub(r"^[A-Za-z ]+Error:\s*", "", msg)
    if "permission" in msg.lower() or "external access" in msg.lower():
        return "This query tried to access files or settings, which is not allowed in the read-only Playground."
    return f"DuckDB could not run the query: {msg[:300]}"


def schema(ctx: Context) -> list[dict]:
    con = connect(ctx)
    out = []
    for table in ("restaurants", "restaurant_cuisines", "restaurant_types"):
        cols = con.execute(f"DESCRIBE {table}").fetchall()
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        out.append({"table": table, "rows": int(count), "columns": [{"name": c[0], "type": c[1]} for c in cols]})
    con.close()
    return out


PREBUILT_QUERIES = [
    {"title": "Top 10 cuisines by listings",
     "sql": "SELECT cuisine, COUNT(*) AS listings\nFROM restaurant_cuisines\nGROUP BY cuisine\nORDER BY listings DESC, cuisine\nLIMIT 10"},
    {"title": "Locations by median rating (n >= 10 rated)",
     "sql": "SELECT location, COUNT(rating) AS rated, ROUND(MEDIAN(rating), 2) AS median_rating\nFROM restaurants\n"
            "WHERE location IS NOT NULL\nGROUP BY location\nHAVING COUNT(rating) >= 10\nORDER BY median_rating DESC, location\nLIMIT 15"},
    {"title": "Price tier summary",
     "sql": "SELECT price_tier, COUNT(*) AS listings, MEDIAN(cost) AS median_cost,\n       ROUND(AVG(rating), 2) AS mean_rating\n"
            "FROM restaurants\nWHERE price_tier IS NOT NULL\nGROUP BY price_tier\nORDER BY median_cost"},
    {"title": "Highest weighted ratings (raw vs weighted)",
     "sql": "SELECT restaurant_name, location, rating, review_count,\n       ROUND(weighted_rating, 3) AS weighted_rating\n"
            "FROM restaurants\nWHERE weighted_rating IS NOT NULL\nORDER BY weighted_rating DESC\nLIMIT 20"},
    {"title": "Online ordering share by restaurant type",
     "sql": "SELECT t.restaurant_type, COUNT(*) AS listings,\n       ROUND(100.0 * AVG(CASE WHEN r.online_order THEN 1 ELSE 0 END), 1) AS online_pct\n"
            "FROM restaurant_types t\nJOIN restaurants r ON r.rid = t.rid\nWHERE r.online_order IS NOT NULL\n"
            "GROUP BY t.restaurant_type\nORDER BY listings DESC"},
]
