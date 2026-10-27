"""Authentication, session handling, route protection and per-user dataset ownership."""
import io
import json
import re
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import auth, main
from app.config import reload_settings
from app.store import Store

from .conftest import TEST_PASSWORD, TINY_MAPPING, sign_up, tiny_raw

SECRET = "test-secret-for-pytest-only-0123456789abcdef"


def _login(c, email="analyst@example.com", password=TEST_PASSWORD):
    return c.post("/api/auth/login", json={"email": email, "password": password})


# ---- registration ------------------------------------------------------------
def test_register_success_sets_httponly_cookie(anon_client):
    r = anon_client.post("/api/auth/register", json={"name": "  Asha  Rao ", "email": " Asha@Example.COM ",
                                                     "password": TEST_PASSWORD})
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "asha@example.com" and r.json()["user"]["name"] == "Asha Rao"
    cookie = r.headers["set-cookie"]
    assert "riq_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "password_hash" not in r.text and TEST_PASSWORD not in r.text
    assert anon_client.get("/api/auth/me").json()["user"]["email"] == "asha@example.com"


def test_register_duplicate_email(anon_client):
    sign_up(anon_client, "dup@example.com")
    r = anon_client.post("/api/auth/register", json={"name": "X", "email": "DUP@example.com", "password": TEST_PASSWORD})
    assert r.status_code == 409 and "already exists" in r.json()["error"]


@pytest.mark.parametrize("password,msg", [("short1", "at least 8"), ("onlyletters", "letter and one number"),
                                          ("12345678", "letter and one number"), ("a1" * 40, "72 bytes")])
def test_register_weak_password(anon_client, password, msg):
    r = anon_client.post("/api/auth/register", json={"name": "X", "email": "w@example.com", "password": password})
    assert r.status_code == 422 and msg in r.json()["error"]


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "", "two@@example.com"])
def test_register_invalid_email(anon_client, email):
    r = anon_client.post("/api/auth/register", json={"name": "X", "email": email, "password": TEST_PASSWORD})
    assert r.status_code == 422 and "valid email" in r.json()["error"]


def test_registration_can_be_disabled(anon_client, monkeypatch):
    monkeypatch.setenv("ALLOW_REGISTRATION", "false")
    reload_settings()
    assert anon_client.get("/api/auth/config").json()["allow_registration"] is False
    r = anon_client.post("/api/auth/register", json={"name": "X", "email": "x@example.com", "password": TEST_PASSWORD})
    assert r.status_code == 403


# ---- login ---------------------------------------------------------------------
def test_login_success_and_logout(anon_client):
    sign_up(anon_client)
    anon_client.post("/api/auth/logout")
    assert anon_client.get("/api/auth/me").status_code == 401
    r = _login(anon_client, "ANALYST@example.com")
    assert r.status_code == 200 and r.json()["user"]["name"] == "Test Analyst"
    assert anon_client.get("/api/datasets").status_code == 200


def test_wrong_password_and_unknown_email_same_message(anon_client):
    sign_up(anon_client)
    anon_client.post("/api/auth/logout")
    wrong = _login(anon_client, password="Wrong12345")
    unknown = _login(anon_client, email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"error": "Incorrect email or password."}


def test_login_rate_limited_after_5_failures(anon_client):
    sign_up(anon_client)
    anon_client.post("/api/auth/logout")
    for _ in range(5):
        assert _login(anon_client, password="Wrong12345").status_code == 401
    r = _login(anon_client)                       # even the right password is blocked now
    assert r.status_code == 429 and "Too many failed sign-in attempts" in r.json()["error"]


def test_rate_limit_per_ip_across_emails(anon_client):
    for i in range(5):
        _login(anon_client, email=f"user{i}@example.com", password="Wrong12345")
    assert _login(anon_client, email="fresh@example.com", password="Wrong12345").status_code == 429


# ---- tokens / me ---------------------------------------------------------------
def test_me_missing_token(anon_client):
    r = anon_client.get("/api/auth/me")
    assert r.status_code == 401 and r.json() == {"error": "Please sign in to continue."}


