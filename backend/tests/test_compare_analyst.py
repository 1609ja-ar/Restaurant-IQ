"""Compare and AI Analyst: values must equal the Dashboard's for the same selection."""
import io
import types

import httpx
import pandas as pd
import pytest

from app import analyst


@pytest.fixture()
def demo(client):
    client.post("/api/demo/load")
    return client


def test_compare_cuisines_match_dashboard(demo):
    r = demo.post("/api/compare", json={"kind": "cuisine", "items": ["Chinese", "Thai"]}).json()
    assert [e["name"] for e in r["entities"]] == ["Chinese", "Thai"]
    for e in r["entities"]:
        dash = {k["id"]: k["value"] for k in demo.get("/api/dashboard", params={"cuisine": e["name"]}).json()["kpis"]}
        assert e["values"]["listings"] == dash["total_restaurants"]
        assert e["values"]["weighted_rating"] == pytest.approx(dash["weighted_rating"])
        assert e["values"]["median_cost"] == pytest.approx(dash["median_cost"])
    assert r["summary"] and not any("because" in s.lower() for s in r["summary"])


def test_compare_locations_and_restaurants(demo):
    r = demo.post("/api/compare", json={"kind": "location", "items": ["HSR", "BTM", "Indiranagar"]})
    assert r.status_code == 200 and len(r.json()["entities"]) == 3
    picks = demo.get("/api/compare/search", params={"q": "spice"}).json()["items"][:2]
    assert len(picks) == 2
    rr = demo.post("/api/compare", json={"kind": "restaurant", "items": [str(p["rid"]) for p in picks]}).json()
    assert [e["values"]["rating"] for e in rr["entities"]] == [p["rating"] for p in picks]


def test_compare_validation(demo):
    assert demo.post("/api/compare", json={"kind": "cuisine", "items": ["Thai"]}).status_code == 422
    assert demo.post("/api/compare", json={"kind": "cuisine", "items": ["Thai", "Thai"]}).status_code == 422
    bad = demo.post("/api/compare", json={"kind": "cuisine", "items": ["Thai", "Martian food"]})
    assert bad.status_code == 422 and "No restaurants found" in bad.json()["error"]
    assert demo.post("/api/compare", json={"kind": "restaurant", "items": ["999999", "1"]}).status_code == 422


@pytest.mark.parametrize("q,intent", [
    ("Which cuisines have above-average weighted ratings with below-average listing counts?", "cuisine_gaps"),
    ("Which neighborhoods have the highest listing density?", "location_density"),
    ("How do cost and rating vary across price tiers?", "cost_rating_tiers"),
    ("Do restaurants with online ordering have different ratings?", "online_booking"),
    ("Which restaurant types have the highest weighted rating within each price tier?", "types_by_tier"),
    ("What should an entrepreneur investigate before opening in HSR?", "location_brief"),
    ("Which cuisine has the best ratings?", "top_rated"),
    ("What are the top-rated locations?", "top_rated"),
    ("What is the weather tomorrow?", None),
])
def test_intent_detection(q, intent):
    assert analyst.detect_intent(q)[0] == intent


def test_all_suggested_questions_answer_in_demo_mode(demo, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sugg = demo.get("/api/analyst/suggestions").json()
    assert sugg["mode"] == "demo" and len(sugg["suggestions"]) == 6
    for s in sugg["suggestions"]:
        body = {"question": s["question"], "location": "HSR" if s["id"] == "location_brief" else None}
        r = demo.post("/api/analyst/ask", json=body).json()
        assert r["intent"] == s["id"] and r["can_answer"], (s["id"], r.get("reason"))
        assert r["mode"] == "demo" and r["explanation"] is None and r["answer"]


def test_top_rated_ranks_cuisines_and_locations(demo):
    r = demo.post("/api/analyst/ask", json={"question": "Which cuisine has the best ratings?"}).json()
    assert r["intent"] == "top_rated" and r["can_answer"] and r["data"]["ranked_by"] == "cuisine"
    wr = [x["weighted_rating"] for x in r["data"]["rows"]]
    assert wr == sorted(wr, reverse=True)
    r = demo.post("/api/analyst/ask", json={"question": "best rated locations"}).json()
    assert r["can_answer"] and r["data"]["ranked_by"] == "location" and r["data"]["rows"][0]["location"]


def test_analyst_numbers_come_from_calculations(demo):
    r = demo.post("/api/analyst/ask", json={"question": "Which neighborhoods have the highest listing density?"}).json()
    dens = demo.get("/api/market").json()["location_density"]["data"]
    assert r["data"]["top_locations"][0]["listings"] == dens[0]["listings"]


def test_analyst_cannot_answer_cases(demo):
    r = demo.post("/api/analyst/ask", json={"question": "What is the weather tomorrow?"}).json()
    assert r["can_answer"] is False and "suggested" in r["reason"]
    r2 = demo.post("/api/analyst/ask", json={"question": "What should an entrepreneur investigate before opening?"}).json()
    assert r2["can_answer"] is False and "Choose a location" in r2["reason"]


def test_analyst_unanswerable_when_fields_missing(client):
    csv = pd.DataFrame({"name": ["A", "B"], "cuisine": ["Thai", "Cafe"], "rate": ["4/5", "3/5"]}).to_csv(index=False).encode()
    up = client.post("/api/uploads", files={"file": ("x.csv", io.BytesIO(csv), "text/csv")}).json()
    client.post(f"/api/uploads/{up['upload_id']}/import", json={"mapping": [
        {"source_column": "name", "canonical_field": "restaurant_name"}, {"source_column": "cuisine", "canonical_field": "cuisines"},
        {"source_column": "rate", "canonical_field": "rating"}], "rating_scale_max": 5})
    r = client.post("/api/analyst/ask", json={"question": "Do restaurants with online ordering have different ratings?"}).json()
    assert r["can_answer"] is False and "online-order" in r["reason"]


def test_llm_errors_are_friendly_and_secret_free(demo, monkeypatch):
    import anthropic
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")

    def create(**kw):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    class Boom:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    monkeypatch.setattr(anthropic, "Anthropic", Boom)
    r = demo.post("/api/analyst/ask", json={"question": "How do cost and rating vary across price tiers?"}).json()
    assert r["mode"] == "llm" and r["explanation"] is None and "could not be reached" in r["ai_error"]
    assert r["answer"] and "sk-test" not in str(r)


def test_llm_explanation_used_when_available(demo, monkeypatch):
    import anthropic
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    captured = {}

    def create(**kw):
        captured.update(kw)
        return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text="Plain explanation.")])

    class Fake:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    monkeypatch.setattr(anthropic, "Anthropic", Fake)
    r = demo.post("/api/analyst/ask", json={"question": "Which restaurant types have the highest weighted rating within each price tier?"}).json()
    assert r["explanation"] == "Plain explanation." and r["mode"] == "llm"
    assert captured["model"] == "claude-opus-5-5" and captured["fallbacks"] == "default"
    assert "best_by_tier" in captured["messages"][0]["content"]   # only the computed JSON is sent


def test_llm_refusal_falls_back_to_computed_answer(demo, monkeypatch):
    import anthropic
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")

    class Fake:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(
                create=lambda **kw: types.SimpleNamespace(stop_reason="refusal", content=[])))
    monkeypatch.setattr(anthropic, "Anthropic", Fake)
    r = demo.post("/api/analyst/ask", json={"question": "Which neighborhoods have the highest listing density?"}).json()
    assert r["explanation"] is None and "declined" in r["ai_error"] and r["answer"]
