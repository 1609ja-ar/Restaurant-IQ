"""Shared fixtures: an isolated data directory per test and small hand-checkable datasets."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from app.cleaning import CleanSettings, clean_dataset
from app.kpis import build_context
from app.store import DEFAULT_SETTINGS, Store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", Store(tmp_path / "data"))
    main._ctx_cache.clear()
    with TestClient(main.app) as c:
        yield c
    main._ctx_cache.clear()


TINY_MAPPING = {"name": "restaurant_name", "address": "address", "area": "locality", "cuisines": "cuisines",
                "rate": "rating", "votes": "review_count", "cost": "cost", "online": "online_order"}


def tiny_raw() -> pd.DataFrame:
    """Six raw rows with a known answer for every rule (see tests/test_kpis.py for the hand calculation)."""
    return pd.DataFrame({
        "name": ["A", "B", "C", "a ", "D", "E"],
        "address": ["1 X St", "2 Y St", "3 Z St", "1 x st.", "4 W St", "5 V St"],
        "area": ["North", "North", "South", "North", "South", "South"],
        "cuisines": ["Chinese, north indian", "Chinese", "Italian", "chinese", "Italian, Chinese", "Cafe"],
        "rate": ["4.0/5", "3.0/5", "NEW", "4.5/5", "5.0/5", "6/5"],
        "votes": ["10", "0", "2", "100", "30", "5"],
        "cost": ["1,000", "500", None, "800", "2,000", "300"],
        "online": ["Yes", "No", "yes", "No", "maybe", None],
    })


def make_ctx(raw: pd.DataFrame, mapping: dict, settings: dict | None = None, **clean_kwargs):
    result = clean_dataset(raw, CleanSettings(mapping=mapping, **clean_kwargs))
    ctx = build_context("test", result.cleaned, result.metadata, {**DEFAULT_SETTINGS, **(settings or {})})
    return ctx, result
