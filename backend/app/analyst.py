"""AI Analyst: question -> intent -> deterministic pandas analysis -> JSON -> explanation.

The numbers always come from the registered calculation functions. A language model (Groq by
default, see services/llm_client.py) is used only to *explain* that JSON, and only when its API key is set.
Without a key the app runs in clearly labeled Demo Mode with templated explanations.
"""
from __future__ import annotations

import json
import logging
import re

from . import calculations as calc
from . import stats
from .kpis import Context, Filters, apply_filters
from .services import llm_client

log = logging.getLogger("restaurantiq.analyst")


SUGGESTED = [
    {"id": "cuisine_gaps", "question": "Which cuisines have above-average weighted ratings with below-average listing counts?"},
    {"id": "location_density", "question": "Which neighborhoods have the highest listing density, and which have fewer listings for a selected cuisine?"},
    {"id": "cost_rating_tiers", "question": "How do cost and rating vary across price tiers and neighborhoods?"},
    {"id": "online_booking", "question": "Do restaurants with online ordering or table booking have different rating distributions?"},
    {"id": "types_by_tier", "question": "Which restaurant types have the highest weighted rating within each price tier?"},
    {"id": "location_brief", "question": "What should an entrepreneur investigate before opening in a chosen neighborhood?"},
]

KEYWORDS = {
    "cuisine_gaps": {"above-average": 3, "above average": 3, "below-average": 2, "below average": 2, "underserved": 3,
                     "gap": 2, "gaps": 2, "niche": 2, "under-represented": 2, "cuisines have": 2, "weighted rating": 1},
    "location_density": {"density": 3, "most listings": 3, "highest listing": 3, "neighborhood": 1, "neighbourhood": 1,
                         "fewer listings": 2, "saturat": 2, "crowded": 2, "competition": 1, "where are": 1},
    "cost_rating_tiers": {"cost": 2, "price": 2, "tier": 2, "expensive": 2, "cheap": 2, "afford": 2, "budget": 1, "premium": 1},
    "online_booking": {"online": 3, "delivery": 3, "table booking": 3, "booking": 2, "reservation": 3, "book a table": 3},
    "types_by_tier": {"restaurant type": 3, "types": 2, "format": 2, "within each price tier": 3, "fine dining": 1,
                      "quick bites": 1, "cafe": 1},
    "location_brief": {"open": 2, "opening": 3, "entrepreneur": 3, "start a restaurant": 3, "launch": 2,
                       "investigate before": 3, "new restaurant": 2, "should i": 1},
    "overview": {"overview": 3, "summary": 3, "summarize": 3, "how many": 2, "average rating": 2, "dataset": 1},
    "top_rated": {"best": 2, "top rated": 3, "top-rated": 3, "highest rated": 3, "highest-rated": 3, "best rated": 3,
                  "best rating": 3, "worst": 2, "lowest rated": 3, "lowest-rated": 3, "rank": 2, "top cuisine": 2},
}

LOCATION_WORDS = ("location", "neighborhood", "neighbourhood", "area", "where")


def detect_intent(question: str) -> tuple[str | None, dict]:
    q = question.lower()
    scores = {intent: sum(w for kw, w in kws.items() if kw in q) for intent, kws in KEYWORDS.items()}
    best = max(scores.items(), key=lambda kv: kv[1])
    return (best[0] if best[1] > 0 else None), scores


def find_entities(ctx: Context, question: str) -> dict:
    """Locations / cuisines mentioned in the question (longest names matched first)."""
    q = f" {question.lower()} "
    out = {}
    for key, values in (("location", ctx.frame["location"].dropna().unique()), ("cuisine", ctx.cuisines["cuisine"].unique())):
        names = sorted((str(v) for v in values), key=len, reverse=True)
        for name in names:
            if re.search(rf"(?<![\w]){re.escape(name.lower())}(?![\w])", q):
                out[key] = name
                break
    return out


# ---------------------------------------------------------------------------
# Deterministic analysis handlers
# ---------------------------------------------------------------------------
def _unavailable(title: str, reason: str) -> dict:
    return {"title": title, "can_answer": False, "reason": reason, "data": None, "answer": [], "sources": []}


