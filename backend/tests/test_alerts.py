from datetime import date, datetime

import pandas as pd
import pytest

from app import db, timeutil
from app.alerts import base
from app.alerts.base import AlertDraft, AlertScanner
from app.alerts.scanners import announcements, data_stale, positions, screens
from app.analytics import frames
from app.jobs import runner
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec
from app.sources.store import save_announcements, save_bars

DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=30)]
NOW = datetime.fromisoformat("2026-11-09T10:00:00+05:30")


def source():
    caps = (CapabilitySpec("bars", "by_symbol", (), adjusted=True),)
    return type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d", "homepage": "h",
                                      "capabilities": caps})()  # fmt: skip


def bars(symbol, close=100.0, overrides=None):
    """Flat bars (high = close + 1, low = close - 1) with per-index (high, low) overrides."""
    out = []
    for i, d in enumerate(DAYS):
        high, low = (overrides or {}).get(i, (close + 1, close - 1))
        out.append(Bar(symbol, d, close, high, low, close, 1000.0))
    return out


def add_position(c, symbol, **kw):
    row = {
        "symbol": symbol, "qty": 10, "entry_date": "2026-10-01", "entry_price": 100.0, "stop": None,
        "target": None, "time_stop_date": None, "created_at": "2026-10-01T09:00:00+05:30",
    } | kw  # fmt: skip
    cols = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    return c.execute(f"INSERT INTO positions({cols}) VALUES ({marks})", row).lastrowid


