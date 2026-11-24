import pandas as pd
from test_alerts import add_position, read, world  # noqa: F401

from app import db
from app.alerts.scanners import regime, results_due
from app.analytics import frames


def _events(c, rows):
    for sym, d in rows:
        c.execute(
            "INSERT INTO events(source, symbol, date, purpose, fetched_at) "
            "VALUES ('x', ?, ?, 'Financial Results', '2026-11-06T09:00:00+05:30')",
            (sym, d),
        )


def _watch(c, sym):
    c.execute("INSERT INTO watchlist(symbol, added_at) VALUES (?, '2026-10-01T09:00:00+05:30')", (sym,))


def test_results_due(world):  # noqa: F811
    with db.tx() as c:
        add_position(c, "AAA")
        _watch(c, "BBB")
        _watch(c, "DDD")
        _events(c, [("AAA", "2026-11-12"), ("BBB", "2026-11-10"), ("CCC", "2026-11-11"),
                    ("DDD", "2026-11-19")])  # fmt: skip
    by = {d.symbol: d for d in read(results_due.scan)}
    assert set(by) == {"AAA", "BBB"}  # CCC is not followed, DDD is 10 days away
    a = by["AAA"]
    assert a.severity == "warn" and a.dedupe_key == "results_due:AAA:2026-11-12" and a.link == "/stock/AAA"
    assert a.message == ("AAA reports results on Thu 12 Nov (3 days). "
                         "Decide before then whether to hold through it.")  # fmt: skip
    assert by["BBB"].severity == "info"
    assert by["BBB"].message == "BBB reports results on Tue 10 Nov (tomorrow)."


def test_results_due_today(world):  # noqa: F811
    with db.tx() as c:
        _watch(c, "EEE")
        _events(c, [("EEE", "2026-11-09")])
    assert [d.message for d in read(results_due.scan)] == ["EEE reports results on Mon 9 Nov (today)."]


def _flat_then(n, tail):
    """n bars at 100 followed by `tail` values, ending 2026-11-06."""
    vals = [100.0] * n + list(tail)
    return pd.Series(vals, index=pd.bdate_range(end="2026-11-06", periods=len(vals)), dtype=float)


def patch(monkeypatch, bench, breadth=None):
    nan = pd.Series([float("nan")] * 5, index=pd.bdate_range(end="2026-11-06", periods=5))
    monkeypatch.setattr(frames, "load_benchmark", lambda start=None: bench)
    monkeypatch.setattr(frames, "load_breadth", lambda n: nan if breadth is None else breadth)


def test_regime_recent_cross_down(world, monkeypatch):  # noqa: F811
    patch(monkeypatch, _flat_then(257, [80.0] * 3))
    drafts = read(regime.scan)
    assert len(drafts) == 1
    d = drafts[0]
    assert d.severity == "warn" and d.symbol is None and d.link == "/"
    assert d.dedupe_key.startswith("regime:index:2026-")
    assert "closed below its 200-day average" in d.message


def test_regime_old_cross_and_short_history(world, monkeypatch):  # noqa: F811
    patch(monkeypatch, _flat_then(245, [80.0] * 15))
    assert read(regime.scan) == []
    patch(monkeypatch, _flat_then(147, [80.0] * 3))
    assert read(regime.scan) == []


def test_regime_latest_of_two_crossings(world, monkeypatch):  # noqa: F811
    s = _flat_then(252, [60.0] * 4 + [100.0] * 4)  # down 8 bars ago, back up 4 bars ago
    s.iloc[-4:] = [150.0] * 4
    patch(monkeypatch, s)
    drafts = read(regime.scan)
    assert len(drafts) == 1 and drafts[0].severity == "info"
    assert drafts[0].dedupe_key == f"regime:index:{s.index[-4].date().isoformat()}"