def _cuisine_gaps(ctx, df, ent):
    title = "Under-listed cuisines with strong weighted ratings"
    gaps = calc.safe_run(ctx, "market_gaps", df)
    if not gaps["available"]:
        return _unavailable(title, gaps["reason"])
    g = gaps["data"]
    rows = [{k: r[k] for k in ("cuisine", "weighted_rating", "listings", "n_rated")} for r in g["rows"]]
    answer = []
    if rows:
        answer.append(f"{len(rows)} cuisine(s) have a weighted rating above the dataset average "
                      f"({g['benchmark_weighted_rating']:.2f}) and fewer listings than the median cuisine "
                      f"({g['median_listings']:.0f}): " + "; ".join(
                          f"{r['cuisine']} (WR {r['weighted_rating']:.2f}, {r['listings']} listings, n={r['n_rated']})" for r in rows[:5]) + ".")
    else:
        answer.append("No cuisine meets all three conditions (above-average weighted rating, below-median listings, "
                      f"at least {ctx.settings['min_group_n']} rated restaurants).")
    answer.append("These are segments to investigate, not proof of unmet demand: few listings can also mean little demand.")
    return {"title": title, "can_answer": True, "reason": None, "tag": "Suggestion",
            "data": {"benchmark_weighted_rating": g["benchmark_weighted_rating"], "median_listings": g["median_listings"],
                     "cuisines": rows}, "answer": answer, "sources": ["market_gaps"]}


def _location_density(ctx, df, ent):
    title = "Listing density by location"
    dens = calc.safe_run(ctx, "location_density", df)
    if not dens["available"]:
        return _unavailable(title, dens["reason"])
    top = [{k: r[k] for k in ("location", "listings", "share_pct")} for r in dens["data"][:5]]
    answer = ["Highest listing density: " + "; ".join(f"{r['location']} ({r['listings']} listings, {r['share_pct']:.1f}%)" for r in top) + "."]
    data = {"top_locations": top}
    sources = ["location_density"]
    if ent.get("cuisine") and ctx.capabilities["fields"]["cuisine"]:
        fc = stats.cuisine_share_by_location(df, ctx, ent["cuisine"])
        fewest = [{k: r[k] for k in ("location", "listings", "location_listings", "share_in_location")} for r in fc["rows"][:5]]
        data["fewest_for_cuisine"] = {"cuisine": ent["cuisine"], "rows": fewest}
        if fewest:
            answer.append(f"Locations with the lowest share of {ent['cuisine']} listings (locations with at least "
                          f"{fc['min_location_listings']} listings): " + "; ".join(
                              f"{r['location']} ({r['listings']} of {r['location_listings']})" for r in fewest) + ".")
        sources.append("saturation")
    else:
        answer.append("Mention a cuisine (for example 'fewer listings for Thai') to see where it is least represented.")
    answer.append("Listing density measures how many restaurants are listed, not how many customers there are.")
    return {"title": title, "can_answer": True, "reason": None, "tag": "Descriptive", "data": data, "answer": answer, "sources": sources}


def _cost_rating_tiers(ctx, df, ent):
    title = "Cost and rating across price tiers and locations"
    tiers = calc.safe_run(ctx, "price_tier_analysis", df)
    if not tiers["available"]:
        return _unavailable(title, tiers["reason"])
    rows = [{k: r[k] for k in ("price_tier", "listings", "median_cost", "mean_rating", "weighted_rating")} for r in tiers["data"]]
    cur = calc.cost_unit(ctx, df) or ""
    answer = ["By price tier: " + "; ".join(
        f"{r['price_tier']}: median cost {r['median_cost']:,.0f} {cur}".rstrip() + f", mean rating {r['mean_rating']:.2f} ({r['listings']} listings)"
        for r in rows if r["mean_rating"] is not None) + "."]
    data = {"tiers": rows}
    loc = calc.safe_run(ctx, "median_cost_by_location", df)
    if loc["available"]:
        ok = [r for r in loc["data"] if r["sufficient_sample"]]
        if len(ok) >= 2:
            data["most_expensive_locations"] = [{k: r[k] for k in ("location", "median_cost", "n_cost")} for r in ok[:3]]
            data["least_expensive_locations"] = [{k: r[k] for k in ("location", "median_cost", "n_cost")} for r in ok[-3:]]
            answer.append("Highest median cost: " + ", ".join(f"{r['location']} ({r['median_cost']:,.0f})" for r in ok[:3]) +
                          "; lowest: " + ", ".join(f"{r['location']} ({r['median_cost']:,.0f})" for r in ok[-3:]) + ".")
    sp = calc.safe_run(ctx, "spearman", df)
    if sp["available"]:
        pair = next((r for r in sp["data"] if {r["x"], r["y"]} == {"rating", "cost"} and r["rho"] is not None), None)
        if pair:
            data["rating_cost_spearman"] = {k: pair[k] for k in ("rho", "p_value", "n")}
            answer.append(pair["note"])
    return {"title": title, "can_answer": True, "reason": None, "tag": "Descriptive", "data": data, "answer": answer,
            "sources": ["price_tier_analysis", "median_cost_by_location", "spearman"]}


