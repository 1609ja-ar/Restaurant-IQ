"""Deterministic cleaning pipeline.

Input : the raw upload as text (every column a string, empty cells = NaN) plus the
        user-confirmed mapping/settings.
Output: a cleaned dataframe (one row per de-duplicated listing, invalid rows kept
        but flagged), a transformation log and a data-quality / reconciliation report.

Rules (numbered as in docs/kpi_definitions.md):
 1. Ratings "4.1/5" -> 4.1. "NEW", "-", blank or unparseable -> null + flagged unrated.
    Unrated rows are kept; they are excluded from rating statistics only.
 2. Costs "1,200" -> 1200. Missing stays null. IQR outliers are flagged, never deleted.
 3. Duplicates: normalized name + address; keep the record with the most votes.
 4. Cuisines / types: split on , | ; -> trimmed, title-cased, de-duplicated lists.
 5. Yes/No -> True/False. Unknown or missing stays null (never assumed "No").
 6. Ratings outside the source scale, negative votes and negative costs are invalid:
    the row is kept in the cleaned file with flags but excluded from analysis.
 7. Reconciliation: raw -> blank -> duplicates -> invalid -> rows used (balanced).
 8. Completeness / uniqueness / validity % per column.
 9. Raw data is never modified; every action is logged with row counts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .schemas import CANONICAL_FIELDS

UNRATED_TOKENS = {"new", "-", "--", "", "nan", "n/a", "na", "none", "null", "not rated", "no rating"}
TRUE_TOKENS = {"yes", "y", "true", "t", "1"}
FALSE_TOKENS = {"no", "n", "false", "f", "0"}
LIST_SPLIT = re.compile(r"\s*[,|;]\s*")
NUMBER_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*$")
RATING_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:/\s*(\d+(?:\.\d+)?))?\s*$")
MONEY_RE = re.compile(r"^\s*(-)?\s*(?:[A-Za-z₹$€£¥.]+\s*)?(-)?\s*(\d+(?:\.\d+)?)\s*(?:[A-Za-z/ ]+)?\s*$")

# Internal columns created by the pipeline. Source columns with these names are
# preserved with a "src_" prefix so nothing is overwritten.
INTERNAL_COLUMNS = {"rid", "source_row", "include_in_analysis", "is_unrated", "rating_invalid", "votes_invalid",
                    "cost_invalid", "is_invalid", "cost_outlier", "price_tier", "location", "rating_source",
                    "rating_raw", "review_count_raw", "cost_raw", "weighted_rating", "invalid_reason"}


@dataclass
class CleanSettings:
    mapping: dict[str, str]              # source column -> canonical field
    rating_scale_min: float = 0.0
    rating_scale_max: float | None = 5.0
    currency: str | None = None          # dataset-level currency if no currency column
    price_unit: str = "unknown"


@dataclass
class CleanResult:
    cleaned: pd.DataFrame
    log: list[dict] = field(default_factory=list)
    reconciliation: dict = field(default_factory=dict)
    quality: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Value parsers (pure functions, unit-tested individually)
# ---------------------------------------------------------------------------
def parse_rating(value, scale_max: float | None = None) -> tuple[float, str]:
    """Return (rating_on_source_scale, status) where status is ok | unrated.

    "4.1/5" -> 4.1. If the value carries its own denominator that differs from
    the dataset scale (e.g. "8/10" in a 0-5 dataset) it is rescaled to the dataset scale.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan, "unrated"
    text = str(value).strip()
    if text.lower() in UNRATED_TOKENS:
        return np.nan, "unrated"
    m = RATING_RE.match(text)
    if not m:
        return np.nan, "unrated"
    number = float(m.group(1))
    denom = float(m.group(2)) if m.group(2) else None
    if denom is not None and scale_max and denom > 0 and denom != scale_max:
        number = number * scale_max / denom
    return number, "ok"


def parse_number(value) -> float:
    """Plain numbers, thousands separators allowed. Unparseable -> NaN."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    m = NUMBER_RE.match(str(value).replace(",", ""))
    return float(m.group(1)) if m else np.nan


def parse_money(value) -> float:
    """'1,200' -> 1200, 'Rs. 450' -> 450, '$25' -> 25, '-300' -> -300 (flagged invalid later)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    m = MONEY_RE.match(str(value).replace(",", ""))
    if not m:
        return np.nan
    amount = float(m.group(3))
    return -amount if (m.group(1) or m.group(2)) else amount


