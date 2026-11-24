from datetime import date

import pandas as pd
import pytest

from app import db, timeutil
from app.analytics import frames
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec, IndexBar
from app.sources.store import save_bars, save_index

DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=300)]


@pytest.fixture
def world(client, monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    registry.clear()
    caps = (CapabilitySpec("bars", "by_symbol", (), adjusted=True), CapabilitySpec("index", "whole", ()))
    registry.register(type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d",
                                                 "homepage": "h", "capabilities": caps})())  # fmt: skip
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('UP','Up',1)")
        bars = [Bar("UP", d, p := 100 + i * 0.5, p + 1, p - 1, p, 1000.0) for i, d in enumerate(DAYS)]
        save_bars("px", bars, c)
        save_index("px", [IndexBar(frames.INDEX_NAME, d, 1000.0) for d in DAYS], c)
        sid = c.execute("SELECT id FROM screens LIMIT 1").fetchone()["id"]
        c.execute("INSERT INTO screen_results(screen_id, symbol, as_of, values_json, first_seen) "
                  "VALUES (?,?,?,?,?)",
                  (sid, "UP", DAYS[-1], "{}", "2026-11-08"))  # fmt: skip
        c.execute("INSERT INTO positions(symbol, qty, entry_date, entry_price, stop, created_at) "
                  "VALUES ('UP', 10, '2026-01-05', 100, 90, 'x')")  # fmt: skip
        c.execute("INSERT INTO watchlist(symbol, added_at) VALUES ('UP','x')")
    frames.invalidate()
    yield
    registry.clear()
    frames.invalidate()


def add_alert(severity, created, key):
    with db.tx() as c:
        c.execute("INSERT INTO alerts(kind, message, severity, dedupe_key, created_at) "
                  "VALUES ('k','m',?,?,?)",
                  (severity, key, created))  # fmt: skip


def add_announcement(category, ts, headline):
    with db.tx() as c:
        c.execute("INSERT INTO announcements(source, symbol, ts, category, headline) VALUES ('s','UP',?,?,?)",
                  (ts, category, headline))  # fmt: skip


def test_shape_and_no_since_without_a_visit(world, client):
    add_alert("info", "2026-11-08T10:00:00+05:30", "a")
    add_alert("critical", "2026-11-07T10:00:00+05:30", "b")
    d = client.get("/api/dashboard").json()
    assert set(d) == {"shortlist", "alerts", "positions", "data", "since"}
    assert d["since"] is None
    assert [a["severity"] for a in d["alerts"]] == ["critical", "info"]  # critical first
    assert d["shortlist"][0]["symbol"] == "UP"
    p = d["positions"]
    assert p["open"] == 1 and p["invested"] == 1000 and p["open_risk"] == 100 and p["pnl"] > 0
    assert d["data"]["last_trading_date"] == DAYS[-1] and d["data"]["stale"] is False
    assert set(d["data"]) == {"last_trading_date", "stale", "updating", "checks_open"}


def test_stale_when_prices_are_old(world, client, monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 20))
    assert client.get("/api/dashboard").json()["data"]["stale"] is True


def test_since_filters_by_last_visit(world, client):
    add_alert("info", "2026-11-05T10:00:00+05:30", "old")
    add_alert("warn", "2026-11-08T10:00:00+05:30", "new")
    add_announcement("results", "2026-11-04T09:00:00", "old results")
    add_announcement("results", "2026-11-08T09:00:00", "new results")
    add_announcement("dividend", "2026-11-08T09:00:00", "dividend (not alerting)")
    db.set_setting("last_visit_at", "2026-11-06T18:00:00+05:30")
    s = client.get("/api/dashboard").json()["since"]
    assert [a["dedupe_key"] for a in s["alerts"]] == ["new"]
    assert [a["headline"] for a in s["announcements"]] == ["new results"]
    assert s["new_in_screens"][0]["symbols"] == ["UP"]
    # last bar is 2026-11-06, the visit day -> no move yet
    assert s["positions"] == [{"symbol": "UP", "change_pct_since_visit": 0.0}]
    db.set_setting("last_visit_at", "2026-11-02T18:00:00+05:30")
    moved = client.get("/api/dashboard").json()["since"]["positions"][0]["change_pct_since_visit"]
    assert moved > 0


def test_visit_updates_last_visit(world, client):
    assert db.get_setting("last_visit_at") is None
    r = client.post("/api/dashboard/visit").json()
    assert db.get_setting("last_visit_at") == r["last_visit_at"]
    assert client.get("/api/dashboard").json()["since"]["alerts"] == []
