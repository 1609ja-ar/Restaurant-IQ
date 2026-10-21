"""Generates validation.ipynb (kept as a script so the notebook source is reviewable in diffs).

Run:  python build_validation_notebook.py
"""
import json
from pathlib import Path

CELLS = [
    ("markdown", """# RestaurantIQ - independent validation

This notebook **independently re-implements** the cleaning rules and core KPIs with plain pandas
(it does not import any RestaurantIQ code), then compares its numbers with the values served by the
running API. Every check prints **PASS** or **FAIL**.

Prerequisites: the backend is running on `http://127.0.0.1:8010` (see README). The notebook loads the
sample dataset through the API if it is not already the active version.

> Sample data is synthetic and illustrative only."""),
    ("code", """import io, json, math, re, urllib.request
import numpy as np
import pandas as pd

API = "http://127.0.0.1:8010/api"
TOL = 1e-9

def get(path):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return r.read()

def post(path):
    req = urllib.request.Request(API + path, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

print(json.loads(get("/health")))"""),
    ("markdown", "## 1. Make sure the sample dataset is the active version and load the RAW CSV"),
    ("code", """active = json.loads(get("/datasets/active"))["active"]
if not active or not active.get("is_demo"):
    active = post("/demo/load")["active"]
DATASET = active["dataset_id"]
raw = pd.read_csv(io.BytesIO(get(f"/datasets/{DATASET}/raw")), dtype=str, keep_default_na=False, na_values=[""])
print(DATASET, raw.shape)
raw.head()"""),
    ("markdown", "## 2. Independent cleaning (written from the documented rules, not copied from the app)"),
    ("code", """df = raw.copy()
df["source_row"] = np.arange(1, len(df) + 1)

def rating(v):
    if not isinstance(v, str):
        return np.nan
    m = re.fullmatch(r"\\s*(-?\\d+(?:\\.\\d+)?)\\s*(?:/\\s*5)?\\s*", v)
    return float(m.group(1)) if m else np.nan          # NEW, '-', blank -> unrated

def number(v):
    if not isinstance(v, str):
        return np.nan
    try:
        return float(v.replace(",", "").strip())
    except ValueError:
        return np.nan

df["r"] = df["rate"].map(rating)
df["v"] = df["votes"].map(number)
df["c"] = df["approx_cost(for two people)"].map(number)
df["invalid"] = ((df["r"] < 0) | (df["r"] > 5)) | (df["v"] < 0) | (df["c"] < 0)

# Duplicates: normalized name + address, keep most votes (invalid/negative votes rank last), ties -> earliest row
norm = lambda s: re.sub(r"\\s+", " ", re.sub(r"[^\\w\\s]", " ", str(s).lower().replace("&", " and "))).strip()
df["key"] = df["name"].map(norm) + "|" + df["address"].map(norm)
df["vote_rank"] = df["v"].where(df["v"] >= 0, -1).fillna(-1)
df = df.sort_values(["key", "vote_rank", "source_row"], ascending=[True, False, True])
dups = df["key"].duplicated(keep="first")
deduped = df[~dups].sort_values("source_row")
used = deduped[~deduped["invalid"]].copy()
print("raw", len(raw), "duplicates", int(dups.sum()), "invalid", int(deduped["invalid"].sum()), "used", len(used))"""),
    ("markdown", "## 3. Independent KPIs"),
    ("code", """rated = used["r"].dropna()
C = rated.mean()
m = used.loc[used["r"].notna() & (used["v"] > 0), "v"].median()
both = used[used["r"].notna() & used["v"].notna()]
wr = (both["v"] / (both["v"] + m)) * both["r"] + (m / (both["v"] + m)) * C
cuisines = used["cuisines"].dropna().str.split(r"\\s*,\\s*").explode().str.strip().str.title()
mine = {
    "total_restaurants": len(used),
    "mean_rating": rated.mean(),
    "median_rating": rated.median(),
    "weighted_rating": wr.mean(),
    "mean_cost": used["c"].mean(),
    "median_cost": used["c"].median(),
    "total_votes": used["v"].sum(),
    "cuisine_count": cuisines.nunique(),
    "location_count": used["location"].nunique(),
}
mine"""),
    ("markdown", "## 4. Compare with the API (PASS / FAIL)"),
    ("code", """dash = json.loads(get(f"/dashboard?dataset_id={DATASET}"))
api_kpis = {k["id"]: k["value"] for k in dash["kpis"]}
rec = json.loads(get(f"/datasets/{DATASET}"))["reconciliation"]
results = []

def check(name, ours, theirs, tol=TOL):
    ok = (ours is None and theirs is None) or (theirs is not None and math.isclose(float(ours), float(theirs), rel_tol=tol, abs_tol=tol))
    results.append({"check": name, "notebook": ours, "api": theirs, "result": "PASS" if ok else "FAIL"})

check("raw rows", len(raw), rec["raw_rows"])
check("duplicates removed", int(dups.sum()), rec["duplicates_removed"])
check("invalid rows", int(deduped["invalid"].sum()), rec["invalid_rows_excluded"])
check("rows used", len(used), rec["rows_used_in_analysis"])
check("unrated rows (kept)", int(used["r"].isna().sum()), rec["unrated_rows_in_analysis"])
for k, v in mine.items():
    check(k, v, api_kpis[k])

# Top cuisines chart
api_top = {r["label"]: r["value"] for r in dash["charts"]["top_cuisines"]["data"]}
ours_top = cuisines.value_counts()
for label, value in list(api_top.items())[:5]:
    check(f"cuisine count: {label}", int(ours_top.get(label, 0)), value)

report = pd.DataFrame(results)
print(report["result"].value_counts().to_dict())
report"""),
    ("code", """assert (report["result"] == "PASS").all(), report[report["result"] == "FAIL"]
print("ALL CHECKS PASS")"""),
]


def build() -> dict:
    cells = []
    for kind, src in CELLS:
        cell = {"cell_type": kind, "metadata": {}, "source": src.splitlines(keepends=True)}
        if kind == "code":
            cell.update({"execution_count": None, "outputs": []})
        cells.append(cell)
    return {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                         "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}


if __name__ == "__main__":
    out = Path(__file__).with_name("validation.ipynb")
    out.write_text(json.dumps(build(), indent=1), encoding="utf-8")
    print(f"wrote {out}")