def parse_bool(value):
    """Yes/No style -> True/False. Anything else (including missing) -> None."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    t = str(value).strip().lower()
    if t in TRUE_TOKENS:
        return True
    if t in FALSE_TOKENS:
        return False
    return None


def _smart_title(token: str) -> str:
    # Keep short acronyms (BBQ, KFC-style) as written; title-case everything else.
    return " ".join(w if (w.isupper() and len(w) <= 4) else w.capitalize() for w in token.split())


def parse_list(value) -> list[str] | None:
    """'north indian,  Chinese|chinese' -> ['North Indian', 'Chinese']. Empty -> None."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    items = []
    for part in LIST_SPLIT.split(str(value).strip()):
        part = re.sub(r"\s+", " ", part).strip()
        if part:
            t = _smart_title(part)
            if t not in items:
                items.append(t)
    return items or None


def _as_nullable_text(col: pd.Series) -> pd.Series:
    """Object column where every missing value is None (not NaN), so missing is represented
    the same way in memory, in MongoDB and in exports."""
    obj = col.astype(object)
    return obj.where(obj.notna(), None)


def normalize_key(value) -> str | None:
    """Normalization used for duplicate detection: case, whitespace and punctuation-insensitive."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    s = str(value).lower().replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def iqr_bounds(values: pd.Series) -> tuple[float, float] | None:
    v = values.dropna()
    if len(v) < 4:
        return None
    q1, q3 = float(v.quantile(0.25)), float(v.quantile(0.75))
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def clean_dataset(raw: pd.DataFrame, settings: CleanSettings) -> CleanResult:
    log: list[dict] = []
    df = raw.copy()  # the raw frame is never mutated
    raw_rows = len(df)
    df.insert(0, "source_row", np.arange(1, raw_rows + 1))
    log.append({"step": "Load", "detail": f"Read {raw_rows:,} raw rows and {raw.shape[1]} columns as text.",
                "rows": raw_rows})

    # Blank rows (every cell empty) carry no information; counted, never silently dropped.
    # Whitespace-only cells are treated as missing (documented in docs/assumptions_log.md).
    value_cols = [c for c in df.columns if c != "source_row"]
    for c in value_cols:
        if df[c].dtype == object:
            s = df[c]
            is_text = s.map(lambda v: isinstance(v, str))
            df[c] = s.where(~(is_text & s.astype(str).str.strip().eq("")), np.nan)
    blank_mask = df[value_cols].isna().all(axis=1)
    blank_rows = int(blank_mask.sum())
    df = df.loc[~blank_mask].reset_index(drop=True)
    if blank_rows:
        log.append({"step": "Blank rows", "detail": f"Removed {blank_rows:,} rows where every cell is empty.",
                    "rows": blank_rows})

    mapping = {src: dst for src, dst in settings.mapping.items() if dst}
    targets = list(mapping.values())
    dup_targets = {t for t in targets if targets.count(t) > 1}
    if dup_targets:
        raise ValueError(f"Each field can be mapped from only one column. Duplicated: {', '.join(sorted(dup_targets))}.")
    unknown = set(targets) - set(CANONICAL_FIELDS)
    if unknown:
        raise ValueError(f"Unknown canonical field(s): {', '.join(sorted(unknown))}.")
    missing_cols = set(mapping) - set(df.columns)
    if missing_cols:
        raise ValueError(f"Mapped column(s) not found in the file: {', '.join(sorted(missing_cols))}.")

    out = pd.DataFrame({"source_row": df["source_row"].to_numpy()})
    scale_max = settings.rating_scale_max
    scale_min = settings.rating_scale_min
    counts: dict[str, int] = {}

    for src, dst in mapping.items():
        kind = CANONICAL_FIELDS[dst]["kind"]
        col = df[src]
        out[f"__present__{dst}"] = col.notna().to_numpy()  # raw presence, for completeness % (dropped later)
        if kind == "text":
            s = col.astype("string").str.strip()
            out[dst] = s.where(s.notna() & (s != ""), None).astype(object)
        elif kind == "list":
            out[dst] = col.map(parse_list)
            log.append({"step": f"Rule 4 - {CANONICAL_FIELDS[dst]['label']}",
                        "detail": f"Split '{src}' on , | ; and trimmed/title-cased values into lists.",
                        "rows": int(out[dst].notna().sum())})
        elif kind == "rating":
            parsed = col.map(lambda v: parse_rating(v, scale_max))
            out["rating_raw"] = _as_nullable_text(col)
            out["rating_source"] = parsed.map(lambda t: t[0]).astype(float)
            out["is_unrated"] = parsed.map(lambda t: t[1] == "unrated").astype(bool)
            upper = scale_max if scale_max else np.inf
            out["rating_invalid"] = out["rating_source"].notna() & (
                (out["rating_source"] < scale_min) | (out["rating_source"] > upper))
            span = (scale_max - scale_min) if scale_max else None
            if span:
                normalized = (out["rating_source"] - scale_min) / span * 5.0
            else:
                normalized = out["rating_source"]
            out["rating"] = normalized.where(~out["rating_invalid"])
            counts["unrated"] = int(out["is_unrated"].sum())
            counts["rating_invalid"] = int(out["rating_invalid"].sum())
            transform = ("identity (source scale is 0-5)" if (scale_min == 0 and scale_max == 5)
                         else f"rescaled from {scale_min:g}-{scale_max:g} to 0-5" if span else "kept as-is (scale unknown)")
            log.append({"step": "Rule 1 - Ratings", "detail": f"Parsed '{src}'; {counts['unrated']:,} unrated "
                        f"(NEW, '-', blank or unparseable) kept but excluded from rating statistics. Scale: {transform}.",
                        "rows": counts["unrated"]})
        elif kind == "count":
            out["review_count_raw"] = _as_nullable_text(col)
            num = col.map(parse_number).astype(float)
            out["votes_invalid"] = num < 0
            out[dst] = num.where(~out["votes_invalid"])
            counts["votes_invalid"] = int(out["votes_invalid"].sum())
            counts["votes_unparseable"] = int((col.notna() & num.isna()).sum())
        elif kind == "money":
            out["cost_raw"] = _as_nullable_text(col)
            num = col.map(parse_money).astype(float)
            out["cost_invalid"] = num < 0
            out[dst] = num.where(~out["cost_invalid"])
            counts["cost_invalid"] = int(out["cost_invalid"].sum())
            counts["cost_unparseable"] = int((col.notna() & num.isna()).sum())
            log.append({"step": "Rule 2 - Cost", "detail": f"Parsed '{src}' (thousands separators and currency "
                        f"symbols removed). {int(col.isna().sum()):,} missing costs stay null; "
                        f"{counts['cost_unparseable']:,} unparseable values set to null.", "rows": int(num.notna().sum())})
        elif kind == "bool":
            out[dst] = col.map(parse_bool).astype(object)
            unknown_n = int(out[dst].isna().sum())
            log.append({"step": f"Rule 5 - {CANONICAL_FIELDS[dst]['label']}",
                        "detail": f"Mapped Yes/No in '{src}' to true/false; {unknown_n:,} unknown/missing values stay null.",
                        "rows": int(out[dst].notna().sum())})
        elif kind == "float":
            num = col.map(parse_number).astype(float)
            lim = 90 if dst == "latitude" else 180
            out[dst] = num.where(num.abs() <= lim)
        elif kind == "date":
            out[dst] = pd.to_datetime(col, errors="coerce", format="mixed")

    # Ensure flag columns exist even when the field is unmapped.
    for flag in ("is_unrated", "rating_invalid", "votes_invalid", "cost_invalid"):
        if flag not in out:
            out[flag] = False
    if "currency" in out:
        out["currency"] = out["currency"].map(lambda v: v.upper() if isinstance(v, str) else v)
    elif "cost" in out:
        out["currency"] = settings.currency.upper() if settings.currency else None

    reasons = []
    for flag, label in (("rating_invalid", "rating outside scale"), ("votes_invalid", "negative votes"),
                        ("cost_invalid", "negative cost")):
        reasons.append(np.where(out[flag], label, ""))
    out["invalid_reason"] = ["; ".join(r for r in parts if r) or None for parts in zip(*reasons)]
    out["is_invalid"] = out["rating_invalid"] | out["votes_invalid"] | out["cost_invalid"]

    # Location used for grouping: most granular geographic label available.
    loc_source = next((f for f in ("locality", "city", "region", "country") if f in out and out[f].notna().any()), None)
    out["location"] = out[loc_source] if loc_source else None

    # Preserve unmapped columns.
    extras = []
    for col in df.columns:
        if col == "source_row" or col in mapping:
            continue
        name = col if (col not in out.columns and col not in INTERNAL_COLUMNS and col not in CANONICAL_FIELDS) else f"src_{col}"
        out[name] = _as_nullable_text(df[col]).to_numpy()
        extras.append(name)

    # ---- Rule 3: duplicates -------------------------------------------------
    pre_dedup = len(out)
    dedup_rule, out, dup_examples = _deduplicate(out, mapping)
    duplicates_removed = pre_dedup - len(out)
    log.append({"step": "Rule 3 - Duplicates", "detail": f"{dedup_rule}. {pre_dedup:,} rows -> {len(out):,} "
                f"({duplicates_removed:,} duplicates removed).", "rows": duplicates_removed})

    # ---- Rule 6: invalid rows -------------------------------------------------
    out["include_in_analysis"] = ~out["is_invalid"]
    invalid_rows = int(out["is_invalid"].sum())
    log.append({"step": "Rule 6 - Invalid values", "detail": f"{invalid_rows:,} rows have a rating outside the "
                f"scale, negative votes or a negative cost. They stay in the cleaned file (flagged) but are excluded "
                "from all analysis.", "rows": invalid_rows})

    analysis = out[out["include_in_analysis"]]

    # ---- Rule 2b: cost outliers (flag only) and price tiers ------------------
    out["cost_outlier"] = False
    out["price_tier"] = None
    outlier_bounds, tier_cutoffs = {}, {}
    if "cost" in out:
        cur = out["currency"].fillna("UNKNOWN") if "currency" in out else pd.Series("UNKNOWN", index=out.index)
        for currency in sorted(cur[out["include_in_analysis"]].unique()):
            mask = out["include_in_analysis"] & (cur == currency)
            costs = out.loc[mask, "cost"]
            bounds = iqr_bounds(costs)
            if bounds:
                outlier_bounds[currency] = {"lower": bounds[0], "upper": bounds[1]}
                out.loc[mask, "cost_outlier"] = (costs < bounds[0]) | (costs > bounds[1])
            valid = costs.dropna()
            if valid.nunique() >= 3 and len(valid) >= 10:
                q1, q2 = float(valid.quantile(1 / 3)), float(valid.quantile(2 / 3))
                if q1 < q2:
                    tier = np.where(costs <= q1, "Budget", np.where(costs <= q2, "Mid-range", "Premium"))
                    out.loc[mask, "price_tier"] = pd.Series(tier, index=costs.index).where(costs.notna(), None)
                    tier_cutoffs[currency] = {"budget_max": q1, "mid_max": q2}
        out["cost_outlier"] = out["cost_outlier"].astype(bool)
        n_out = int(out["cost_outlier"].sum())
        log.append({"step": "Rule 2 - Cost outliers", "detail": f"Flagged {n_out:,} cost outliers with the 1.5 x IQR "
                    "rule (per currency). Outliers are kept; use 'Exclude cost outliers' to see their impact.",
                    "rows": n_out})
        if tier_cutoffs:
            log.append({"step": "Price tiers", "detail": "Assigned Budget / Mid-range / Premium using the 33rd and "
                        "67th cost percentiles of analysis rows (per currency).",
                        "rows": int(out["price_tier"].notna().sum())})

    out.insert(0, "rid", out["source_row"].astype(int))
    analysis = out[out["include_in_analysis"]]

    # ---- Rule 7: reconciliation ---------------------------------------------
    unrated_used = int(analysis["is_unrated"].sum()) if "rating" in out else None
    rec = {
        "raw_rows": raw_rows,
        "blank_rows_removed": blank_rows,
        "duplicates_removed": duplicates_removed,
        "rows_after_dedup": int(len(out)),
        "invalid_rows_excluded": invalid_rows,
        "invalid_breakdown": {
            "rating_outside_scale": int(out["rating_invalid"].sum()),
            "negative_votes": int(out["votes_invalid"].sum()),
            "negative_cost": int(out["cost_invalid"].sum()),
        },
        "rows_used_in_analysis": len(analysis),
        "unrated_rows_in_analysis": unrated_used,
        "rated_rows_in_analysis": (len(analysis) - unrated_used) if unrated_used is not None else None,
        "cost_outliers_flagged": int(analysis["cost_outlier"].sum()),
        "dedup_rule": dedup_rule,
        "duplicate_examples": dup_examples,
        "balanced": bool(raw_rows - blank_rows - duplicates_removed - invalid_rows == len(analysis)),
    }
    assert rec["balanced"], "Row reconciliation does not balance"  # programming error if hit

    quality = column_quality(out, mapping, extras, counts)
    out = out.drop(columns=[c for c in out.columns if c.startswith("__present__")])
    metadata = {
        "mapping": mapping,
        "extras": extras,
        "location_source": loc_source,
        "rating_scale": {"min": scale_min, "max": scale_max, "normalized_to": "0-5" if scale_max else None},
        "price_unit": settings.price_unit,
        "currencies": sorted(out.loc[out["include_in_analysis"], "currency"].dropna().unique().tolist()) if "currency" in out else [],
        "cost_outlier_bounds": outlier_bounds,
        "price_tier_cutoffs": tier_cutoffs,
        "parse_counts": counts,
    }
    return CleanResult(cleaned=out.reset_index(drop=True), log=log, reconciliation=rec, quality=quality, metadata=metadata)


def _deduplicate(out: pd.DataFrame, mapping: dict) -> tuple[str, pd.DataFrame, list[dict]]:
    """Rule 3. Keep the row with the most votes per key; ties keep the earliest source row."""
    fields = set(mapping.values())
    if "restaurant_name" in fields:
        parts = ["restaurant_name"] + (["address"] if "address" in fields else
                                        [f for f in ("locality", "city") if f in fields])
        rule = "Key = normalized " + " + ".join(p.replace("_", " ") for p in parts) + "; kept the row with the most votes"
        key = out[parts].apply(lambda r: "|".join(normalize_key(v) or "" for v in r), axis=1)
        key = key.where(out["restaurant_name"].notna(), None)  # rows without a name are not de-duplicated
    else:
        value_cols = [c for c in out.columns if c not in {"source_row"} and not c.endswith("_invalid")
                      and not c.startswith("__present__")
                      and c not in {"is_unrated", "is_invalid", "invalid_reason", "rid"}]
        rule = "No restaurant name mapped: removed exact duplicate rows (all values identical)"
        key = out[value_cols].astype(str).agg("|".join, axis=1)

    votes = out["review_count"] if "review_count" in out else pd.Series(np.nan, index=out.index)
    rank_votes = votes.fillna(-1.0)
    order = pd.DataFrame({"key": key, "votes": rank_votes, "row": out["source_row"]})
    order = order.sort_values(["key", "votes", "row"], ascending=[True, False, True], na_position="last")
    has_key = order["key"].notna()
    dup_mask = has_key & order["key"].duplicated(keep="first")
    removed_idx = order.index[dup_mask]
    kept_by_key = order[has_key & ~dup_mask].set_index("key")["row"]
    examples = [{"removed_source_row": int(out.at[i, "source_row"]), "kept_source_row": int(kept_by_key[order.at[i, "key"]])}
                for i in list(removed_idx)[:50]]
    result = out.drop(index=removed_idx).sort_values("source_row").reset_index(drop=True)
    return rule, result, sorted(examples, key=lambda e: e["removed_source_row"])


def column_quality(out: pd.DataFrame, mapping: dict, extras: list[str], counts: dict) -> list[dict]:
    """Rule 8. Computed on the de-duplicated rows (the cleaned dataset)."""
    n = len(out)
    rows = []
    src_for = {dst: src for src, dst in mapping.items()}
    for dst, src in src_for.items():
        present = out[f"__present__{dst}"]
        non_null = int(present.sum())
        values = out[dst]
        if dst == "rating":
            valid = int(out["rating"].notna().sum())
            note = "Valid = numeric and inside the rating scale; unrated values count as not valid."
        elif dst == "review_count":
            valid = int(values.notna().sum())
            note = "Valid = parseable, non-negative number."
        elif dst == "cost":
            valid = int(values.notna().sum())
            note = "Valid = parseable, non-negative amount."
        elif CANONICAL_FIELDS[dst]["kind"] == "bool":
            valid = int(values.notna().sum())
            note = "Valid = recognized Yes/No value."
        else:
            valid = int(values.notna().sum())
            note = "Valid = non-empty after trimming."
        hashable = values.dropna().map(lambda v: tuple(v) if isinstance(v, list) else v)
        rows.append({
            "column": src, "field": dst,
            "completeness_pct": round(100 * non_null / n, 2) if n else None,
            "uniqueness_pct": round(100 * hashable.nunique() / len(hashable), 2) if len(hashable) else None,
            "validity_pct": round(100 * valid / non_null, 2) if non_null else None,
            "non_null": non_null, "valid": valid, "note": note,
        })
    for col in extras:
        s = out[col]
        nn = int(s.notna().sum())
        rows.append({"column": col, "field": None,
                     "completeness_pct": round(100 * nn / n, 2) if n else None,
                     "uniqueness_pct": round(100 * s.dropna().nunique() / nn, 2) if nn else None,
                     "validity_pct": None, "non_null": nn, "valid": None,
                     "note": "Unmapped column, preserved as-is; validity not assessed."})
    return rows