def _user_id(c):
    return c.get("/api/auth/me").json()["user"]["id"]


def test_me_expired_token(anon_client):
    sign_up(anon_client)
    uid = _user_id(anon_client)
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    token = jwt.encode({"sub": uid, "ver": 0, "jti": "x1", "iat": old, "exp": old + timedelta(minutes=60)}, SECRET, "HS256")
    anon_client.cookies.clear()
    r = anon_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and "session expired" in r.json()["error"]


def test_me_tampered_token(anon_client):
    sign_up(anon_client)
    token = anon_client.cookies.get("riq_session")
    anon_client.cookies.clear()
    header, payload, sig = token.split(".")
    bad_sig = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    forged = jwt.encode({"sub": "someone-else", "ver": 0, "jti": "x", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                        "a-different-secret-xxxxxxxxxxxxxxxxxxxxxx", "HS256")
    for t in (bad_sig, forged, "garbage", f"{header}.{payload}."):
        r = anon_client.get("/api/auth/me", headers={"Authorization": f"Bearer {t}"})
        assert r.status_code == 401, t


def test_logout_revokes_token(anon_client):
    sign_up(anon_client)
    token = anon_client.cookies.get("riq_session")
    anon_client.post("/api/auth/logout")
    anon_client.cookies.clear()
    assert anon_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_change_password_ends_other_sessions(anon_client):
    sign_up(anon_client)
    old_token = anon_client.cookies.get("riq_session")
    r = anon_client.post("/api/auth/change-password", json={"current_password": TEST_PASSWORD, "new_password": "NewPass456"})
    assert r.status_code == 200
    assert anon_client.get("/api/auth/me").status_code == 200        # new cookie works
    anon_client.cookies.clear()
    assert anon_client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
    assert _login(anon_client, password=TEST_PASSWORD).status_code == 401
    assert _login(anon_client, password="NewPass456").status_code == 200
    bad = anon_client.post("/api/auth/change-password", json={"current_password": "nope12345", "new_password": "Other789x"})
    assert bad.status_code == 400


# ---- route protection -------------------------------------------------------------
def _protected_routes():
    for route in main.app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/") and route.path not in auth.PUBLIC_PATHS:
            for method in route.methods:
                yield method, re.sub(r"\{[^}]+\}", "1", route.path)


def test_every_protected_route_rejects_anonymous_requests(anon_client):
    routes = list(_protected_routes())
    assert len(routes) >= 35
    for method, path in routes:
        r = anon_client.request(method, path, json={})
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.json() == {"error": "Please sign in to continue."}


def test_public_routes_stay_public(anon_client):
    assert anon_client.get("/api/health").json()["status"] == "ok"
    assert anon_client.get("/api/auth/config").status_code == 200
    assert anon_client.get("/docs").status_code == 200
    assert anon_client.get("/openapi.json").status_code == 200


def test_authenticated_call_works(client):
    assert client.get("/api/datasets").status_code == 200


# ---- storage ---------------------------------------------------------------------
def test_password_stored_as_bcrypt_hash(anon_client):
    sign_up(anon_client, "hash@example.com")
    raw = (main.store.base / "users.json").read_text(encoding="utf-8")
    assert TEST_PASSWORD not in raw
    user = json.loads(raw)["users"][0]
    assert user["password_hash"].startswith("$2b$12$") and len(user["password_hash"]) == 60


# ---- ownership -------------------------------------------------------------------
@pytest.fixture()
def two_users(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", Store(tmp_path / "data"))
    main._ctx_cache.clear()
    with TestClient(main.app) as a, TestClient(main.app) as b:
        sign_up(a, "alice@example.com", "Alice")
        sign_up(b, "bob@example.com", "Bob")
        yield a, b


def test_users_cannot_see_each_others_datasets(two_users):
    a, b = two_users
    ds = a.post("/api/demo/load").json()["active"]["dataset_id"]
    csv = tiny_raw().to_csv(index=False).encode()
    up = a.post("/api/uploads", files={"file": ("t.csv", io.BytesIO(csv), "text/csv")}).json()["upload_id"]

    assert b.get("/api/datasets").json() == {"active": None, "versions": []}
    for path in (f"/api/datasets/{ds}", f"/api/datasets/{ds}/raw", f"/api/datasets/{ds}/cleaned.csv",
                 f"/api/datasets/{ds}/remap"):
        assert b.get(path).status_code == 404, path
    for path in ("/api/dashboard", "/api/market", "/api/restaurants", "/api/export/star-schema.zip"):
        assert b.get(path, params={"dataset_id": ds}).status_code == 404, path
    assert b.put("/api/datasets/active", json={"dataset_id": ds}).status_code == 404
    assert b.post("/api/sql", json={"sql": "SELECT 1", "dataset_id": ds}).status_code == 404
    mapping = [{"source_column": c, "canonical_field": f} for c, f in TINY_MAPPING.items()]
    assert b.post(f"/api/uploads/{up}/import", json={"mapping": mapping}).status_code == 404

    # Bob's own data is independent, and Alice still sees hers
    bob_ds = b.post("/api/demo/load").json()["active"]["dataset_id"]
    assert bob_ds != ds and [v["dataset_id"] for v in b.get("/api/datasets").json()["versions"]] == [bob_ds]
    assert [v["dataset_id"] for v in a.get("/api/datasets").json()["versions"]] == [ds]
    assert a.get("/api/dashboard").json()["context"]["dataset_id"] == ds


def test_logout_then_other_user_sees_no_previous_data(two_users):
    a, b = two_users
    a.post("/api/demo/load")
    a.post("/api/auth/logout")
    assert a.get("/api/dashboard").status_code == 401


def test_first_user_claims_pre_auth_datasets(tmp_path, monkeypatch):
    """Versions imported before accounts existed belong to the first account (or the demo account)."""
    store = Store(tmp_path / "data")
    from app.cleaning import CleanSettings, clean_dataset
    res = clean_dataset(tiny_raw(), CleanSettings(mapping=TINY_MAPPING))
    store.create_dataset(res.cleaned, {**res.metadata, "name": "legacy", "reconciliation": res.reconciliation})
    monkeypatch.setattr(main, "store", store)
    main._ctx_cache.clear()
    with TestClient(main.app) as first, TestClient(main.app) as second:
        sign_up(first, "first@example.com")
        assert [v["name"] for v in first.get("/api/datasets").json()["versions"]] == ["legacy"]
        sign_up(second, "second@example.com")
        assert second.get("/api/datasets").json()["versions"] == []


def test_demo_user_seeded_and_demo_login(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_USER_EMAIL", "demo@example.com")
    monkeypatch.setenv("DEMO_USER_PASSWORD", "DemoPass123")
    reload_settings()
    monkeypatch.setattr(main, "store", Store(tmp_path / "data"))
    with TestClient(main.app) as c:                       # startup seeds the account
        assert c.get("/api/auth/config").json()["demo_available"] is True
        r = c.post("/api/auth/demo-login")
        assert r.status_code == 200 and r.json()["user"]["is_demo"] is True
        assert _login(c, "demo@example.com", "DemoPass123").status_code == 200
    with TestClient(main.app):                            # second startup does not duplicate it
        pass
    users = json.loads((tmp_path / "data" / "users.json").read_text(encoding="utf-8"))["users"]
    assert len(users) == 1


def test_no_demo_login_without_demo_user(anon_client):
    assert anon_client.get("/api/auth/config").json()["demo_available"] is False
    assert anon_client.post("/api/auth/demo-login").status_code == 404


def test_production_requires_jwt_secret(monkeypatch):
    monkeypatch.setenv("RIQ_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "")
    reload_settings()
    with pytest.raises(auth.AuthConfigError, match="JWT_SECRET is not set"):
        auth.startup_check()
    monkeypatch.setenv("JWT_SECRET", "short")
    reload_settings()
    with pytest.raises(auth.AuthConfigError, match="at least 32"):
        auth.startup_check()


def test_cors_restricted_to_frontend(anon_client):
    ok = anon_client.options("/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert ok.headers.get("access-control-allow-credentials") == "true"
    bad = anon_client.options("/api/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers
