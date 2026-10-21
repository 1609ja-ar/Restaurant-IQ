"""Pandas vs DuckDB agreement for every registered calculation, and Playground safety."""
import pandas as pd
import pytest

from app import calculations as calc
from app import sql_queries
from app.demo_data import DEMO_MAPPING, generate_demo_dataframe
from app.kpis import Filters

from .conftest import TINY_MAPPING, make_ctx, tiny_raw

FILTER_CASES = [
    Filters(),
    Filters(location=["Indiranagar", "HSR", "BTM"]),
    Filters(cuisine=["Chinese"], online_order=True),
    Filters(restaurant_type=["Cafe", "Quick Bites"], price_tier=["Budget"], rating_min=3.5, rating_max=4.5),
    Filters(table_booking=False, search="spice", exclude_outliers=True),
    Filters(search="o'brien_%"),            # escaping of quote, underscore, percent
    Filters(location=["Nowhere"]),          # zero rows
]


@pytest.fixture(scope="module")
def demo_ctx():
    return make_ctx(generate_demo_dataframe(), DEMO_MAPPING, currency="INR", price_unit="for_two")[0]


@pytest.mark.parametrize("f", FILTER_CASES, ids=[f"filters{i}" for i in range(len(FILTER_CASES))])
@pytest.mark.parametrize("calc_id", list(calc.CALCS))
def test_pandas_matches_duckdb(demo_ctx, calc_id, f):
    detail = calc.show_calculation(demo_ctx, calc_id, f)
    if detail["available"]:
        assert detail["match"], detail["mismatches"]
    else:
        assert detail["reason"]


def test_opportunity_custom_weights_match(demo_ctx):
    d = calc.show_calculation(demo_ctx, "opportunity", Filters(),
                              weights={"rating": 0.6, "engagement": 0.2, "low_saturation": 0.2})
    assert d["match"], d["mismatches"]
    assert "0.6 * wr_pct" in d["sql"]


def test_tiny_dataset_sql_agrees(tmp_path):
    ctx = make_ctx(tiny_raw(), TINY_MAPPING)[0]
    for cid in calc.CALCS:
        d = calc.show_calculation(ctx, cid, Filters())
        assert d["match"] in (True, None), (cid, d["mismatches"])


def test_show_calculation_returns_real_source(demo_ctx):
    d = calc.show_calculation(demo_ctx, "median_cost", Filters(location=["HSR"]))
    assert "def kpi_median_cost" in d["pandas_code"]
    assert "r.location IN ('HSR')" in d["sql"] and d["filters"] == ["Location: HSR"]


# ---- Playground ----------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "DELETE FROM restaurants", "DROP TABLE restaurants", "INSERT INTO restaurants VALUES (1)",
    "SELECT 1; DROP TABLE restaurants", "COPY restaurants TO 'x.csv'", "ATTACH 'x.db'", "PRAGMA version",
    "SELECT * FROM read_csv('C:/secret.csv')", "UPDATE restaurants SET rating = 5", "SET threads = 1",
    "CREATE TABLE t AS SELECT 1", "", "EXPLAIN SELECT 1", "SELECT * FROM glob('*')",
])
def test_playground_rejects_non_select(demo_ctx, sql):
    with pytest.raises(sql_queries.SqlError):
        sql_queries.run_playground(demo_ctx, sql)


def test_playground_allows_keywords_inside_strings(demo_ctx):
    res = sql_queries.run_playground(demo_ctx, "SELECT 'drop table; delete' AS note -- update")
    assert res["rows"] == [["drop table; delete"]]


def test_playground_row_cap_and_truncation_flag(demo_ctx):
    res = sql_queries.run_playground(demo_ctx, "SELECT * FROM range(5000)")
    assert res["row_count"] == 1000 and res["truncated"] is True


def test_playground_timeout(demo_ctx):
    with pytest.raises(sql_queries.SqlError, match="longer than"):
        sql_queries.run_playground(demo_ctx, "SELECT COUNT(*) FROM range(200000) a, range(200000) b WHERE a.range * b.range % 7 = 3",
                                   timeout=0.5)


def test_playground_no_file_access_even_via_functions(demo_ctx):
    # read_text is blocked by the validator; external access is also disabled inside DuckDB.
    con = sql_queries.connect(demo_ctx, read_only_sandbox=True)
    with pytest.raises(Exception):
        con.execute("SELECT * FROM read_csv_auto('pytest.ini')").fetchall()
    with pytest.raises(Exception):
        con.execute("SET enable_external_access = true")
    con.close()


def test_prebuilt_queries_run(demo_ctx):
    for q in sql_queries.PREBUILT_QUERIES:
        res = sql_queries.run_playground(demo_ctx, q["sql"])
        assert res["row_count"] > 0, q["title"]


def test_nan_becomes_sql_null(demo_ctx):
    con = sql_queries.connect(demo_ctx)
    nulls = con.execute("SELECT COUNT(*) FROM restaurants WHERE rating IS NULL").fetchone()[0]
    assert nulls == int(demo_ctx.frame["rating"].isna().sum()) > 0
    con.close()
