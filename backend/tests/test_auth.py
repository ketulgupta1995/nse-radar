from datetime import datetime, timedelta

import pytest

from app import timeutil
from app.api import auth as auth_api
from app.cloud import auth
from app.config import TZ

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=TZ)


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    monkeypatch.setenv("APP_SECRET", "s3cret")
    monkeypatch.setattr(timeutil, "now", lambda: NOW)
    monkeypatch.setattr(auth_api, "FAIL_DELAY_S", 0)


def _cookie(value: str) -> dict:
    return {"Cookie": f"{auth.COOKIE}={value}"}


def test_gate_off_without_env(client, monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/me").json() == {"auth_required": False, "logged_in": True}


def test_401_without_cookie(client, gate):
    r = client.get("/api/settings")
    assert r.status_code == 401
    assert r.json() == {"detail": "login required"}


def test_non_api_paths_not_gated(client, gate):
    assert client.get("/some/page").status_code == 200


def test_exempt_paths(client, gate):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/me").json() == {"auth_required": True, "logged_in": False}
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401


def test_bad_password_401_without_cookie(client, gate):
    r = client.post("/api/login", json={"password": "wrong"})
    assert r.status_code == 401
    assert "set-cookie" not in r.headers


def test_good_password_sets_cookie(client, gate):
    r = client.post("/api/login", json={"password": "open-sesame"})
    assert r.status_code == 204
    sc = r.headers["set-cookie"]
    assert sc.startswith(f"{auth.COOKIE}=")
    low = sc.lower()
    assert "httponly" in low and "secure" in low and "samesite=lax" in low
    assert f"max-age={90 * 24 * 3600}" in low
    value = sc.split(";", 1)[0].split("=", 1)[1]
    assert auth.cookie_ok(value, NOW)
    assert client.get("/api/settings", headers=_cookie(value)).status_code == 200
    assert client.get("/api/me", headers=_cookie(value)).json()["logged_in"] is True


def test_expired_cookie_fails(client, gate, monkeypatch):
    value = auth.make_cookie(NOW - timedelta(days=91))
    assert not auth.cookie_ok(value, NOW)
    assert client.get("/api/settings", headers=_cookie(value)).status_code == 401


def test_tampered_cookie_fails(client, gate):
    value = auth.make_cookie(NOW)
    expiry, sig = value.split(".")
    longer = f"{int(expiry) + 999}.{sig}"
    bad_sig = f"{expiry}.{'0' * len(sig)}"
    for v in (longer, bad_sig, "garbage", "", "x.y"):
        assert not auth.cookie_ok(v, NOW)
    assert client.get("/api/settings", headers=_cookie(longer)).status_code == 401


def test_cookie_signed_with_other_secret_fails(gate, monkeypatch):
    value = auth.make_cookie(NOW)
    monkeypatch.setenv("APP_SECRET", "rotated")
    assert not auth.cookie_ok(value, NOW)


def test_logout_clears_cookie(client, gate):
    value = auth.make_cookie(NOW)
    r = client.post("/api/logout", headers=_cookie(value))
    assert r.status_code == 204
    assert "max-age=0" in r.headers["set-cookie"].lower()