def _online_booking(ctx, df, ent):
    title = "Rating distributions by online ordering and table booking"
    mw = calc.safe_run(ctx, "mann_whitney", df)
    if not mw["available"] or not mw["data"]:
        return _unavailable(title, mw["reason"] or "Requires an online-order or table-booking Yes/No column and ratings.")
    rows = [{k: r[k] for k in ("label", "n_yes", "n_no", "median_yes", "median_no", "p_value", "effect_size_r")} for r in mw["data"]]
    answer = [r["note"] if r.get("note") else "" for r in mw["data"]]
    answer = [f"{r['label']}: median {r['median_yes']:.2f} (Yes, n={r['n_yes']}) vs {r['median_no']:.2f} (No, n={r['n_no']}). {n}"
              if r["median_yes"] is not None and r["median_no"] is not None else f"{r['label']}: {n}" for r, n in zip(rows, answer)]
    return {"title": title, "can_answer": True, "reason": None, "tag": "Statistical", "data": {"tests": rows},
            "answer": answer, "sources": ["mann_whitney"]}


def _types_by_tier(ctx, df, ent):
    title = "Best restaurant types within each price tier"
    t = calc.safe_run(ctx, "types_by_tier", df)
    if not t["available"]:
        return _unavailable(title, t["reason"])
    best = {}
    for r in t["data"]:
        if r["sufficient_sample"] and r["price_tier"] not in best:
            best[r["price_tier"]] = {k: r[k] for k in ("restaurant_type", "weighted_rating", "n_rated")}
    answer = [f"{tier}: {b['restaurant_type']} (weighted rating {b['weighted_rating']:.2f}, n={b['n_rated']})." for tier, b in best.items()]
    if not answer:
        answer = [f"No restaurant type has at least {ctx.settings['min_group_n']} rated restaurants within a tier."]
    answer.append("Only types meeting the sample-size rule are ranked; differences between close scores may not be meaningful.")
    return {"title": title, "can_answer": True, "reason": None, "tag": "Descriptive", "data": {"best_by_tier": best},
            "answer": answer, "sources": ["types_by_tier"]}


