"""One or more tests per cleaning rule, using tiny hand-checkable inputs."""
import math

import numpy as np
import pandas as pd
import pytest

from app.cleaning import (CleanSettings, clean_dataset, iqr_bounds, normalize_key, parse_bool, parse_list,
                          parse_money, parse_number, parse_rating)
from app.demo_data import DEMO_MAPPING, generate_demo_dataframe

from .conftest import TINY_MAPPING, tiny_raw


# ---- Rule 1: ratings ---------------------------------------------------------
@pytest.mark.parametrize("value,expected", [("4.1/5", 4.1), (" 3.8 ", 3.8), ("4", 4.0), ("0/5", 0.0)])
def test_rule1_rating_parsed(value, expected):
    number, status = parse_rating(value, 5)
    assert status == "ok" and number == pytest.approx(expected)


@pytest.mark.parametrize("value", ["NEW", "-", "", None, np.nan, "not rated", "abc", "4.1 stars?"])
def test_rule1_unrated_tokens_become_null(value):
    number, status = parse_rating(value, 5)
    assert status == "unrated" and math.isnan(number)


def test_rule1_own_denominator_is_rescaled():
    assert parse_rating("8/10", 5)[0] == pytest.approx(4.0)


def test_rule1_unrated_rows_kept_but_excluded_from_rating_stats():
    _, res = None, clean_dataset(tiny_raw(), CleanSettings(mapping=TINY_MAPPING))
    c = res.cleaned
    row_c = c[c["restaurant_name"] == "C"].iloc[0]
    assert bool(row_c["is_unrated"]) and pd.isna(row_c["rating"]) and bool(row_c["include_in_analysis"])


# ---- Rule 2: costs and outliers ------------------------------------------------
@pytest.mark.parametrize("value,expected", [("1,200", 1200), ("Rs. 450", 450), ("₹800", 800), ("$25", 25),
                                            ("-300", -300), ("2,000 for two", 2000)])
def test_rule2_money_parsing(value, expected):
    assert parse_money(value) == expected


@pytest.mark.parametrize("value", [None, np.nan, "abc", "300-500"])
def test_rule2_missing_or_unparseable_cost_is_null_not_zero(value):
    assert math.isnan(parse_money(value))


def test_rule2_iqr_bounds_hand_calculated():
    # q1 = 225, q3 = 475, IQR = 250 -> bounds (-150, 850)
    lo, hi = iqr_bounds(pd.Series([100, 200, 300, 400, 500, 10000]))
    assert (lo, hi) == (pytest.approx(-150), pytest.approx(850))


def test_rule2_outliers_flagged_not_deleted():
    raw = pd.DataFrame({"name": [f"R{i}" for i in range(6)], "cost": ["100", "200", "300", "400", "500", "10,000"],
                        "rate": ["4/5"] * 6})
    res = clean_dataset(raw, CleanSettings(mapping={"name": "restaurant_name", "cost": "cost", "rate": "rating"}))
    assert len(res.cleaned) == 6
    assert res.cleaned["cost_outlier"].tolist() == [False] * 5 + [True]


# ---- Rule 3: duplicates ----------------------------------------------------------
def test_rule3_normalize_key():
    assert normalize_key("  Spice  Kitchen & Co. ") == "spice kitchen and co"


def test_rule3_dedup_keeps_most_votes():
    res = clean_dataset(tiny_raw(), CleanSettings(mapping=TINY_MAPPING))
    c = res.cleaned
    assert res.reconciliation["duplicates_removed"] == 1
    kept = c[c["address"].str.lower().str.startswith("1 x st")]
    assert len(kept) == 1 and kept.iloc[0]["review_count"] == 100 and kept.iloc[0]["source_row"] == 4
    assert res.reconciliation["duplicate_examples"] == [{"removed_source_row": 1, "kept_source_row": 4}]


def test_rule3_tie_keeps_earliest_row():
    raw = pd.DataFrame({"name": ["X", "x"], "address": ["1 Road", "1 road"], "votes": ["5", "5"], "rate": ["4/5", "3/5"]})
    res = clean_dataset(raw, CleanSettings(mapping={"name": "restaurant_name", "address": "address",
                                                    "votes": "review_count", "rate": "rating"}))
    assert res.cleaned["source_row"].tolist() == [1]


def test_rule3_without_name_only_exact_duplicates_removed():
    raw = pd.DataFrame({"cuisine": ["Thai", "Thai", "Thai"], "rate": ["4/5", "4/5", "3/5"]})
    res = clean_dataset(raw, CleanSettings(mapping={"cuisine": "cuisines", "rate": "rating"}))
    assert res.reconciliation["duplicates_removed"] == 1


# ---- Rule 4: lists ----------------------------------------------------------------
def test_rule4_list_split_trim_title_dedupe():
    assert parse_list("north indian,  Chinese|chinese; ") == ["North Indian", "Chinese"]
    assert parse_list("BBQ, cafe") == ["BBQ", "Cafe"]
    assert parse_list(None) is None and parse_list("  ") is None


# ---- Rule 5: booleans --------------------------------------------------------------
@pytest.mark.parametrize("value,expected", [("Yes", True), ("no", False), ("TRUE", True), ("0", False),
                                            ("maybe", None), ("", None), (None, None)])
def test_rule5_bool(value, expected):
    assert parse_bool(value) is expected


