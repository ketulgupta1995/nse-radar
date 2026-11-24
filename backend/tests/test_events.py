import json

import pandas as pd
import pytest

from app import db
from app.analytics import adjust, events, frames
from app.sources import registry
from app.sources.base import Action, Bar, BaseSource, CapabilitySpec
from app.sources.store import save_actions, save_bars

DAYS = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-09-01", periods=30)]
EX = DAYS[15]


def make(name, adjusted):
    specs = (
        CapabilitySpec("bars", "by_symbol", (), adjusted=adjusted),
        CapabilitySpec("actions", "by_symbol", ()),
    )
    return type(
        name, (BaseSource,),
        {"name": name, "label": name, "description": "d", "homepage": "h", "capabilities": specs},
    )()  # fmt: skip


@pytest.fixture(autouse=True)
def _setup():
    db.init_db()
    registry.clear()
    registry.register(make("raw", False))
    registry.register(make("adj", True))
    db.set_setting("source_priority", {"bars": ["raw", "adj"], "actions": ["raw", "adj"]})
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','Alpha',1)")
    frames.invalidate()
    yield
    registry.clear()
    frames.invalidate()


def put_bars(source, fn, days=DAYS, symbol="AAA"):
    """fn(i) -> (open, close)."""
    bars = []
    for i, d in enumerate(days):
        o, c = fn(i)
        bars.append(Bar(symbol, d, o, max(o, c), min(o, c), c, 1000.0))
    with db.tx() as c:
        save_bars(source, bars, c)


def put_action(kind, ex=EX, source="raw", symbol="AAA"):
    with db.tx() as c:
        save_actions(source, [Action(symbol, ex, f"{kind} event", kind, None)], c)


def compute(kind="demerger", ex=EX):
    with db.tx() as c:
        return events.compute_event_factor("AAA", ex, kind, c)


def test_demerger_reference_method_and_adjustment():
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else (60.0, 60.0))
    put_bars("adj", lambda i: (60.0, 60.0))
    put_action("demerger")
    factor, method, detail = compute()
    assert method == "reference" and factor == pytest.approx(0.6)
    assert detail["reference"] == "adj" and detail["n_before"] == 10 and detail["n_after"] == 10
    with db.tx() as c:
        assert events.refresh_event_factors(c) == 1
        assert adjust.adjustment_factors("AAA", c) == [(EX, pytest.approx(0.6))]
        assert adjust.adjustment_factors("AAA", c, include_events=False) == []
    df, _ = adjust.adjusted_ohlcv("AAA")
    assert df["close"].pct_change().abs().max() < 1e-9


def test_demerger_open_method_and_none():
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else (40.0, 40.0))
    factor, method, detail = compute()
    assert (method, factor) == ("open", pytest.approx(0.4))
    assert detail["open"] == 40.0 and detail["prev_close"] == 100.0
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else (99.0, 99.0))
    assert compute()[:2] == (None, "none")


def test_rights_never_uses_open():
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else (40.0, 40.0))
    assert compute("rights")[:2] == (None, "none")


def test_reference_rejections():
    put_bars("raw", lambda i: (100.0, 100.0))
    put_bars("adj", lambda i: (50.0, 50.0) if i >= 15 else (100.0, 100.0))  # step 2 > 1
    assert compute("rights")[:2] == (None, "none")
    # too few dates on one side
    ex = DAYS[3]
    put_bars("adj", lambda i: (60.0, 60.0))
    assert compute("rights", ex)[:2] == (None, "none")


def test_manual_adjustment_replaces_event_factor():
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else (40.0, 40.0))
    put_action("demerger")
    with db.tx() as c:
        events.refresh_event_factors(c)
        c.execute(
            "INSERT INTO manual_adjustments(symbol, ex_date, factor) VALUES ('AAA', ?, 0.5)", (DAYS[14],)
        )
        assert adjust.adjustment_factors("AAA", c) == [(DAYS[14], 0.5)]


