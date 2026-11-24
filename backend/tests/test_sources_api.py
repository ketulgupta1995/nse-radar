import pytest

from app import db
from app.sources import registry, secrets
from app.sources.base import Bar, BaseSource, CapabilitySpec, JobVariant
from app.sources.store import save_bars


def make(name, caps=("bars",), secret_keys=()):
    specs = tuple(
        CapabilitySpec(c, "by_symbol", (JobVariant(suffix="daily"),), adjusted=False if c == "bars" else None)
        for c in caps
    )
    return type(
        name, (BaseSource,),
        {"name": name, "label": name.title(), "description": "desc", "homepage": "https://x.test",
         "capabilities": specs, "secrets": secret_keys},
    )()  # fmt: skip


@pytest.fixture
def api(client):
    registry.clear()
    registry.register(make("alpha"))
    registry.register(make("beta", caps=("bars", "news"), secret_keys=("API_KEY",)))
    yield client
    registry.clear()


def test_list_shape(api):
    rows = {r["name"]: r for r in api.get("/api/sources").json()}
    a = rows["alpha"]
    assert set(a) == {
        "name", "label", "description", "homepage", "enabled", "paused_reason", "last_ok_at",
        "last_error_at", "last_error", "capabilities", "secrets", "stats",
    }  # fmt: skip
    assert a["enabled"] is True and a["stats"] == {"ok_7d": 0, "failed_7d": 0, "not_found_7d": 0}
    assert a["capabilities"] == [
        {"capability": "bars", "mode": "by_symbol", "adjusted": False, "jobs": ["bars.alpha.daily"]}
    ]
    assert rows["beta"]["secrets"] == {"API_KEY": False}


def test_enable_disable_and_reason_cleared(api):
    out = api.put("/api/sources/alpha", json={"enabled": False}).json()
    assert out["enabled"] is False
    registry.set_enabled("alpha", False, "refused (HTTP 403)")
    assert api.get("/api/sources").json()[0]["paused_reason"] == "refused (HTTP 403)"
    out = api.put("/api/sources/alpha", json={"enabled": True}).json()
    assert out["enabled"] is True and out["paused_reason"] is None
    assert api.put("/api/sources/nope", json={"enabled": True}).status_code == 404
    assert api.put("/api/sources/alpha", json={}).status_code == 400


def test_stats_from_source_fetch(api):
    with db.tx() as c:
        for key, status in (("A", "ok"), ("B", "ok"), ("C", "failed"), ("D", "not_found")):
            c.execute(
                "INSERT INTO source_fetch(source, capability, key, status, fetched_at) VALUES "
                "('alpha','bars',?,?,?)",
                (key, status, db.timeutil.now_iso()),
            )
        c.execute(
            "INSERT INTO source_fetch(source, capability, key, status, fetched_at) VALUES "
            "('alpha','bars','OLD','failed','2020-01-01T00:00:00+05:30')"
        )
    a = next(r for r in api.get("/api/sources").json() if r["name"] == "alpha")
    assert a["stats"] == {"ok_7d": 2, "failed_7d": 1, "not_found_7d": 1}


def test_secrets_never_returned(api):
    r = api.put("/api/sources/beta/secrets", json={"API_KEY": "  super-secret  "})
    assert r.json() == {"API_KEY": True}
    assert secrets.get("beta", "API_KEY") == "super-secret"
    assert "super-secret" not in api.get("/api/sources").text
    assert api.put("/api/sources/beta/secrets", json={"OTHER": "x"}).status_code == 400
    assert api.put("/api/sources/alpha/secrets", json={"API_KEY": "x"}).status_code == 400
    assert api.put("/api/sources/beta/secrets", json={"API_KEY": None}).json() == {"API_KEY": False}


def test_priority_get_put_validation(api):
    p = api.get("/api/sources/priority").json()
    assert p["capabilities"] == {"bars": ["alpha", "beta"], "news": ["beta"]}
    assert p["bars"] == ["nse_bhav", "yfinance"]  # default setting, untouched by registry contents
    out = api.put("/api/sources/priority", json={"bars": ["beta", "alpha"]}).json()
    assert out["bars"] == ["beta", "alpha"] and out["universe"] == ["nse_archives"]
    assert db.get_setting("source_priority")["bars"] == ["beta", "alpha"]
    assert api.put("/api/sources/priority", json={"bars": ["ghost"]}).status_code == 400
    assert api.put("/api/sources/priority", json={"news": ["alpha"]}).status_code == 400
    assert api.put("/api/sources/priority", json={"bogus": []}).status_code == 400
    assert api.put("/api/sources/priority", json={"bars": ["alpha", "alpha"]}).status_code == 400


def test_coverage_shape(api):
    with db.tx() as c:
        save_bars("alpha", [Bar("A", "2026-01-01", 1, 1, 1, 1), Bar("A", "2026-01-02", 1, 1, 1, 1),
                            Bar("B", "2026-01-05", 1, 1, 1, 1)], c)  # fmt: skip
    rows = api.get("/api/sources/coverage?capability=bars").json()
    assert rows == [
        {"source": "alpha", "symbols": 2, "first_date": "2026-01-01", "last_date": "2026-01-05", "rows": 3}
    ]
    assert api.get("/api/sources/coverage?capability=quarters").json() == []
    assert api.get("/api/sources/coverage?capability=news").status_code == 400
