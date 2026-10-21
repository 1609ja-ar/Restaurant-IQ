"""Report builder: computes a report from the active dataset and renders it to PDF.

``build_report`` returns plain data (also used for the on-screen preview), so the PDF and
the preview always show the same, freshly computed numbers. Nothing here is hard-coded.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import analyst, calculations as calc, insights
from .compare import compare
from .kpis import Context, Filters, apply_filters

NAVY = colors.HexColor("#0B1B3A")
CORAL = colors.HexColor("#FF6B57")
BLUE = colors.HexColor("#2a78d6")
TIERS = [colors.HexColor("#86b6ef"), colors.HexColor("#2a78d6"), colors.HexColor("#104281")]
GRID = colors.HexColor("#E4E7EC")
MUTED = colors.HexColor("#5B6475")

STANDARD_LIMITATIONS = [
    "Snapshot data: listings reflect one point in time and may be out of date.",
    "Ratings are user-generated platform scores (often scraped); they can be biased and are not quality audits.",
    "No revenue, footfall, demand or profit data: nothing here measures commercial performance.",
    "Costs are approximate listed prices (for example 'for two'), not actual spend.",
    "Findings are observational; correlation is not causation.",
]
NEXT_STEPS = [
    "Validate shortlisted segments with field research: footfall counts, rents and competitor visits.",
    "Add time-stamped data (monthly snapshots) to study trends rather than a single snapshot.",
    "Join sales or delivery-order data, if available, to move from ratings to demand.",
    "Re-run the analysis with stricter sample-size thresholds to check that rankings are stable.",
]


def _money(v, cur):
    if v is None:
        return "N/A"
    return f"{cur} {v:,.0f}" if cur else f"{v:,.0f}"


def _kpi_text(card: dict, cur) -> str:
    if not card["available"] or card["value"] is None:
        return "N/A"
    if card["id"] in ("mean_cost", "median_cost"):
        return _money(card["value"], cur)
    if card["unit"] == "/5":
        return f"{card['value']:.2f} / 5"
    return f"{card['value']:,.0f}"


def build_report(ctx: Context, report_type: str, length: str, f: Filters, focus: str | None,
                 compare_kind: str | None, compare_items: list[str]) -> dict:
    df = apply_filters(ctx, f)
    cur = calc.cost_unit(ctx, df)
    cards = calc.kpi_cards(ctx, df)
    kpi = {c["id"]: c for c in cards}
    findings = insights.key_findings(ctx, df)
    rec = ctx.meta.get("reconciliation", {})
    titles = {"market_overview": "Market Overview", "cuisine": "Cuisine Report", "location": "Location Report",
              "comparison": "Comparison Report"}
    report = {
        "title": f"RestaurantIQ {titles[report_type]}" + (f": {focus}" if focus and report_type in ("cuisine", "location") else ""),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "report_type": report_type, "length": length,
        "dataset": {"id": ctx.dataset_id, "name": ctx.meta.get("name"), "version": ctx.meta.get("version"),
                    "is_demo": bool(ctx.meta.get("is_demo")), "source_file": ctx.meta.get("source_filename"),
                    "price_unit": ctx.meta.get("price_unit"), "currency": cur},
        "scope": {"filters": f.describe() or ["Full dataset (no filters)"], "sample_size": int(len(df)),
                  "total_rows": int(len(ctx.frame))},
        "reconciliation": rec,
        "kpis": [{"label": c["label"], "value": _kpi_text(c, cur), "definition": c["definition"] if c["available"] else c["reason"]}
                 for c in cards],
        "findings": findings,
        "charts": {},
        "sections": [],
        "opportunities": [],
        "limitations": list(STANDARD_LIMITATIONS),
        "next_steps": list(NEXT_STEPS),
    }
    if report["dataset"]["is_demo"]:
        report["limitations"].insert(0, "Sample data - illustrative only. These numbers are synthetic and are not real market evidence.")
    for feat, info in ctx.capabilities["features"].items():
        if not info["available"] and feat in ("rating_analysis", "cost_analysis", "cuisine_analysis", "location_analysis", "weighted_rating"):
            report["limitations"].append(f"{feat.replace('_', ' ').capitalize()} not available: the dataset needs {info['requires']}.")
    if ctx.capabilities["fields"]["mixed_currency"] and not f.currency:
        report["limitations"].append("Mixed currencies: cost figures are N/A unless a single currency is selected.")

    # Executive summary built only from computed values.
    summary = [f"{len(df):,} restaurants analyzed ({report['scope']['filters'][0] if len(report['scope']['filters']) == 1 else 'filtered selection'})."]
    if kpi["mean_rating"]["available"]:
        summary.append(f"Mean rating {kpi['mean_rating']['value']:.2f} (median {kpi['median_rating']['value']:.2f}); "
                       f"weighted rating {kpi['weighted_rating']['value']:.2f}." if kpi["weighted_rating"]["available"]
                       else f"Mean rating {kpi['mean_rating']['value']:.2f} (median {kpi['median_rating']['value']:.2f}).")
    if kpi["median_cost"]["available"]:
        summary.append(f"Median cost {_money(kpi['median_cost']['value'], cur)} vs mean {_money(kpi['mean_cost']['value'], cur)}.")
    summary += [f"{x['title']}: {x['detail']}" for x in findings[:3]]
    report["executive_summary"] = summary

    # Chart data (also drawn in the PDF).
    for cid, label in (("top_cuisines", "Top cuisines by listings"), ("by_location", "Listings by location"),
                       ("price_tiers", "Price tier mix")):
        res = calc.safe_run(ctx, cid, df)
        if res["available"] and res["data"]:
            rows = res["data"][:10]
            report["charts"][cid] = {"label": label, "rows": rows,
                                     "summary": ", ".join(f"{r['label']} {r['value']:,}" for r in rows[:5])}
    prof = calc.safe_run(ctx, "distribution_profile", df)

    # Type-specific section.
    if report_type == "cuisine" and focus:
        sub = apply_filters(ctx, Filters(**{**f.to_dict(), "cuisine": [focus]}))
        if sub.empty:
            report["sections"].append({"heading": f"{focus}", "lines": [f"No restaurants list {focus} in this selection."]})
        else:
            from .compare import group_profile
            p = group_profile(sub, ctx)
            share = calc.safe_run(ctx, "location_density", sub)
            lines = [f"{p['listings']:,} listings ({p['n_rated']:,} rated); mean rating {p['mean_rating']:.2f}; weighted rating {p['weighted_rating']:.2f}." if p["mean_rating"] is not None and p["weighted_rating"] is not None else f"{p['listings']:,} listings.",
                     f"Median cost {_money(p['median_cost'], cur)}." if p["median_cost"] is not None else "Cost N/A."]
            if share["available"]:
                lines.append("Most listings in: " + ", ".join(f"{r['location']} ({r['listings']})" for r in share["data"][:5]) + ".")
            from .stats import cuisine_share_by_location
            fewest = cuisine_share_by_location(df, ctx, focus)["rows"][:5]
            if fewest:
                lines.append("Lowest share of listings in: " + ", ".join(f"{r['location']} ({r['share_in_location'] * 100:.1f}%)" for r in fewest) + ".")
            report["sections"].append({"heading": f"Cuisine profile: {focus}", "lines": lines})
    elif report_type == "location" and focus:
        brief = analyst._location_brief(ctx, df, {"location": focus})
        report["sections"].append({"heading": brief["title"], "lines": brief["answer"] if brief["can_answer"] else [brief["reason"]]})
    elif report_type == "comparison" and compare_kind and len(compare_items) >= 2:
        cmp = compare(ctx, compare_kind, compare_items, f)
        rows = [["Metric"] + [e["name"] for e in cmp["entities"]]]
        for m in cmp["metrics"]:
            vals = []
            for e in cmp["entities"]:
                v = e["values"].get(m["key"])
                vals.append("N/A" if v is None else (", ".join(v) if isinstance(v, list) else
                            f"{v:.2f}" if m["format"] == "rating" else _money(v, cur) if m["format"] == "money" else
                            f"{v * 100:.1f}%" if m["format"] == "pct" else ("Yes" if v else "No") if m["format"] == "bool" else
                            f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)))
            rows.append([m["label"]] + vals)
        report["sections"].append({"heading": "Comparison", "lines": cmp["summary"], "table": rows})
    elif report_type in ("cuisine", "location", "comparison"):
        report["sections"].append({"heading": "Focus not set", "lines": ["Choose a cuisine, location or comparison items to add the focused section."]})

    # Opportunities to investigate (exploratory).
    gaps = calc.safe_run(ctx, "market_gaps", df)
    if gaps["available"]:
        for r in gaps["data"]["rows"][:5]:
            report["opportunities"].append(f"{r['cuisine']}: weighted rating {r['weighted_rating']:.2f} with {r['listings']} listings "
                                           f"(n={r['n_rated']}) - above-average rating, below-median listings.")
    opp = calc.safe_run(ctx, "opportunity", df)
    if opp["available"]:
        for r in opp["data"][:5]:
            report["opportunities"].append(f"{r['cuisine']} in {r['location']}: exploratory Opportunity Score {r['score']:.0f}/100 (n={r['n_rated']}).")
    if not report["opportunities"]:
        report["opportunities"].append("No segment met the sample-size and scoring conditions in this selection.")

    if length == "detailed":
        if prof["available"]:
            rows = [["Metric", "n", "Mean", "Median", "IQR", "P10", "P90", "Skew"]]
            for r in prof["data"]:
                fmt = (lambda v: _money(v, cur)) if r["metric"] == "cost" else (lambda v: "N/A" if v is None else f"{v:,.2f}")
                rows.append([r["label"], f"{r['n']:,}", fmt(r["mean"]), fmt(r["median"]), fmt(r["iqr"]), fmt(r["p10"]), fmt(r["p90"]),
                             "N/A" if r["skewness"] is None else f"{r['skewness']:.2f}"])
            report["sections"].append({"heading": "Distribution profile", "lines": ["Median is shown beside mean because votes and cost are usually right-skewed."], "table": rows})
        tiers = calc.safe_run(ctx, "price_tier_analysis", df)
        if tiers["available"]:
            rows = [["Tier", "Listings", "Median cost", "Mean rating", "Weighted rating"]]
            rows += [[r["price_tier"], f"{r['listings']:,}", _money(r["median_cost"], cur),
                      "N/A" if r["mean_rating"] is None else f"{r['mean_rating']:.2f}",
                      "N/A" if r["weighted_rating"] is None else f"{r['weighted_rating']:.2f}"] for r in tiers["data"]]
            report["sections"].append({"heading": "Price tiers", "lines": ["Tiers are dataset-relative cost terciles."], "table": rows})
        tests = []
        sp = calc.safe_run(ctx, "spearman", df)
        if sp["available"]:
            tests += [f"{r['label']}: {r['note']}" for r in sp["data"] if r.get("note")]
        mw = calc.safe_run(ctx, "mann_whitney", df)
        if mw["available"]:
            tests += [f"{r['label']}: {r['note']}" for r in mw["data"] if r.get("note")]
        if tests:
            report["sections"].append({"heading": "Statistical tests", "lines": tests})
    return report


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------
def _bar_chart(rows: list[dict], title: str) -> Drawing:
    rows = list(reversed(rows[:10]))
    h = 26 + 16 * len(rows)
    d = Drawing(170 * mm, h + 10)
    chart = HorizontalBarChart()
    chart.x, chart.y, chart.width, chart.height = 45 * mm, 6, 110 * mm, h - 14
    chart.data = [[r["value"] for r in rows]]
    chart.categoryAxis.categoryNames = [str(r["label"])[:26] for r in rows]
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.barLabels.fontName = "Helvetica"
    chart.categoryAxis.labels.fillColor = MUTED
    chart.categoryAxis.strokeColor = GRID
    chart.valueAxis.valueMin = 0
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labels.fillColor = MUTED
    chart.valueAxis.strokeColor = GRID
    chart.valueAxis.visibleGrid = True
    chart.valueAxis.gridStrokeColor = GRID
    chart.bars[0].fillColor = BLUE
    chart.bars[0].strokeColor = None
    chart.barLabelFormat = "%d"
    chart.barLabels.fontSize = 6.5
    chart.barLabels.nudge = 8
    d.add(chart)
    d.add(String(0, h + 2, title, fontName="Helvetica-Bold", fontSize=9, fillColor=NAVY))
    return d


def _pie(rows: list[dict], title: str) -> Drawing:
    d = Drawing(170 * mm, 68 * mm)
    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = 30, 22, 42 * mm, 42 * mm
    pie.data = [r["value"] for r in rows]
    total = sum(pie.data) or 1
    pie.labels = [f"{r['label']} {100 * r['value'] / total:.0f}%" for r in rows]
    pie.simpleLabels = 0
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1.5
    pie.slices.fontSize = 7
    pie.slices.fontName = "Helvetica"
    for i in range(len(rows)):
        pie.slices[i].fillColor = TIERS[i % 3]
    d.add(pie)
    d.add(String(0, 68 * mm - 10, title, fontName="Helvetica-Bold", fontSize=9, fillColor=NAVY))
    return d


def render_pdf(report: dict) -> bytes:
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=NAVY, fontSize=18, alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=NAVY, fontSize=12, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12.5)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=10, textColor=MUTED)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=10, bulletIndent=0)

    def esc(s) -> str:
        # Built-in PDF fonts have no rupee glyph; spell currency symbols as codes.
        s = str(s).replace("₹", "INR ").replace("€", "EUR ").replace("£", "GBP ")
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def bullets(items):
        return [Paragraph(esc(i), bullet, bulletText="•") for i in items]

    def table(rows, widths=None):
        t = Table([[Paragraph(esc(c), small if r else ParagraphStyle("th", parent=small, textColor=NAVY, fontName="Helvetica-Bold"))
                    for c in row] for r, row in enumerate(rows)], colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY), ("LINEBELOW", (0, 1), (-1, -1), 0.3, GRID),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    ds = report["dataset"]
    story = [Paragraph(esc(report["title"]), h1),
             Paragraph(f"Generated {esc(report['generated_at'])} UTC &middot; Dataset {esc(ds['name'])} ({esc(ds['id'])}, version {ds['version']})"
                       f" &middot; {esc(report['length'].capitalize())} report", small)]
    if ds["is_demo"]:
        story.append(Paragraph("<b>Sample data &mdash; illustrative only.</b> Synthetic numbers, not real market evidence.",
                               ParagraphStyle("warn", parent=body, textColor=colors.HexColor("#A16207"))))
    story.append(Paragraph(f"Scope: {esc('; '.join(report['scope']['filters']))} &middot; {report['scope']['sample_size']:,} of "
                           f"{report['scope']['total_rows']:,} restaurants", small))

    story += [Paragraph("Executive summary", h2)] + bullets(report["executive_summary"])

    rec = report["reconciliation"]
    if rec:
        story.append(Paragraph("Dataset and reconciliation", h2))
        story.append(Paragraph(f"Source file: {esc(ds['source_file'] or 'N/A')}. Cost unit: {esc(ds['price_unit'])}; currency: {esc(ds['currency'] or 'unknown')}.", body))
        story.append(table([["Raw rows", "Blank removed", "Duplicates removed", "Invalid excluded", "Rows used", "Unrated (kept)"],
                            [f"{rec['raw_rows']:,}", f"{rec['blank_rows_removed']:,}", f"{rec['duplicates_removed']:,}",
                             f"{rec['invalid_rows_excluded']:,}", f"{rec['rows_used_in_analysis']:,}",
                             "N/A" if rec.get("unrated_rows_in_analysis") is None else f"{rec['unrated_rows_in_analysis']:,}"]]))

    story.append(Paragraph("Key performance indicators", h2))
    story.append(table([["KPI", "Value", "Definition"]] + [[k["label"], k["value"], k["definition"] or ""] for k in report["kpis"]],
                       widths=[40 * mm, 30 * mm, 100 * mm]))

    if report["findings"]:
        story.append(Paragraph("Findings", h2))
        story += [Paragraph(f"<b>[{esc(x['tag'])}] {esc(x['title'])}.</b> {esc(x['detail'])}", body) for x in report["findings"]]

    if report["charts"]:
        story.append(Paragraph("Chart summaries", h2))
        for cid, ch in report["charts"].items():
            drawing = _pie(ch["rows"], ch["label"]) if cid == "price_tiers" else _bar_chart(ch["rows"], ch["label"])
            story.append(KeepTogether([drawing, Paragraph(esc(ch["summary"]), small), Spacer(1, 6)]))

    for sec in report["sections"]:
        block = [Paragraph(esc(sec["heading"]), h2)] + bullets(sec.get("lines", []))
        if sec.get("table"):
            n = len(sec["table"][0])
            block.append(table(sec["table"], widths=[170 * mm / n] * n))
        story += block

    story += [Paragraph("Opportunities to investigate (exploratory)", h2),
              Paragraph("Suggestions to investigate further, not predictions of success.", small)] + bullets(report["opportunities"])
    story += [Paragraph("Limitations", h2)] + bullets(report["limitations"])
    story += [Paragraph("Next steps", h2)] + bullets(report["next_steps"])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(CORAL)
        canvas.rect(15 * mm, A4[1] - 12 * mm, 20 * mm, 1.2 * mm, stroke=0, fill=1)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 9 * mm, f"RestaurantIQ - {ds['name']} ({ds['id']})")
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=report["title"], author="RestaurantIQ")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()

