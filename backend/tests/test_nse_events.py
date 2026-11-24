import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from app import config, db, timeutil
from app.analytics import calendar, frames, score
from app.sources import registry, store
from app.sources.base import Bar, BaseSource, CapabilitySpec, Event, SourceError
from app.sources.parsers.nse_events import parse_event_calendar
from app.sources.store import save_bars

FIXTURE = Path(__file__).parent / "fixtures" / "sources" / "nse_api" / "event_calendar.json"
TODAY = "2026-11-11"


def _seed_bars() -> None:
    registry.clear()
    registry.register(type(
        "raw", (BaseSource,),
        {"name": "raw", "label": "raw", "description": "d", "homepage": "h",
         "capabilities": (CapabilitySpec("bars", "by_symbol", (), adjusted=True),)},
    )())  # fmt: skip
    db.set_setting("source_priority", {"bars": ["raw"]})
    frames.invalidate()
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-10-01", periods=20)]
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','Aaa Ltd',1)")
        save_bars("raw", [Bar("AAA", d, 100, 102, 98, 100, 1000) for d in days], c)


def _entry_answers() -> dict:
    return {"thesis": "growth", "wrong_if": "below 90", "entry_price": 100, "stop": 95, "target": 110,
            "time_stop_weeks": 8, "risk_pct": 1, "read_announcements": True, "checked_results": True,
            "emotion": "calm"}  # fmt: skip


@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    monkeypatch.setattr(timeutil, "now", lambda: datetime(2026, 11, 11, 10, 0, tzinfo=config.TZ))
    db.init_db()


def _add(conn, symbol, date, purpose, source="s"):
    conn.execute(
        "INSERT INTO events(source, symbol, date, purpose, description, fetched_at) "
        "VALUES (?,?,?,?,NULL,'t')",
        (source, symbol, date, purpose),
    )


# ---- parser ----


def test_parser_fixture():
    import json

    events = parse_event_calendar(json.loads(FIXTURE.read_text()))
    assert len(events) == 9
    ace = next(e for e in events if e.symbol == "ACE")
    assert (ace.date, ace.purpose) == ("2026-11-12", "Financial Results")
    assert ace.description and ace.description.startswith("To consider and approve")
    assert any(e.symbol == "JMA" and e.purpose == "Buyback" for e in events)


def test_parser_skips_bad_rows_and_dedupes(caplog):
    items = [
        {"symbol": " ace ", "purpose": " Financial Results ", "bm_desc": " ", "date": "12-Nov-2026"},
        {"symbol": "ACE", "purpose": "Financial Results", "bm_desc": "later", "date": "12-Nov-2026"},
        {"symbol": "BAD", "purpose": "Financial Results", "date": "soon"},
        {"symbol": "", "purpose": "Financial Results", "date": "12-Nov-2026"},
        {"symbol": "NOP", "purpose": "", "date": "12-Nov-2026"},
    ]
    with caplog.at_level(logging.WARNING):
        out = parse_event_calendar(items)
    assert out == [Event("ACE", "2026-11-12", "Financial Results", "later")]
    assert sum("skipped 3" in r.message for r in caplog.records) == 1


def test_parser_rejects_non_list():
    with pytest.raises(SourceError):
        parse_event_calendar({"error": "x"})  # type: ignore[arg-type]


# ---- store ----


def test_save_events_replaces_future_rows_keeps_past():
    a = Event("AAA", "2026-11-20", "Financial Results")
    with db.tx() as c:
        batch = [a, Event("OLD", "2026-11-01", "Financial Results")]
        assert store.save("events", "s", batch, key="all", conn=c) == 2
        store.save_events("s", [a], c)
        assert c.execute("SELECT COUNT(*) FROM events WHERE symbol='AAA'").fetchone()[0] == 1
    with db.tx() as c:
        # a second save without AAA (rescheduled) removes it; the past OLD row stays
        store.save_events("s", [Event("BBB", "2026-11-25", "Financial Results")], c)
        rows = {r["symbol"] for r in c.execute("SELECT symbol FROM events")}
    assert rows == {"OLD", "BBB"}