def test_regime_breadth(world, monkeypatch):  # noqa: F811
    idx = pd.bdate_range(end="2026-11-06", periods=30)
    flat = _flat_then(100, [])
    patch(monkeypatch, flat, pd.Series([60.0] * 27 + [40.0] * 3, index=idx))
    drafts = read(regime.scan)
    assert len(drafts) == 1
    assert drafts[0].message.startswith("Only 40% of stocks are above") and drafts[0].severity == "warn"
    patch(monkeypatch, flat, pd.Series([40.0] * 27 + [55.0] * 3, index=idx))
    assert read(regime.scan)[0].message.startswith("55% of stocks are back above")


def test_kinds_listed(world, client):  # noqa: F811
    kinds = {k["kind"] for k in client.get("/api/alerts/kinds").json()}
    assert {"results_due", "market_regime", "trend_break", "trail_hit"} <= kinds


def _px(closes, lows=None, sym="TTT"):
    """Bars ending 2026-11-06 (high = close + 1, low = close - 1 unless overridden by index)."""
    from app.sources.base import Bar
    from app.sources.store import save_bars

    days = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=len(closes))]
    out = [Bar(sym, d, c, c + 1, (lows or {}).get(i, c - 1), c, 1000.0)
           for i, (d, c) in enumerate(zip(days, closes, strict=True))]  # fmt: skip
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO symbols(symbol, name, in_universe) VALUES (?,?,1)", (sym, sym))
        save_bars("px", out, c)
    frames.invalidate()
    return days


def test_trend_break_fires_on_crossing_and_is_stable(world):  # noqa: F811
    from app.alerts.scanners import trend_exit

    days = _px([100.0] * 30 + [101, 102, 103, 104, 105, 90, 89, 88])
    with db.tx() as c:
        db.set_setting("position_exit_sma", 20, c)
        pid = add_position(c, "TTT", entry_date=days[30])
    [d] = read(trend_exit.trend_break)
    assert d.dedupe_key == f"trend_break:{pid}:{days[35]}" and d.severity == "warn"
    assert "closed at ₹90 on" in d.message and "below its 20-day average (₹" in d.message
    assert [x.dedupe_key for x in read(trend_exit.trend_break)] == [d.dedupe_key]
    with db.tx() as c:
        db.set_setting("position_exit_sma", 0, c)
    assert read(trend_exit.trend_break) == []


def test_trend_break_needs_a_crossing_after_entry(world):  # noqa: F811
    from app.alerts.scanners import trend_exit

    days = _px([100.0] * 30 + [90.0] * 5)
    with db.tx() as c:
        db.set_setting("position_exit_sma", 20, c)
        add_position(c, "TTT", entry_date=days[34])  # bought while already below
    assert read(trend_exit.trend_break) == []


def test_trail_hit_follows_highest_close(world):  # noqa: F811
    from app.alerts.scanners import trend_exit

    days = _px([100.0] * 30 + [110, 120, 118, 117], lows={33: 115.0, 31: 108.0})
    with db.tx() as c:
        db.set_setting("trail_atr_multiple", 2, c)
        pid = add_position(c, "TTT", entry_date=days[29], entry_price=100.0)
    [d] = read(trend_exit.trail_hit)
    assert d.dedupe_key == f"trail_hit:{pid}" and d.severity == "critical"
    assert "(low ₹115, stop ₹116, 2 ATRs under the high of ₹120)" in d.message


def test_trail_hit_never_on_entry_day_and_off_at_zero(world):  # noqa: F811
    from app.alerts.scanners import trend_exit

    days = _px([100.0] * 34, lows={33: 50.0})  # crash low on the entry day itself
    with db.tx() as c:
        db.set_setting("trail_atr_multiple", 2, c)
        add_position(c, "TTT", entry_date=days[33])
    assert read(trend_exit.trail_hit) == []
    with db.tx() as c:
        db.set_setting("trail_atr_multiple", 0, c)
    assert read(trend_exit.trail_hit) == []


def _screen(c, name="Value"):
    return c.execute(
        "INSERT INTO screens(name, rule, created_at, updated_at) "
        "VALUES (?, '{}', '2026-10-01T09:00:00+05:30', '2026-10-01T09:00:00+05:30')",
        (name,),
    ).lastrowid


def _result(c, sid, sym, as_of):
    c.execute(
        "INSERT INTO screen_results(screen_id, symbol, as_of, values_json, first_seen) VALUES (?,?,?,'{}',?)",
        (sid, sym, as_of, as_of),
    )