@pytest.fixture
def world(client, monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    registry.clear()
    registry.register(source())
    with db.tx() as c:
        for s in ("AAA", "BBB", "CCC", "DDD", "EEE"):
            c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES (?,?,1)", (s, s))
            save_bars("px", bars(s, overrides={26: (101, 90)} if s == "AAA" else
                                 {27: (110, 99)} if s == "CCC" else None), c)  # fmt: skip
    frames.invalidate()
    yield
    registry.clear()
    frames.invalidate()


def read(fn, now=NOW):
    conn = db.connect()
    try:
        return fn(conn, now)
    finally:
        conn.close()


def test_stop_hit_names_the_first_hit_day_even_after_recovery(world):
    with db.tx() as c:
        pid = add_position(c, "AAA", stop=95.0)
    drafts = read(positions.stop_hit)
    assert len(drafts) == 1
    d = drafts[0]
    assert d.dedupe_key == f"stop_hit:{pid}" and d.severity == "critical" and d.link == "/positions"
    day = DAYS[26]  # 3 bars ago; the price has since recovered to 100
    assert f"{pd.Timestamp(day):%a} {pd.Timestamp(day).day} {pd.Timestamp(day):%b}" in d.message
    assert "low ₹90" in d.message and "₹95" in d.message and d.symbol == "AAA"


def test_stop_not_hit_when_low_stays_above(world):
    with db.tx() as c:
        add_position(c, "BBB", stop=95.0)
    assert read(positions.stop_hit) == []


def test_entry_day_bar_does_not_count(world):
    with db.tx() as c:
        add_position(c, "AAA", stop=95.0, entry_date=DAYS[26])  # the crash bar is the entry day itself
    assert read(positions.stop_hit) == []


def test_stop_near_within_three_percent_above(world):
    with db.tx() as c:
        near = add_position(c, "BBB", stop=98.0)  # close 100 is 2.0% above
        add_position(c, "DDD", stop=90.0)  # 11% above: not near
        add_position(c, "EEE", stop=100.5)  # close below the stop: that's a hit, not "near"
    drafts = read(positions.stop_near)
    assert [d.dedupe_key for d in drafts] == [f"stop_near:{near}:{DAYS[-1]}"]
    assert drafts[0].message == "BBB closed at ₹100, 2.0% above your stop ₹98"
    assert drafts[0].severity == "warn"


def test_target_hit(world):
    with db.tx() as c:
        pid = add_position(c, "CCC", target=105.0)
        add_position(c, "BBB", target=130.0)
    drafts = read(positions.target_hit)
    assert [d.dedupe_key for d in drafts] == [f"target_hit:{pid}"]
    assert "hit your target ₹105" in drafts[0].message and "high ₹110" in drafts[0].message
    assert drafts[0].severity == "info"


def test_time_stop(world):
    with db.tx() as c:
        due = add_position(c, "DDD", time_stop_date="2026-11-01")
        add_position(c, "EEE", time_stop_date="2026-12-01")
        closed = add_position(c, "BBB", time_stop_date="2026-10-01")
        c.execute("UPDATE positions SET status='closed' WHERE id=?", (closed,))
    drafts = read(positions.time_stop)
    assert [d.dedupe_key for d in drafts] == [f"time_stop:{due}"]
    assert read(positions.time_stop, datetime.fromisoformat("2026-11-01T09:00:00+05:30"))[0].symbol == "DDD"


def test_announcement_scanner_uses_category_flags_and_follow_date(world):
    with db.tx() as c:
        c.execute("INSERT INTO watchlist(symbol, added_at) VALUES ('AAA', '2026-11-01T10:00:00+05:30')")
        add_position(c, "BBB", created_at="2026-10-20T10:00:00+05:30")
        mk = lambda sym, ts, head, body="": base_ann(sym, ts, head, body)  # noqa: E731
        save_announcements("nse_api", [
            mk("AAA", "2026-10-30T10:00:00+05:30", "Old pledge", "pledge of shares"),  # before it was watched
            mk("AAA", "2026-11-03T10:00:00+05:30", "Pledge update", "creation of pledge"),
            mk("AAA", "2026-11-04T10:00:00+05:30", "Dividend", "interim dividend"),  # category without alert
            mk("AAA", "2026-11-04T11:00:00+05:30", "Newspaper", "newspaper publication"),  # routine
            mk("BBB", "2026-11-05T10:00:00+05:30", "Results", "financial result for the quarter"),
            mk("ZZZ", "2026-11-05T10:00:00+05:30", "Not followed", "pledge"),
        ], c)  # fmt: skip
    drafts = {d.symbol: d for d in read(announcements.scan)}
    assert set(drafts) == {"AAA", "BBB"}
    assert drafts["AAA"].severity == "warn" and drafts["AAA"].message == (
        "AAA: new announcement (pledge): Pledge update")  # fmt: skip
    assert drafts["BBB"].severity == "info" and drafts["BBB"].link == "/stock/BBB"
    assert drafts["AAA"].dedupe_key.startswith("ann:")


def base_ann(sym, ts, head, body):
    from app.sources.base import Announcement

    return Announcement(sym, ts, head, body)


def test_screen_new(world):
    with db.tx() as c:
        c.execute("INSERT INTO screens(name, rule, created_at, updated_at) VALUES ('Mine','{}','x','x')")
        sid = c.execute("SELECT id FROM screens WHERE name='Mine'").fetchone()[0]
        for sym, seen in (("AAA", "2026-11-09"), ("BBB", "2026-11-09"), ("CCC", "2026-11-01")):
            c.execute("INSERT INTO screen_results VALUES (?,?,?,?,?)", (sid, sym, "2026-11-06", "{}", seen))
    drafts = [d for d in read(screens.scan) if "Mine" in d.message]
    assert len(drafts) == 1
    d = drafts[0]
    assert d.message == "2 new stocks in 'Mine': AAA, BBB"
    assert d.dedupe_key == f"screen_new:{sid}:2026-11-09" and d.link == f"/screener?screen={sid}"
    next_day = datetime.fromisoformat("2026-11-10T10:00:00+05:30")
    assert read(screens.scan, next_day) == []  # nothing is new on the next day


def test_data_stale_and_suppressed_while_updating(world, monkeypatch):
    late = datetime.fromisoformat("2026-11-12T10:00:00+05:30")  # 4 weekdays after Fri 6 Nov
    drafts = read(data_stale.scan, late)
    assert len(drafts) == 1 and drafts[0].dedupe_key == "stale:2026-11-06" and drafts[0].severity == "warn"
    day = lambda d: datetime.fromisoformat(f"2026-11-{d}T10:00:00+05:30")  # noqa: E731
    assert read(data_stale.scan, day("09")) == []  # 1 weekday behind
    assert read(data_stale.scan, day("10")) == []  # 2 weekdays: still fine
    assert len(read(data_stale.scan, day("11"))) == 1  # 3 weekdays: stale
    monkeypatch.setattr(data_stale.runner, "status", lambda: {"updating": True})
    assert read(data_stale.scan, late) == []


def test_weekdays_behind_helper():
    assert data_stale.weekdays_behind(date(2026, 11, 6), date(2026, 11, 9)) == 1
    assert data_stale.weekdays_behind(date(2026, 11, 6), date(2026, 11, 8)) == 0
    assert data_stale.weekdays_behind(date(2026, 11, 6), date(2026, 11, 12)) == 4


def run_scan():
    rid = runner.enqueue("alerts_scan")
    assert runner.run_one() == rid
    with db.tx() as c:
        run = dict(c.execute("SELECT * FROM job_runs WHERE id=?", (rid,)).fetchone())
        rows = c.execute("SELECT key, status FROM job_items WHERE run_id=?", (rid,))
        items = {r["key"]: r["status"] for r in rows}
    return run, items


def test_job_inserts_without_duplicates_and_survives_a_failing_scanner(world):
    def boom(conn, now):
        raise RuntimeError("kaput")

    base.register(AlertScanner("boom", "Broken", boom))
    try:
        with db.tx() as c:
            add_position(c, "AAA", stop=95.0)
        run, items = run_scan()
        assert run["status"] == "done" and items["boom"] == "failed" and items["stop_hit"] == "ok"
        with db.tx() as c:
            n = c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        assert n >= 1
        run_scan()  # nothing new the second time
        with db.tx() as c:
            assert c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == n
    finally:
        base.unregister("boom")


def test_api_count_seen_kinds_and_filters(world, client):
    with db.tx() as c:
        a = db.insert_alert("stop_hit", "one", dedupe_key="k1", severity="critical", conn=c)
        db.insert_alert("time_stop", "two", dedupe_key="k2", conn=c)
        db.insert_alert("time_stop", "three", dedupe_key="k3", conn=c)
        assert a
    assert client.get("/api/alerts/count").json() == {"unseen": 3}
    allrows = client.get("/api/alerts").json()
    assert [r["message"] for r in allrows] == ["three", "two", "one"]
    assert [r["message"] for r in client.get("/api/alerts?kind=stop_hit").json()] == ["one"]
    assert len(client.get("/api/alerts?limit=2").json()) == 2

    first = allrows[2]["id"]
    assert client.post("/api/alerts/seen", json={"ids": [first]}).json() == {"marked": 1}
    assert client.get("/api/alerts/count").json() == {"unseen": 2}
    assert len(client.get("/api/alerts?unseen=1").json()) == 2
    assert client.post("/api/alerts/seen", json={"ids": [first]}).json() == {"marked": 0}  # already seen
    assert client.post("/api/alerts/seen").json() == {"marked": 2}
    assert client.get("/api/alerts/count").json() == {"unseen": 0}
    assert len(client.get("/api/alerts").json()) == 3  # seen alerts are kept

    kinds = {k["kind"] for k in client.get("/api/alerts/kinds").json()}
    assert {"stop_near", "stop_hit", "target_hit", "time_stop", "announcement", "screen_new",
            "data_stale", "job_refused"} <= kinds  # fmt: skip


def test_scanner_registry_rejects_duplicates():
    s = AlertScanner("dup_test", "x", lambda c, n: [AlertDraft("dup_test", "m", "k")])
    base.register(s)
    try:
        with pytest.raises(ValueError):
            base.register(s)
    finally:
        base.unregister("dup_test")
