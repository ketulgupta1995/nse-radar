import json

import pandas as pd
import pytest

from app import db, timeutil
from app.analytics import frames
from app.signals import outcome
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec, IndexBar
from app.sources.store import save_bars, save_index

FREE = {"brokerage_pct": 0, "brokerage_cap_inr": 0, "stt_pct": 0, "exchange_pct": 0, "sebi_pct": 0,
        "stamp_buy_pct": 0, "gst_pct": 0, "dp_charge_inr": 0, "slippage_pct": 0}  # fmt: skip
COSTLY = {**FREE, "brokerage_pct": 0.03, "brokerage_cap_inr": 20, "stt_pct": 0.1, "slippage_pct": 0.1}
CFG = {"exits": [{"type": "stop_atr", "params": {"k": 2}}, {"type": "target_atr", "params": {"k": 4}},
                 {"type": "time_stop", "params": {"days": 3}}], "notional_inr": 100000}  # fmt: skip
PRE = 30  # flat bars: O=C=100, H=101, L=99 -> ATR14 = 2 -> stop 96, target 108 at entry 100
DATES = pd.bdate_range("2026-01-01", periods=80)
AS_OF = DATES[PRE - 1]


def make(post: list[tuple], scale: float = 1.0) -> pd.DataFrame:
    rows = [(100, 101, 99, 100)] * PRE + post
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=DATES[: len(rows)]) * scale
    df["volume"] = 1000.0
    return df


def bench(n: int, values=None) -> pd.Series:
    return pd.Series(values or [1000.0] * n, index=DATES[:n])


def sig(cfg=CFG) -> dict:
    return {"as_of": AS_OF.strftime("%Y-%m-%d"), "exit_config": json.dumps(cfg)}


def run(post, model=FREE, scale=1.0, b=None, newest=None):
    f = make(post, scale)
    newest = newest or f.index[-1].strftime("%Y-%m-%d")
    return outcome.compute_outcome(sig(), f, b if b is not None else bench(len(f)), model, newest)


def test_pending_without_next_bar():
    assert run([])["status"] == "pending"


def test_stop_hit_intraday():
    o = run([(100, 101, 99, 100), (99, 100, 95, 96)])
    assert o["status"] == "closed" and o["exit_reason"] == "stop"
    assert o["exit_fill"] == pytest.approx(96) and o["r_multiple"] == pytest.approx(-1)
    assert o["stop_level"] == pytest.approx(96) and o["target_level"] == pytest.approx(108)


def test_gap_below_stop_exits_at_open():
    o = run([(100, 101, 99, 100), (90, 92, 89, 91)])
    assert o["exit_reason"] == "stop" and o["exit_fill"] == pytest.approx(90)
    assert o["r_multiple"] < -1


def test_target_and_stop_same_bar():
    o = run([(100, 101, 99, 100), (100, 110, 95, 105)])
    assert o["exit_reason"] == "stop"  # stop assumed first
    o = run([(100, 101, 99, 100), (100, 109, 99.5, 105)])
    assert o["exit_reason"] == "target" and o["exit_fill"] == pytest.approx(108)


def test_time_stop_exits_next_open():
    flat = (100, 101, 99, 100)
    o = run([flat, flat, flat, flat, (102, 103, 101, 102)])
    assert o["status"] == "closed" and o["exit_reason"] == "time stop"
    assert o["exit_fill"] == pytest.approx(102) and o["days_held"] == 4
    # exit pending: no next bar yet, so still open and nothing recorded as exit
    o = run([flat, flat, flat, flat])
    assert o["status"] == "open" and o["exit_date"] is None and o["exit_fill"] is None


def test_open_unrealised():
    o = run([(100, 101, 99, 100), (100, 103, 99.5, 102)])
    assert o["status"] == "open" and o["exit_reason"] is None
    assert o["r_multiple"] == pytest.approx(0.5) and o["return_pct"] == pytest.approx(2.0)
    assert o["mfe_r"] == pytest.approx(0.75) and o["mae_r"] == pytest.approx(-0.25)


def test_no_data_when_stale():
    f = make([(100, 101, 99, 100)])
    o = outcome.compute_outcome(sig(), f, bench(len(f)), FREE, "2026-12-30")
    assert o["status"] == "no_data"
    # a closed trade stays closed even when stale
    f = make([(100, 101, 99, 100), (99, 100, 95, 96)])
    o = outcome.compute_outcome(sig(), f, bench(len(f)), FREE, "2026-12-30")
    assert o["status"] == "closed"