# ---- next_results ----


def test_next_results():
    with db.tx() as c:
        _add(c, "AAA", "2026-11-30", "Financial Results")
        _add(c, "AAA", "2026-11-15", "Financial Results/Dividend", "other")
        _add(c, "AAA", "2026-11-12", "Buyback")
        _add(c, "AAA", "2026-11-01", "Financial Results")
        _add(c, "BBB", TODAY, "FINANCIAL RESULTS")
        _add(c, "CCC", "2026-12-01", "Bonus")
        got = calendar.next_results(c)
        only = calendar.next_results(c, ["BBB", "ZZZ"])
    assert got == {"AAA": {"date": "2026-11-15", "days": 4}, "BBB": {"date": TODAY, "days": 0}}
    assert only == {"BBB": {"date": TODAY, "days": 0}}


# ---- db and job registration ----


def test_fresh_db_has_events_and_version_8():
    conn = db.connect()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 9
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='events'").fetchone()
    conn.close()


def test_version_7_db_gains_events():
    conn = db.connect()
    conn.execute("DROP TABLE events")
    conn.execute("PRAGMA user_version=7")
    conn.close()
    db.init_db()
    with db.tx() as c:
        assert c.execute("SELECT name FROM sqlite_master WHERE name='events'").fetchone()
        assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_events_job_at_stage_3():
    from app.sources import jobs

    assert jobs.STAGES["events"] == (3, ())
    assert jobs.CAP_LABEL["events"] == "board meetings"
    from app.jobs import registry as jobs_registry
    from app.sources import registry
    from app.sources.adapters.nse_api import NseApi

    registry.clear()
    saved = dict(jobs_registry._JOBS)
    jobs_registry._JOBS.clear()
    try:
        registry.register(NseApi())
        jobs.register_source_jobs()
        job = jobs_registry.get("events.nse_api")
        assert job.stage == 3
    finally:
        jobs_registry._JOBS.clear()
        jobs_registry._JOBS.update(saved)


# ---- APIs ----


def test_symbol_detail_next_results(client):
    _seed_bars()
    assert client.get("/api/symbols/AAA").json()["next_results"] is None
    with db.tx() as c:
        _add(c, "AAA", "2026-11-14", "Financial Results")
    assert client.get("/api/symbols/AAA").json()["next_results"] == {"date": "2026-11-14", "days": 3}


def test_suggest_and_positions_next_results(client):
    _seed_bars()
    r =client.get("/api/positions/suggest", params={"symbol": "AAA"}).json()
    assert r["next_results"] is None
    with db.tx() as c:
        _add(c, "AAA", "2026-12-01", "Financial Results")
    r = client.get("/api/positions/suggest", params={"symbol": "AAA"}).json()
    assert r["next_results"] == {"date": "2026-12-01", "days": 20}
    pos = client.post("/api/positions", json={"symbol": "AAA", "qty": 10, "entry_date": "2026-10-20",
                                              "answers": _entry_answers()}).json()  # fmt: skip
    assert pos["next_results"] == {"date": "2026-12-01", "days": 20}
    listed = client.get("/api/positions").json()
    assert listed[0]["next_results"] == {"date": "2026-12-01", "days": 20}


def test_shortlist_next_results(client, monkeypatch):
    monkeypatch.setattr(score, "score_candidates", lambda conn=None: [{"symbol": "AAA"}, {"symbol": "BBB"}])
    with db.tx() as c:
        _add(c, "AAA", "2026-11-13", "Financial Results")
    got = client.get("/api/shortlist").json()
    assert got == [
        {"symbol": "AAA", "next_results": {"date": "2026-11-13", "days": 2}},
        {"symbol": "BBB", "next_results": None},
    ]
