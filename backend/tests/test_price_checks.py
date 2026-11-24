import pandas as pd
import pytest

from app import db
from app.analytics import frames
from app.jobs import runner
from app.jobs.defs.price_checks import (
    _close_resolved,
    find_adjustment_jumps,
    find_gaps,
    find_mismatches,
)
from app.sources import registry
from app.sources.base import Action, Bar, BaseSource, CapabilitySpec
from app.sources.store import save_actions, save_bars


def series(values, start="2026-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def test_missing_bonus_gives_one_mismatch_with_half_factor():
    other = series([50.0] * 30)
    primary = series([100.0] * 10 + [50.0] * 20)  # unadjusted: the 1:1 bonus was never applied
    out = find_mismatches(primary, other)
    assert len(out) == 1
    m = out[0]
    assert m["date"] == "2026-01-01" and m["end"] == "2026-01-14"
    assert m["suggested_factor"] == pytest.approx(0.5) and m["ex_date"] == "2026-01-15"


def test_short_streak_and_small_difference_ignored():
    other = series([50.0] * 20)
    assert find_mismatches(series([100.0] * 3 + [50.0] * 17), other) == []  # only 3 days
    assert find_mismatches(series([50.5] * 20), other) == []  # 1% off


def test_gap_flagged_unless_action_nearby():
    s = series([100.0] * 10 + [60.0] * 10)  # -40% on day 11 (2026-01-15)
    assert [g["date"] for g in find_gaps(s, [])] == ["2026-01-15"]
    assert find_gaps(s, ["2026-01-13"]) == []  # action 2 days away
    assert len(find_gaps(s, ["2026-01-05"])) == 1  # far away: still flagged


def make(name, adjusted):
    specs = (
        CapabilitySpec("bars", "by_symbol", (), adjusted=adjusted),
        CapabilitySpec("actions", "by_symbol", ()),
    )
    return type(
        name, (BaseSource,),
        {"name": name, "label": name, "description": "d", "homepage": "h", "capabilities": specs},
    )()  # fmt: skip


@pytest.fixture
def seeded(client):
    registry.clear()
    registry.register(make("raw", False))
    registry.register(make("adj", True))
    db.set_setting("source_priority", {"bars": ["raw", "adj"], "actions": ["raw", "adj"]})
    days = [d.date().isoformat() for d in pd.bdate_range("2026-01-01", periods=30)]
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','Alpha',1)")
        raw = [Bar("AAA", d, *([100.0 if i < 10 else 50.0] * 4), 10) for i, d in enumerate(days)]
        save_bars("raw", raw, c)
        save_bars("adj", [Bar("AAA", d, *([50.0] * 4), 10) for d in days], c)
    frames.invalidate()
    yield
    registry.clear()
    frames.invalidate()


def run_job():
    rid = runner.enqueue("price_checks")
    assert runner.run_one() == rid
    with db.tx() as c:
        return dict(c.execute("SELECT * FROM job_runs WHERE id=?", (rid,)).fetchone())


def test_job_apply_factor_flow(client, seeded):
    r = run_job()
    assert r["status"] == "done" and r["ok"] == 1
    checks = client.get("/api/data/checks").json()
    # the unadjusted drop is also an unexplained -50% jump, so two checks are raised
    assert sorted(c["kind"] for c in checks) == ["mismatch", "unexplained_gap"]
    ck = next(c for c in checks if c["kind"] == "mismatch")
    assert ck["kind"] == "mismatch" and ck["primary_source"] == "raw" and ck["other_source"] == "adj"
    assert ck["detail"]["suggested_factor"] == pytest.approx(0.5)
    assert client.get("/api/data/health").json()["checks_open"] == 2

    done = client.post(f"/api/data/checks/{ck['id']}", json={"action": "apply_factor"}).json()
    assert done["status"] == "fixed"
    with db.tx() as c:
        row = c.execute("SELECT * FROM manual_adjustments WHERE symbol='AAA'").fetchone()
    assert (row["ex_date"], row["factor"]) == ("2026-01-15", 0.5)
    assert (frames.load_frame("AAA")["close"] == 50.0).all()

    run_job()  # nothing new: the fixed check isn't reopened
    assert client.get("/api/data/checks").json() == []
    assert len(client.get("/api/data/checks?status=fixed").json()) == 2  # the jump closes with the fix


def test_ignored_check_stays_ignored(client, seeded):
    run_job()
    ck = next(c for c in client.get("/api/data/checks").json() if c["kind"] == "mismatch")
    res = client.post(f"/api/data/checks/{ck['id']}", json={"action": "ignore"})
    assert res.json()["status"] == "ignored"
    run_job()
    assert [c["kind"] for c in client.get("/api/data/checks").json()] == ["unexplained_gap"]
    assert len(client.get("/api/data/checks?status=ignored").json()) == 1


def test_checks_close_when_the_missing_action_arrives(client, seeded):
    run_job()
    assert len(client.get("/api/data/checks").json()) == 2
    with db.tx() as c:  # the split turns up later from a source
        save_actions("raw", [Action("AAA", "2026-01-15", "Split 2:1", "split", 0.5)], c)
    frames.invalidate()
    run_job()
    assert client.get("/api/data/checks").json() == []
    assert len(client.get("/api/data/checks?status=fixed").json()) == 2
    assert client.get("/api/data/health").json()["checks_open"] == 0


def test_gap_check_for_single_source(client):
    registry.clear()
    registry.register(make("raw", False))
    days = [d.date().isoformat() for d in pd.bdate_range("2026-01-01", periods=20)]
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','Alpha',1)")
        raw = [Bar("AAA", d, *([100.0 if i < 10 else 55.0] * 4), 1) for i, d in enumerate(days)]
        save_bars("raw", raw, c)
    frames.invalidate()
    run_job()
    ck = client.get("/api/data/checks").json()
    assert [(x["kind"], x["date"]) for x in ck] == [("unexplained_gap", days[10])]
    # a gap needs an explicit factor to apply
    assert client.post(f"/api/data/checks/{ck[0]['id']}", json={"action": "apply_factor"}).status_code == 400
    ok = client.post(f"/api/data/checks/{ck[0]['id']}", json={"action": "apply_factor", "factor": 0.55})
    assert ok.json()["status"] == "fixed"
    registry.clear()
    frames.invalidate()


def test_manual_adjustment_unknown_check_and_validation(client):
    assert client.post("/api/data/checks/999", json={"action": "ignore"}).status_code == 404
    url = "/api/data/manual-adjustment"
    bad = client.post(url, json={"symbol": "x", "ex_date": "01/02/2026", "factor": 0.5})
    assert bad.status_code == 400
    ok = client.post(url, json={"symbol": "x", "ex_date": "2026-02-01", "factor": 0.5})
    assert ok.json() == {"symbol": "X", "ex_date": "2026-02-01", "factor": 0.5, "note": None}
    assert client.post(url, json={"symbol": "x", "ex_date": "2026-02-01", "factor": 0}).status_code == 422


def test_health_and_unparsed_shapes(client):
    registry.clear()
    registry.register(make("raw", False))
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','Alpha',1)")
        save_bars("raw", [Bar("AAA", "2026-11-06", 1, 1, 1, 1, 1)], c)
        save_actions("raw", [Action("AAA", "2026-10-01", "Bonus issue", "unparsed", None)], c)
    h = client.get("/api/data/health").json()
    assert set(h) == {
        "last_trading_date", "symbols", "universe", "checks_open", "unparsed_actions",
        "bars", "fundamentals", "quarters", "news",
    }  # fmt: skip
    assert h["last_trading_date"] == "2026-11-06" and h["universe"] == 1 and h["unparsed_actions"] == 1
    assert h["bars"] == {"raw": {"symbols": 1, "last_date": "2026-11-06"}}
    assert h["fundamentals"] == {"merged": 0} and h["quarters"] == {}
    assert h["news"] == {"announcements_7d": 0, "news_7d": 0}
    assert client.get("/api/data/unparsed-actions").json() == [
        {"source": "raw", "symbol": "AAA", "ex_date": "2026-10-01", "subject": "Bonus issue"}
    ]
    registry.clear()


def long_series(values):
    idx = pd.bdate_range(end="2026-11-10", periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def test_full_window_finds_old_missed_bonus():
    other = long_series([50.0] * 1000)
    primary = long_series([100.0] * 300 + [50.0] * 700)  # bonus missed ~700 business days back
    assert find_mismatches(primary, other) == []
    out = find_mismatches(primary, other, window=None)
    assert len(out) == 1 and out[0]["suggested_factor"] == pytest.approx(0.5)


def test_full_window_finds_old_gap():
    s = long_series([100.0] * 300 + [60.0] * 700)
    assert find_gaps(s, []) == []
    assert len(find_gaps(s, [], window=None)) == 1


def test_close_resolved_window(client):
    s = long_series([100.0] * 1000)
    old = s.index[100].date().isoformat()
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','Alpha',1)")
        c.execute(
            "INSERT INTO price_checks(symbol, date, kind, created_at) VALUES ('AAA',?,'mismatch','x')",
            (old,),
        )
        assert _close_resolved(c, "AAA", s, set()) == 0
        assert _close_resolved(c, "AAA", s, set(), window=None) == 1
        row = c.execute("SELECT status FROM price_checks WHERE symbol='AAA'").fetchone()
    assert row["status"] == "fixed"


def test_both_jobs_registered():
    from app.jobs import registry as jobs

    full = jobs.get("price_checks_full")
    assert full.title == "Price checks (full history)" and full.stage == 4
    assert full.default_schedule == {"kind": "weekly", "weekday": 6, "at_time": "11:00"}
    assert jobs.get("price_checks").default_schedule["kind"] == "daily"


def raw_frame(values, start="2026-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    cols = {k: values for k in ("open", "high", "low", "close")}
    return pd.DataFrame({**cols, "volume": 10.0}, index=idx)


def adjusted(raw, factors):
    from app.analytics import adjust

    return adjust.apply_factors(raw, factors)


EX = "2026-01-15"  # 11th bar of raw_frame


def test_jump_check_no_row_when_raw_halves_with_half_factor():
    f = [(EX, 0.5)]
    raw = raw_frame([100.0] * 10 + [50.0] * 10)
    assert find_adjustment_jumps(adjusted(raw, f), f) == []


def test_jump_check_flat_raw_with_half_factor_suggests_one():
    f = [(EX, 0.5)]
    raw = raw_frame([100.0] * 20)
    (row,) = find_adjustment_jumps(adjusted(raw, f), f)
    assert row["date"] == EX and row["applied_factor"] == 0.5
    assert row["suggested_factor"] == pytest.approx(1.0) and row["open_move_pct"] == pytest.approx(100.0)


def test_jump_check_big_step_down_suggests_one_sixth():
    f = [(EX, 0.5)]
    raw = raw_frame([600.0] * 10 + [100.0] * 10)
    (row,) = find_adjustment_jumps(adjusted(raw, f), f)
    assert row["suggested_factor"] == pytest.approx(0.1667) and row["open_move_pct"] < 0


def test_jump_check_needs_both_open_and_close():
    f = [(EX, 1.0)]
    raw = raw_frame([100.0] * 20)
    raw.loc[pd.Timestamp(EX), ["open", "high", "low"]] = 120.0  # open +20%, close flat
    assert find_adjustment_jumps(raw, f) == []
    raw.loc[pd.Timestamp(EX), "close"] = 105.0  # close only +5%
    assert find_adjustment_jumps(raw, f) == []


def test_jump_check_window():
    f = [(EX, 0.5)]
    adj = adjusted(raw_frame([100.0] * 40), f)  # ex-date is bar 11 of 40
    assert find_adjustment_jumps(adj, f, window=5) == []
    assert len(find_adjustment_jumps(adj, f, window=None)) == 1


@pytest.fixture
def jump_db(client):
    registry.clear()
    registry.register(make("raw", False))
    db.set_setting("source_priority", {"bars": ["raw"], "actions": ["raw"]})
    days = [d.date().isoformat() for d in pd.bdate_range("2026-01-01", periods=30)]
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','Alpha',1)")
        save_bars("raw", [Bar("AAA", d, 100.0, 100.0, 100.0, 100.0, 10) for d in days], c)
        save_actions("raw", [Action("AAA", EX, "Split 2:1", "split", 0.5)], c)  # never happened
    frames.invalidate()
    yield
    registry.clear()
    frames.invalidate()


def test_jump_row_apply_factor_and_close(client, jump_db):
    run_job()
    checks = client.get("/api/data/checks").json()
    (ck,) = [c for c in checks if c["kind"] == "adjustment_jump"]
    assert ck["date"] == EX and ck["detail"]["suggested_factor"] == pytest.approx(1.0)
    with db.tx() as c:  # an open gap row near the ex-date closes with the fix
        c.execute(
            "INSERT INTO price_checks(symbol, date, kind, status) "
            "VALUES ('AAA','2026-01-16','unexplained_gap','open')"
        )
    done = client.post(f"/api/data/checks/{ck['id']}", json={"action": "apply_factor"}).json()
    assert done["status"] == "fixed"
    with db.tx() as c:
        row = c.execute("SELECT ex_date, factor FROM manual_adjustments WHERE symbol='AAA'").fetchone()
        gap = c.execute("SELECT status FROM price_checks WHERE kind='unexplained_gap'").fetchone()
    assert (row["ex_date"], row["factor"]) == (EX, 1.0) and gap["status"] == "fixed"


def test_open_jump_row_closes_once_adjustment_removes_it(client, jump_db):
    run_job()
    with db.tx() as c:
        c.execute("INSERT INTO manual_adjustments(symbol, ex_date, factor) VALUES ('AAA', ?, 1.0)", (EX,))
    frames.invalidate()
    run_job()
    assert [c for c in client.get("/api/data/checks").json() if c["kind"] == "adjustment_jump"] == []
    fixed = client.get("/api/data/checks?status=fixed").json()
    assert [c["kind"] for c in fixed] == ["adjustment_jump"]