def test_split_adjusted_frame_gives_same_r():
    post = [(100, 101, 99, 100), (99, 100, 95, 96)]
    a, b = run(post), run(post, scale=0.5)
    assert b["r_multiple"] == pytest.approx(a["r_multiple"]) and b["exit_reason"] == "stop"
    assert b["entry_fill"] == pytest.approx(50)


def test_costs_and_gap():
    post = [(102, 103, 101, 102), (102, 111, 101, 105)]
    free, costly = run(post), run(post, COSTLY)
    assert costly["return_pct"] < free["return_pct"]
    assert costly["gap_pct"] == pytest.approx(2.0)
    gross = (costly["exit_fill"] / costly["entry_fill"] - 1) * 100
    assert costly["return_pct"] < gross


def test_close_basis_excess():
    post = [(100, 101, 99, 100), (100, 103, 99.5, 102)]
    n = PRE + len(post)
    vals = [1000.0] * (PRE + 1) + [1010.0]
    o = run(post, b=bench(n, vals))
    assert o["stock_cc_pct"] == pytest.approx(2.0) and o["nifty_cc_pct"] == pytest.approx(1.0)
    assert o["excess_pct"] == pytest.approx(1.0)


# ---- update_outcomes ---------------------------------------------------------------------

DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=300)]


def put_bars(extra_days: list[str] | None = None, price=lambda i: 100.0):
    days = DAYS + (extra_days or [])
    with db.tx() as c:
        save_bars(
            "px", [Bar("S00", d, p := price(i), p + 1, p - 1, p, 1000.0) for i, d in enumerate(days)], c
        )
        save_index("px", [IndexBar(frames.INDEX_NAME, d, 1000.0) for d in days], c)
    frames.invalidate()


@pytest.fixture
def world(client, monkeypatch):
    registry.clear()
    caps = (CapabilitySpec("bars", "by_symbol", (), adjusted=True), CapabilitySpec("index", "whole", ()))
    registry.register(type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d",
                                                 "homepage": "h", "capabilities": caps})())  # fmt: skip
    monkeypatch.setattr(timeutil, "now_iso", lambda: "2026-11-09T10:00:00")
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('S00','S00',1)")
    put_bars()
    yield
    registry.clear()
    frames.invalidate()


def add_signal(as_of: str, cfg=CFG) -> int:
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO signals(source, screen_id, symbol, as_of, reasons, planned_entry, atr14, "
            "planned_stop, planned_target, exit_config, score_weights, app_version, bars_as_of, created_at) "
            "VALUES ('shortlist',0,'S00',?, '[]',100,2,96,108,?, '{}','x',?,'t')",
            (as_of, json.dumps(cfg), as_of),
        )
        return cur.lastrowid


def outcome_row(sid: int) -> dict:
    with db.tx() as c:
        return dict(c.execute("SELECT * FROM signal_outcomes WHERE signal_id=?", (sid,)).fetchone())


def test_update_outcomes_writes_and_recomputes(world):
    sid = add_signal(DAYS[-1])
    assert outcome.update_outcomes() == {"pending": 1, "open": 0, "closed": 0, "no_data": 0}
    assert outcome_row(sid)["updated_at"] == "2026-11-09T10:00:00"

    old = add_signal(DAYS[-3])  # flat bars after it: open
    assert outcome.update_outcomes()["open"] == 1
    assert outcome_row(old)["status"] == "open" and outcome_row(old)["last_bar"] == DAYS[-1]

    new_days = [d.date().isoformat() for d in pd.bdate_range(start="2026-11-09", periods=2)]
    put_bars(new_days)
    counts = outcome.update_outcomes()
    assert counts["open"] == 2 and counts["pending"] == 0
    assert outcome_row(sid)["entry_date"] == new_days[0]
    assert outcome_row(old)["last_bar"] == new_days[-1]


def test_closed_rows_left_alone_until_newer_bar(world, monkeypatch):
    sid = add_signal(DAYS[-3])
    put_bars(price=lambda i: 100.0 if i < len(DAYS) - 1 else 90.0)  # last bar gaps below the stop
    outcome.update_outcomes()
    row = outcome_row(sid)
    assert row["status"] == "closed" and row["exit_reason"] == "stop"

    calls = []
    real = outcome.compute_outcome
    monkeypatch.setattr(outcome, "compute_outcome", lambda *a, **k: calls.append(1) or real(*a, **k))
    outcome.update_outcomes()
    assert calls == []  # nothing newer: untouched

    new_days = [d.date().isoformat() for d in pd.bdate_range(start="2026-11-09", periods=1)]
    put_bars(new_days, price=lambda i: 100.0 if i < len(DAYS) - 1 else 90.0)
    outcome.update_outcomes()
    assert calls == [1] and outcome_row(sid)["last_bar"] == new_days[-1]