def test_screen_left(world):  # noqa: F811
    from app.alerts.scanners import screen_left

    with db.tx() as c:
        sid = _screen(c)
        gone = add_position(c, "AAA", source_screen_id=sid)
        add_position(c, "BBB", source_screen_id=sid)
        add_position(c, "CCC")
        _result(c, sid, "BBB", "2026-11-06")
        _result(c, sid, "DDD", "2026-11-06")
    [d] = read(screen_left.scan)
    assert d.dedupe_key == f"screen_left:{gone}:{sid}" and d.severity == "info" and d.link == "/stock/AAA"
    assert d.message.startswith("AAA no longer matches 'Value', the screen you bought it from.")


def test_screen_left_old_run_or_never_run(world):  # noqa: F811
    from app.alerts.scanners import screen_left

    with db.tx() as c:
        sid = _screen(c)
        other = _screen(c, "Never run")
        add_position(c, "AAA", source_screen_id=sid, entry_date="2026-11-06")
        add_position(c, "BBB", source_screen_id=other)
        _result(c, sid, "DDD", "2026-11-06")  # same day as entry
    assert read(screen_left.scan) == []


def _ann(c, sym, ts, headline="Wins big order", category="order_win"):
    return c.execute(
        "INSERT INTO announcements(source, symbol, ts, category, headline) VALUES ('x',?,?,?,?)",
        (sym, ts, category, headline),
    ).lastrowid


def _jump(pct, mult, sym="TTT"):
    from app.sources.base import Bar
    from app.sources.store import save_bars

    closes = [100.0] * 29 + [100.0 + pct, 100.0 + pct]
    vols = [1000.0] * 29 + [1000.0 * mult, 1000.0]
    days = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=len(closes))]
    out = [Bar(sym, d, c, c, c, c, v) for d, c, v in zip(days, closes, vols, strict=True)]
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO symbols(symbol, name, in_universe) VALUES (?,?,1)", (sym, sym))
        save_bars("px", out, c)
    frames.invalidate()
    return days


def test_catalyst_fires(world):  # noqa: F811
    from app.alerts.scanners import catalyst

    days = _jump(4, 2.5)
    with db.tx() as c:
        aid = _ann(c, "TTT", f"{days[29]}T11:00:00+05:30", "x" * 130)
    [d] = read(catalyst.scan)
    assert d.dedupe_key == f"catalyst:{aid}" and d.severity == "info" and d.link == "/stock/TTT"
    assert d.message.startswith("TTT rose 4.0% on 2.5× normal volume on ")
    assert d.message.endswith("after: " + "x" * 119 + "…")


def test_catalyst_needs_volume_and_move(world):  # noqa: F811
    from app.alerts.scanners import catalyst

    for pct, mult in ((4, 1.2), (1, 3)):
        days = _jump(pct, mult)
        with db.tx() as c:
            c.execute("DELETE FROM announcements")
            _ann(c, "TTT", f"{days[29]}T11:00:00+05:30")
        assert read(catalyst.scan) == []


def test_catalyst_after_close_uses_next_bar(world):  # noqa: F811
    from app.alerts.scanners import catalyst

    days = _jump(4, 2.5)
    with db.tx() as c:
        _ann(c, "TTT", f"{days[29]}T16:00:00+05:30")  # next bar is flat again
    assert read(catalyst.scan) == []
    with db.tx() as c:
        c.execute("DELETE FROM announcements")
        _ann(c, "TTT", f"{days[28]}T16:00:00+05:30")  # next bar is the jump
    assert len(read(catalyst.scan)) == 1


def test_catalyst_category_and_age(world):  # noqa: F811
    from app.alerts.scanners import catalyst

    days = _jump(4, 2.5)
    with db.tx() as c:
        _ann(c, "TTT", f"{days[29]}T11:00:00+05:30", category="dividend")
        _ann(c, "TTT", "2026-11-02T11:00:00+05:30")  # 7 days before NOW
    assert read(catalyst.scan) == []