def _location_brief(ctx, df, ent):
    title = "What to investigate before opening"
    if not ctx.capabilities["fields"]["location"]:
        return _unavailable(title, "Requires a location column.")
    loc = ent.get("location")
    if not loc:
        return _unavailable(title, "Choose a location (use the location selector or name one in your question).")
    here = df[df["location"] == loc]
    if here.empty:
        return _unavailable(title, f"No restaurants are listed in {loc} in this dataset.")
    min_n = ctx.settings["min_group_n"]
    dens = calc.run(ctx, "location_density", df)
    rank = next((i + 1 for i, r in enumerate(dens) if r["location"] == loc), None)
    data = {"location": loc, "listings": int(len(here)), "density_rank": rank, "locations_total": len(dens),
            "mean_rating": calc.run(ctx, "mean_rating", here) if ctx.capabilities["fields"]["rating"] else None,
            "dataset_mean_rating": calc.run(ctx, "mean_rating", df) if ctx.capabilities["fields"]["rating"] else None}
    answer = [f"{loc} has {len(here)} listings (rank {rank} of {len(dens)} locations by listing density)."
              + (" This is a small sample; treat its averages as indicative." if len(here) < min_n else "")]
    if data["mean_rating"] is not None and data["dataset_mean_rating"] is not None:
        answer.append(f"Mean rating there is {data['mean_rating']:.2f} vs {data['dataset_mean_rating']:.2f} across the dataset.")
    if calc.cost_guard(here) is None and calc.cost_guard(df) is None:
        data["median_cost"] = calc.run(ctx, "median_cost", here)
        data["dataset_median_cost"] = calc.run(ctx, "median_cost", df)
        answer.append(f"Median cost {data['median_cost']:,.0f} vs {data['dataset_median_cost']:,.0f} overall.")
    if ctx.capabilities["fields"]["cuisine"]:
        sat = [r for r in calc.run(ctx, "saturation", df) if r["location"] == loc]
        sat.sort(key=lambda r: (-r["listings"], r["cuisine"]))
        data["top_cuisines"] = [{k: r[k] for k in ("cuisine", "listings", "location_quotient")} for r in sat[:5]]
        present = {r["cuisine"] for r in sat}
        popular = [r for r in calc.run(ctx, "cuisine_popularity", df) if r["listings"] >= min_n]
        under = [{"cuisine": r["cuisine"], "location_quotient": next((s["location_quotient"] for s in sat if s["cuisine"] == r["cuisine"]), 0.0)}
                 for r in popular]
        under = sorted([u for u in under if u["location_quotient"] < 0.7], key=lambda u: (u["location_quotient"], u["cuisine"]))[:5]
        data["under_represented_cuisines"] = under
        answer.append("Most listed here: " + ", ".join(f"{r['cuisine']} ({r['listings']})" for r in data["top_cuisines"]) + ".")
        if under:
            answer.append("Under-represented here relative to the dataset (LQ < 0.7): " + ", ".join(
                f"{u['cuisine']} (LQ {u['location_quotient']:.2f}{'' if u['cuisine'] in present else ', none listed'})" for u in under) + ".")
    opp = calc.safe_run(ctx, "opportunity", df)
    if opp["available"]:
        mine = [r for r in opp["data"] if r["location"] == loc][:3]
        data["opportunity_pairs"] = [{k: r[k] for k in ("cuisine", "score", "n_rated")} for r in mine]
        if mine:
            answer.append("Exploratory Opportunity Score leaders here: " + ", ".join(f"{r['cuisine']} ({r['score']:.0f}/100)" for r in mine) + ".")
    data["investigate_outside_this_data"] = ["Rent and lease terms", "Footfall and visibility at specific streets",
                                             "Competitors' actual sales and table turnover", "Delivery radius and platform commissions",
                                             "Licences, parking and local regulations", "Target customers' spending and timing"]
    answer.append("Before deciding, investigate what this dataset cannot show: rent, footfall, competitor sales, "
                  "delivery economics and licensing.")
    return {"title": f"{title} in {loc}", "can_answer": True, "reason": None, "tag": "Suggestion", "data": data,
            "answer": answer, "sources": ["location_density", "saturation", "cuisine_popularity", "opportunity"]}


def _overview(ctx, df, ent):
    cards = calc.kpi_cards(ctx, df)
    data = {c["id"]: c["value"] for c in cards}
    parts = [f"{data['total_restaurants']:,} restaurants analyzed"]
    if data.get("mean_rating") is not None:
        parts.append(f"mean rating {data['mean_rating']:.2f} (median {data['median_rating']:.2f})")
    if data.get("median_cost") is not None:
        parts.append(f"median cost {data['median_cost']:,.0f}")
    if data.get("location_count"):
        parts.append(f"{data['location_count']} locations")
    if data.get("cuisine_count"):
        parts.append(f"{data['cuisine_count']} cuisines")
    return {"title": "Dataset overview", "can_answer": True, "reason": None, "tag": "Descriptive", "data": data,
            "answer": ["; ".join(parts) + "."], "sources": ["total_restaurants", "mean_rating", "median_cost"]}


