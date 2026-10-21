"""Key Findings: short, evidence-backed statements built only from computed results.

Every finding carries a tag:
  Descriptive  - what the listings show (counts, shares, central tendency)
  Statistical  - the result of a formal test, with n and p-value
  Suggestion   - something worth investigating; never a prediction or causal claim
"""
from __future__ import annotations

import pandas as pd

from . import calculations as calc
from .kpis import Context


def _fmt_money(value: float, currency: str | None) -> str:
    symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(currency or "", "")
    return f"{symbol}{value:,.0f}" if symbol else (f"{value:,.0f} {currency}" if currency else f"{value:,.0f}")


def key_findings(ctx: Context, df: pd.DataFrame) -> list[dict]:
    out: list[dict] = []
    n = len(df)
    if n == 0:
        return out

    top = calc.safe_run(ctx, "top_cuisines", df)
    if top["available"] and top["data"]:
        t = top["data"][0]
        out.append({"tag": "Descriptive", "title": f"{t['label']} is the most listed cuisine",
                    "detail": f"{t['value']:,} of {n:,} restaurants ({100 * t['value'] / n:.1f}%) list {t['label']}.",
                    "source": "top_cuisines"})

    loc = calc.safe_run(ctx, "by_location", df)
    if loc["available"] and loc["data"] and len(loc["data"]) > 1:
        l0 = loc["data"][0]
        out.append({"tag": "Descriptive", "title": f"{l0['label']} has the highest listing density",
                    "detail": f"{l0['value']:,} listings ({100 * l0['value'] / n:.1f}% of the selection). "
                              "Listing density reflects supply of listings, not demand.",
                    "source": "by_location"})

    mean_c, med_c = calc.safe_run(ctx, "mean_cost", df), calc.safe_run(ctx, "median_cost", df)
    if mean_c["available"] and med_c["available"] and med_c["data"]:
        cur = calc.cost_unit(ctx, df)
        gap = mean_c["data"] / med_c["data"] - 1
        if abs(gap) >= 0.05:
            out.append({"tag": "Descriptive", "title": "Costs are skewed",
                        "detail": f"Mean cost {_fmt_money(mean_c['data'], cur)} is {abs(gap) * 100:.0f}% "
                                  f"{'above' if gap > 0 else 'below'} the median {_fmt_money(med_c['data'], cur)}; "
                                  "the median is the better 'typical' value.",
                        "source": "median_cost"})

    sp = calc.safe_run(ctx, "spearman", df)
    if sp["available"]:
        for row in sp["data"]:
            if row["x"] == "rating" and row["y"] == "review_count" and row["rho"] is not None:
                out.append({"tag": "Statistical", "title": "Rating vs votes (Spearman)",
                            "detail": row["note"], "source": "spearman"})

    mw = calc.safe_run(ctx, "mann_whitney", df)
    if mw["available"]:
        for row in mw["data"]:
            if row["p_value"] is not None:
                out.append({"tag": "Statistical", "title": row["label"],
                            "detail": f"Median {row['median_yes']:.2f} (Yes, n={row['n_yes']:,}) vs "
                                      f"{row['median_no']:.2f} (No, n={row['n_no']:,}). {row['note']}",
                            "source": "mann_whitney"})

    gaps = calc.safe_run(ctx, "market_gaps", df)
    if gaps["available"] and gaps["data"]["rows"]:
        names = [r["cuisine"] for r in gaps["data"]["rows"][:3]]
        out.append({"tag": "Suggestion", "title": "Cuisines worth investigating",
                    "detail": f"{', '.join(names)}: weighted rating above the selection average "
                              f"({gaps['data']['benchmark_weighted_rating']:.2f}) with fewer listings than the median "
                              "cuisine. Validate demand with other evidence before acting.",
                    "source": "market_gaps"})

    opp = calc.safe_run(ctx, "opportunity", df)
    if opp["available"] and opp["data"]:
        o = opp["data"][0]
        out.append({"tag": "Suggestion", "title": "Highest exploratory Opportunity Score",
                    "detail": f"{o['cuisine']} in {o['location']} scores {o['score']:.0f}/100 "
                              f"(n={o['n_rated']} rated listings). Exploratory indicator, not a prediction of success.",
                    "source": "opportunity"})
    return out