def test_refresh_replaces_and_drops_and_dedupes():
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else (40.0, 40.0))
    put_action("demerger")
    put_action("demerger", DAYS[16], source="adj")  # within ±2 days: same event
    put_action("rights", DAYS[5])
    with db.tx() as c:
        assert events.refresh_event_factors(c) == 2
        rows = c.execute("SELECT kind, ex_date, method FROM event_factors ORDER BY kind").fetchall()
        assert [(r["kind"], r["ex_date"], r["method"]) for r in rows] == [
            ("demerger", EX, "open"),
            ("rights", DAYS[5], "none"),
        ]
        c.execute("DELETE FROM corp_actions WHERE kind='rights'")
        assert events.refresh_event_factors(c, ["AAA"]) == 1
        assert c.execute("SELECT COUNT(*) FROM event_factors").fetchone()[0] == 1


def test_job_registered_and_followups():
    from app.jobs import registry as jobs
    from app.jobs.defs import event_factors  # noqa: F401
    from app.sources.jobs import STAGES

    j = jobs.get("event_factors")
    assert j.stage == 3 and j.default_schedule == {"kind": "manual"}
    for cap in ("bars", "actions"):
        f = STAGES[cap][1]
        assert f.index("event_factors") < f.index("price_checks")


def test_job_message():
    from app.jobs import registry as jobs
    from app.jobs.defs import event_factors  # noqa: F401

    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else (40.0, 40.0))
    put_action("demerger")
    put_action("rights", DAYS[5])
    msg = jobs.get("event_factors").fn(None)
    assert msg == "2 events: 0 adjusted (reference), 1 adjusted (open), 0 adjusted (close), 1 not adjusted"


def adj_for(after):
    """Reference series giving a primary/reference step of 0.6 when the primary falls to `after`."""
    return lambda i: (100.0, 100.0) if i < 15 else (after / 0.6, after / 0.6)


def test_guard_rejects_bad_reference_uses_open():
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else (80.0, 80.0))
    put_bars("adj", adj_for(80.0))
    factor, method, detail = compute()
    assert method == "open" and factor == pytest.approx(0.8)
    assert detail["rejected"] == "reference" and detail["reference"] == "adj"
    assert detail["open_move"] == pytest.approx(0.3333) and "before" in detail


def test_guard_accepts_consistent_reference():
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else (62.0, 62.0))
    put_bars("adj", adj_for(62.0))
    factor, method, detail = compute()
    assert method == "reference" and factor == pytest.approx(0.6) and "rejected" not in detail


def test_guard_falls_through_to_close():
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else ((90.0, 17.0) if i == 15 else (60.0, 60.0)))
    put_bars("adj", lambda i: (60.0, 60.0))
    factor, method, detail = compute()
    assert method == "close" and factor == pytest.approx(0.17)
    assert detail["rejected"] == "reference" and detail["close"] == 17.0


def test_close_not_used_for_small_demerger():
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else ((98.4, 95.0) if i == 15 else (95.0, 95.0)))
    factor, method, _ = compute()
    assert method == "none" and factor is None


def test_rights_skip_guard():
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else (80.0, 80.0))
    put_bars("adj", adj_for(80.0))
    factor, method, _ = compute("rights")
    assert method == "reference" and factor == pytest.approx(0.6)


def test_api_shape(client):
    put_bars("raw", lambda i: (100.0, 100.0) if i < 15 else (40.0, 40.0))
    put_action("demerger")
    put_action("rights", DAYS[5])
    with db.tx() as c:
        events.refresh_event_factors(c)
    r = client.get("/api/data/event-factors").json()
    assert [x["ex_date"] for x in r] == [EX, DAYS[5]]
    assert set(r[0]) == {"symbol", "ex_date", "kind", "factor", "method", "detail"}
    assert r[0]["method"] == "open" and r[1]["factor"] is None
    assert isinstance(r[0]["detail"], dict) and json.dumps(r[0]["detail"])