def test_rule5_missing_is_not_assumed_no():
    res = clean_dataset(tiny_raw(), CleanSettings(mapping=TINY_MAPPING))
    d = res.cleaned.set_index("restaurant_name")
    assert d.loc["D", "online_order"] is None
    assert d.loc["C", "online_order"] is True


# ---- Rule 6: invalid values -----------------------------------------------------------
def test_rule6_invalid_values_flagged_and_excluded():
    raw = pd.DataFrame({"name": ["A", "B", "C", "D"], "rate": ["6.2/5", "-1/5", "4/5", "4/5"],
                        "votes": ["3", "4", "-12", "5"], "cost": ["100", "200", "300", "-300"]})
    res = clean_dataset(raw, CleanSettings(mapping={"name": "restaurant_name", "rate": "rating",
                                                    "votes": "review_count", "cost": "cost"}))
    c = res.cleaned
    assert c["is_invalid"].tolist() == [True, True, True, True]
    assert res.reconciliation["invalid_breakdown"] == {"rating_outside_scale": 2, "negative_votes": 1, "negative_cost": 1}
    assert res.reconciliation["rows_used_in_analysis"] == 0
    assert c["invalid_reason"].tolist() == ["rating outside scale", "rating outside scale", "negative votes", "negative cost"]


def test_rule6_scale_aware_validity():
    raw = pd.DataFrame({"name": ["A", "B"], "rate": ["8.5", "11"]})
    res = clean_dataset(raw, CleanSettings(mapping={"name": "restaurant_name", "rate": "rating"}, rating_scale_max=10))
    c = res.cleaned
    assert c["rating"].iloc[0] == pytest.approx(4.25)      # 8.5/10 normalized to 0-5
    assert bool(c["rating_invalid"].iloc[1])


# ---- Rule 7: reconciliation ------------------------------------------------------------
def test_rule7_reconciliation_tiny_balances():
    rec = clean_dataset(tiny_raw(), CleanSettings(mapping=TINY_MAPPING)).reconciliation
    assert (rec["raw_rows"], rec["duplicates_removed"], rec["rows_after_dedup"], rec["invalid_rows_excluded"],
            rec["rows_used_in_analysis"], rec["unrated_rows_in_analysis"], rec["rated_rows_in_analysis"]) == (6, 1, 5, 1, 4, 1, 3)
    assert rec["balanced"]


def test_rule7_blank_rows_counted_not_silently_dropped():
    raw = pd.DataFrame({"name": ["A", None, "B"], "rate": ["4/5", "  ", "3/5"]})
    rec = clean_dataset(raw, CleanSettings(mapping={"name": "restaurant_name", "rate": "rating"})).reconciliation
    assert rec["blank_rows_removed"] == 1 and rec["rows_used_in_analysis"] == 2


def test_rule7_demo_reconciliation():
    rec = clean_dataset(generate_demo_dataframe(), CleanSettings(mapping=DEMO_MAPPING, currency="INR")).reconciliation
    assert rec["raw_rows"] == 804 and rec["duplicates_removed"] == 24 and rec["invalid_rows_excluded"] == 6
    assert rec["raw_rows"] - rec["blank_rows_removed"] - rec["duplicates_removed"] - rec["invalid_rows_excluded"] \
        == rec["rows_used_in_analysis"]


# ---- Rule 8: quality metrics --------------------------------------------------------------
def test_rule8_column_quality_hand_calculated():
    res = clean_dataset(tiny_raw(), CleanSettings(mapping=TINY_MAPPING))
    q = {r["field"]: r for r in res.quality}
    # 5 de-duplicated rows; cost present for 4 of them (C is missing) -> 80% complete
    assert q["cost"]["completeness_pct"] == 80.0
    # ratings present for all 5; valid (numeric, in scale) for 3 (C is NEW, E is 6/5) -> 60%
    assert q["rating"]["completeness_pct"] == 100.0 and q["rating"]["validity_pct"] == 60.0
    # online: values Yes/No/yes/No/maybe/None after dedup -> B No, C yes, a No, D maybe, E None
    assert q["online_order"]["completeness_pct"] == 80.0 and q["online_order"]["validity_pct"] == 75.0


# ---- Rule 9: raw preserved, deterministic, extras kept ---------------------------------------
def test_rule9_raw_not_mutated_and_deterministic():
    raw = tiny_raw()
    before = raw.copy()
    a = clean_dataset(raw, CleanSettings(mapping=TINY_MAPPING))
    b = clean_dataset(raw, CleanSettings(mapping=TINY_MAPPING))
    pd.testing.assert_frame_equal(raw, before)
    pd.testing.assert_frame_equal(a.cleaned, b.cleaned)
    assert a.reconciliation == b.reconciliation


def test_unmapped_columns_preserved_and_collisions_prefixed():
    raw = tiny_raw().assign(phone=["1"] * 6, location=["x"] * 6)
    res = clean_dataset(raw, CleanSettings(mapping=TINY_MAPPING))
    assert "phone" in res.cleaned and "src_location" in res.cleaned
    assert set(res.metadata["extras"]) == {"phone", "src_location"}


def test_duplicate_mapping_rejected():
    with pytest.raises(ValueError):
        clean_dataset(tiny_raw(), CleanSettings(mapping={"name": "restaurant_name", "address": "restaurant_name"}))


def test_parse_number():
    assert parse_number("1,234") == 1234 and math.isnan(parse_number("x"))
