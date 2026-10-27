"""db_check / MongoDB error handling (no MongoDB server needed)."""
import pytest
from pymongo.errors import (AutoReconnect, ConfigurationError, InvalidName, InvalidURI, OperationFailure,
                            ServerSelectionTimeoutError)

from app import db_check, main
from app.config import reload_settings
from app.db import MongoStore, classify_db_error, describe_uri, friendly_db_error, redact_uri

URI = "mongodb://riq:s3cret%40pw@127.0.0.1:27017/?authSource=admin"


@pytest.mark.parametrize("exc,kind,needle", [
    (ServerSelectionTimeoutError("127.0.0.1:27017: [WinError 10061] No connection could be made because the target "
                                 "machine actively refused it"), "not_running", "not running"),
    (ServerSelectionTimeoutError("nohost:27017: [Errno 11001] getaddrinfo failed"), "unknown_host", "could not be found"),
    (ConfigurationError("The DNS query name does not exist: _mongodb._tcp.nohost.example.net."), "unknown_host",
     "could not be found"),
    (ServerSelectionTimeoutError("cluster0: SSL handshake failed: [SSL: CERTIFICATE_VERIFY_FAILED]"), "tls", "TLS"),
    (OperationFailure("Authentication failed.", code=18), "auth_failed", "wrong user name or password"),
    (OperationFailure("bad auth : authentication failed", code=8000), "auth_failed", "URL-encoded"),
    (OperationFailure("not authorized on restaurantiq to execute command", code=13), "no_privileges", "readWrite"),
    (OperationFailure("Command listCollections requires authentication", code=13), "auth_required",
     "requires a user name and password"),
    (InvalidURI("Invalid URI scheme: URI must begin with 'mongodb://' or 'mongodb+srv://'"), "bad_uri",
     "not a valid MongoDB connection string"),
    (InvalidName("database names cannot contain the character ' '"), "bad_db_name", "not a valid database name"),
    (AutoReconnect("connection closed"), "connection_lost", "was lost"),
])
def test_error_kinds_and_messages(exc, kind, needle):
    assert classify_db_error(exc) == kind
    text = friendly_db_error(exc, URI, "restaurantiq")
    assert needle in text and "s3cret" not in text


def test_uri_helpers_never_show_the_password():
    assert redact_uri(URI) == "mongodb://riq:****@127.0.0.1:27017/?authSource=admin"
    assert redact_uri("mongodb://127.0.0.1:27017") == "mongodb://127.0.0.1:27017"
    info = describe_uri("mongodb+srv://ana%40corp:p%40ss@cluster0.abc.mongodb.net/?retryWrites=true")
    assert info == {"scheme": "mongodb+srv", "user": "ana@corp", "hosts": "cluster0.abc.mongodb.net", "has_password": True}
    assert describe_uri("mysql://x")["scheme"] is None
    # A password that was NOT URL-encoded is still hidden completely (credentials end at the last @).
    raw = "mongodb://riq:p@ss:w/rd#1@127.0.0.1:27017/?authSource=restaurantiq"
    assert redact_uri(raw) == "mongodb://riq:****@127.0.0.1:27017/?authSource=restaurantiq"
    assert describe_uri(raw)["hosts"] == "127.0.0.1:27017"


def test_unencoded_password_is_a_clear_bad_uri_error(tmp_path, capsys, monkeypatch):
    """PyMongo raises a plain ValueError here; it must become the friendly 'not a valid connection string'."""
    store = MongoStore("mongodb://riq:p@ss:w/rd#1@127.0.0.1:27017", "restaurantiq", tmp_path, timeout_ms=300)
    with pytest.raises(Exception) as info:
        store.health() and store.count_users()
    assert "not a valid MongoDB connection string" in str(info.value) and "ss:w" not in str(info.value)
    monkeypatch.setenv("RIQ_MONGO_URI", "mongodb://riq:p@ss:w/rd#1@127.0.0.1:27017")
    reload_settings()
    assert db_check.check() == 1
    out = capsys.readouterr().out
    assert "FAIL (bad uri)" in out and "ss:w/rd" not in out


def test_config_reads_mongo_settings(monkeypatch):
    monkeypatch.setenv("RIQ_MONGO_URI", " mongodb://db.example:27019 ")
    monkeypatch.setenv("RIQ_MONGO_DB", "riq_other")
    s = reload_settings()
    assert (s.mongo_uri, s.mongo_db, s.storage) == ("mongodb://db.example:27019", "riq_other", "file")
    assert "27019" not in repr(s)                      # the URI may hold a password: kept out of repr()


def test_db_check_reports_server_not_running(monkeypatch, capsys):
    monkeypatch.setenv("RIQ_MONGO_URI", "mongodb://riq:hidden-pw@127.0.0.1:1")   # nothing listens on port 1
    monkeypatch.setenv("RIQ_MONGO_TIMEOUT_MS", "300")
    reload_settings()
    assert db_check.check() == 1
    out = capsys.readouterr().out
    assert "FAIL (not running)" in out and "net start MongoDB" in out
    assert "hidden-pw" not in out and "mongodb://riq:****@127.0.0.1:1" in out


def test_db_check_reports_bad_uri(monkeypatch, capsys):
    monkeypatch.setenv("RIQ_MONGO_URI", "mysql://root@127.0.0.1:3306")
    reload_settings()
    assert db_check.check() == 1
    assert "FAIL (bad uri)" in capsys.readouterr().out


def test_unreachable_database_gives_friendly_503(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    bad = MongoStore("mongodb://nobody:wrong@127.0.0.1:1", "none", tmp_path, timeout_ms=300)
    monkeypatch.setattr(main, "store", bad)
    main._ctx_cache.clear()
    with TestClient(main.app) as c:                    # the API still starts and explains the problem
        h = c.get("/api/health").json()
        assert h["status"] == "ok" and h["database"]["connected"] is False
        assert c.get("/api/datasets").status_code == 401          # protected before touching the database
        r = c.post("/api/auth/login", json={"email": "a@example.com", "password": "Secret123"})
        assert r.status_code == 503 and "MongoDB" in r.json()["error"] and "wrong" not in r.json()["error"]
        r = c.post("/api/auth/register", json={"name": "A", "email": "a@example.com", "password": "Secret123"})
        assert r.status_code == 503 and "Start the MongoDB service" in r.json()["error"]