def _top_rated(ctx, df, ent):
    min_n = ctx.settings["min_group_n"]
    if ent.get("by") == "location":
        title = "Locations ranked by weighted rating"
        if not ctx.capabilities["fields"]["location"]:
            return _unavailable(title, "The active dataset has no location field.")
        g = df.groupby("location").agg(listings=("rid", "size"), n_rated=("weighted_rating", "count"),
                                       weighted_rating=("weighted_rating", "mean")).reset_index()
        g = g[g["n_rated"] >= min_n].sort_values(["weighted_rating", "location"], ascending=[False, True])
        rows = [{"location": r.location, "weighted_rating": float(r.weighted_rating), "listings": int(r.listings),
                 "n_rated": int(r.n_rated)} for r in g.itertuples()]
        key, sources = "location", ["weighted_rating"]
    else:
        title = "Cuisines ranked by weighted rating"
        res = calc.safe_run(ctx, "wr_by_cuisine", df)
        if not res["available"]:
            return _unavailable(title, res["reason"])
        rows = [{k: r[k] for k in ("cuisine", "weighted_rating", "listings", "n_rated")}
                for r in res["data"] if r["sufficient_sample"]]
        key, sources = "cuisine", ["wr_by_cuisine"]
    if not rows:
        return _unavailable(title, f"No {key} has at least {min_n} rated restaurants.")
    fmt = lambda r: f"{r[key]} (WR {r['weighted_rating']:.2f}, n={r['n_rated']})"
    answer = ["Highest weighted rating: " + "; ".join(fmt(r) for r in rows[:5]) + ".",
              "Lowest weighted rating: " + "; ".join(fmt(r) for r in rows[-3:][::-1]) + ".",
              f"Only groups with at least {min_n} rated restaurants are ranked; weighted rating shrinks small samples "
              "toward the dataset average."]
    return {"title": title, "can_answer": True, "reason": None, "tag": "Descriptive",
            "data": {"ranked_by": key, "rows": rows}, "answer": answer, "sources": sources}


HANDLERS = {"cuisine_gaps": _cuisine_gaps, "location_density": _location_density, "cost_rating_tiers": _cost_rating_tiers,
            "online_booking": _online_booking, "types_by_tier": _types_by_tier, "location_brief": _location_brief,
            "overview": _overview, "top_rated": _top_rated}


def ask(ctx: Context, question: str, location: str | None = None, intent_hint: str | None = None) -> dict:
    df = apply_filters(ctx, Filters())
    intent, scores = (intent_hint, {}) if intent_hint in HANDLERS else detect_intent(question)
    entities = find_entities(ctx, question)
    if location:
        entities["location"] = location
    if intent == "top_rated" and any(w in question.lower() for w in LOCATION_WORDS):
        entities["by"] = "location"
    base ={"question": question, "intent": intent, "entities": entities, "dataset_id": ctx.dataset_id,
            "dataset_name": ctx.meta.get("name"), "is_demo_data": bool(ctx.meta.get("is_demo")), "scope": "Full active dataset (no filters)",
            "caveats": ["Results describe restaurant listings in one dataset snapshot.",
                        "Ratings are not revenue, demand, footfall or profit; correlation is not causation."]}
    if intent is None:
        return {**base, "title": "Question not recognized", "can_answer": False, "tag": None, "data": None, "answer": [], "sources": [],
                "reason": "I can only answer questions that map to a supported analysis. Try one of the suggested questions.",
                "explanation": None, "mode": mode()}
    result = HANDLERS[intent](ctx, df, entities)
    out = {**base, **result}
    out["explanation"], out["mode"], out["ai_error"] = explain(question, out)
    return out


# ---------------------------------------------------------------------------
# Optional LLM explanation (only the computed JSON is sent)
# ---------------------------------------------------------------------------
def mode() -> str:
    """'llm' when the selected provider's API key is configured, otherwise labeled Demo Mode."""
    return "llm" if llm_client.is_configured() else "demo"


SYSTEM_PROMPT = (
    "You explain restaurant-listing analysis results to a business audience. Use only the numbers present in the "
    "JSON you are given; never invent, estimate or round them differently in a way that changes meaning. Mention sample "
    "sizes when they are present. Do not make causal claims: ratings are platform scores and do not measure revenue, "
    "demand, footfall or profit. If the JSON says the question cannot be answered, explain why in one sentence. "
    "Write 2 short paragraphs of plain text (no headings, no bullet lists, no markdown), under 170 words."
)


def explain(question: str, result: dict) -> tuple[str | None, str, str | None]:
    """Returns (explanation, mode, ai_error). Demo Mode returns (None, 'demo', None).
    Only the computed JSON result is sent to the language model, never the dataset itself."""
    if mode() != "llm" or not result.get("can_answer"):
        return None, mode(), None
    payload = {k: result.get(k) for k in ("title", "data", "answer", "caveats", "entities", "is_demo_data")}
    prompt = f"Question: {question}\n\nComputed result (JSON):\n{json.dumps(payload, default=str)}"
    try:
        return llm_client.ask_llm(prompt, system=SYSTEM_PROMPT), "llm", None
    except llm_client.LLMRefused:
        return None, "llm", "The AI service declined to explain this result; the computed answer is shown instead."
    except llm_client.LLMError as exc:
        return None, "llm", f"{exc} The computed answer is shown instead."
