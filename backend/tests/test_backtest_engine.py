import numpy as np
import pandas as pd
import pytest

from app import db
from app.backtest import exits as exits_mod
from app.backtest.engine import BacktestConfig, run_backtest

ZERO = {
    k: 0
    for k in (
        "brokerage_pct",
        "brokerage_cap_inr",
        "stt_pct",
        "exchange_pct",
        "sebi_pct",
        "stamp_buy_pct",
        "gst_pct",
        "dp_charge_inr",
        "slippage_pct",
    )
}
IDX = pd.bdate_range("2024-01-01", periods=30)
# entry rule: the "signal" lives in the volume column (volume > 5 means "buy")
RULE = {"all": [{"left": {"ind": "volume"}, "op": ">", "right": {"value": 5}}]}


@pytest.fixture(autouse=True)
def _db():
    db.init_db()
    db.set_setting("cost_model", ZERO)


def make(opens, highs=None, lows=None, closes=None, signal_days=(2,), n=30):
    o = np.array(list(opens) + [opens[-1]] * (n - len(opens)), dtype=float)
    c = o if closes is None else np.array(list(closes) + [closes[-1]] * (n - len(closes)), dtype=float)
    h = (
        np.maximum(o, c) + 0.5
        if highs is None
        else np.array(list(highs) + [highs[-1]] * (n - len(highs)), dtype=float)
    )
    lo = (
        np.minimum(o, c) - 0.5
        if lows is None
        else np.array(list(lows) + [lows[-1]] * (n - len(lows)), dtype=float)
    )
    vol = np.ones(n)
    for s in signal_days:
        vol[s] = 10
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": vol}, index=IDX[:n])


def cfg(exits, **kw):
    return BacktestConfig(entry_rule=RULE, exits=exits, start="2024-01-01", **kw)


def flat(price=100.0, **kw):
    return make([price] * 30, **kw)


def test_new_exit_type_needs_no_engine_change(monkeypatch):
    monkeypatch.setitem(
        exits_mod.EXITS,
        "always",
        exits_mod.ExitDef(
            "always", "Always", "x", (), "close", lambda p, q: {}, lambda s, b, c: (True, None, "always")
        ),
    )
    r = run_backtest(cfg([{"type": "always", "params": {}}]), frames={"A": flat()}, bench=None, fund={})
    assert r["trades"][0]["reason"] == "always"


def test_signal_fills_next_open_not_same_day():
    opens = [100.0] * 30
    opens[3] = 110.0  # t+1 open differs from signal-day (t=2) open
    r = run_backtest(
        cfg([{"type": "time_stop", "params": {"days": 3}}]), frames={"A": make(opens)}, bench=None, fund={}
    )
    t = r["trades"][0]
    assert t["entry_date"] == IDX[3].strftime("%Y-%m-%d") and t["entry"] == 110.0


def test_future_bars_do_not_change_decision():
    a = flat()
    b = flat()
    b.iloc[10:, :4] = 50.0  # rewrite the future after the signal
    ra = run_backtest(
        cfg([{"type": "time_stop", "params": {"days": 3}}]), frames={"A": a}, bench=None, fund={}
    )
    rb = run_backtest(
        cfg([{"type": "time_stop", "params": {"days": 3}}]), frames={"A": b}, bench=None, fund={}
    )
    assert ra["trades"][0]["entry_date"] == rb["trades"][0]["entry_date"]
    assert ra["trades"][0]["entry"] == rb["trades"][0]["entry"]


def test_stop_gap_down_fills_at_open():
    opens = [100.0] * 30
    opens[6:] = [80.0] * 24
    f = make(opens, closes=opens, lows=[99.5] * 6 + [79.5] * 24)
    r = run_backtest(cfg([{"type": "stop_pct", "params": {"pct": 8}}]), frames={"A": f}, bench=None, fund={})
    t = r["trades"][0]
    assert t["reason"] == "stop" and t["exit"] == 80.0 and t["exit"] < 92.0


def test_stop_and_target_same_bar_stop_wins():
    highs = [100.5] * 30
    lows = [99.5] * 30
    highs[6], lows[6] = 130.0, 70.0
    f = make([100.0] * 30, highs=highs, lows=lows)
    ex = [{"type": "target_pct", "params": {"pct": 10}}, {"type": "stop_pct", "params": {"pct": 10}}]
    r = run_backtest(cfg(ex), frames={"A": f}, bench=None, fund={})
    assert r["trades"][0]["reason"] == "stop" and r["trades"][0]["exit"] == pytest.approx(90.0)


def test_time_stop_after_n_days():
    r = run_backtest(
        cfg([{"type": "time_stop", "params": {"days": 5}}]), frames={"A": flat()}, bench=None, fund={}
    )
    t = r["trades"][0]
    assert t["reason"] == "time stop" and t["days"] == 6  # decided at close of day 5, sold next open


def test_max_positions_and_rank_by_relative_strength():
    n = 200
    idx = pd.bdate_range("2023-01-02", periods=n)

    def frame(slope):
        c = 100 * (1 + slope) ** np.arange(n)
        v = np.ones(n)
        v[-3] = 10
        return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": v}, index=idx)

    bench = pd.Series(100.0, index=idx)
    frames = {"LOW": frame(0.001), "MID": frame(0.002), "TOP": frame(0.004)}
    c = BacktestConfig(
        entry_rule=RULE,
        exits=[{"type": "time_stop", "params": {"days": 50}}],
        start="2023-01-01",
        max_positions=2,
    )
    r = run_backtest(c, frames=frames, bench=bench, fund={})
    assert sorted(t["symbol"] for t in r["trades"]) == ["MID", "TOP"]


def test_costs_reduce_equity():
    ex = [{"type": "time_stop", "params": {"days": 3}}]
    free = run_backtest(cfg(ex), frames={"A": flat()}, bench=None, fund={})
    db.set_setting("cost_model", {**ZERO, "brokerage_pct": 0.5, "brokerage_cap_inr": 1e6, "stt_pct": 0.1})
    paid = run_backtest(cfg(ex), frames={"A": flat()}, bench=None, fund={})
    assert paid["equity"][-1]["v"] < free["equity"][-1]["v"]


def test_fundamentals_warning_and_bad_config():
    rule = {"all": [{"left": {"fund": "pe"}, "op": "<", "right": {"value": 99}}]}
    c = BacktestConfig(entry_rule=rule, exits=[{"type": "time_stop", "params": {}}], start="2024-01-01")
    r = run_backtest(c, frames={"A": flat()}, bench=None, fund={"A": {"pe": 10}})
    assert any("fundamentals" in w for w in r["warnings"])
    with pytest.raises(ValueError):
        BacktestConfig(entry_rule=RULE, exits=[{"type": "nope"}])


# ---- delisted stocks (T085) ----
HOLD = [{"type": "time_stop", "params": {"days": 100}}]


def test_delisted_position_sold_at_last_close_and_slot_freed():
    db.set_setting("cost_model", {**ZERO, "slippage_pct": 1})
    a = make([100.0] * 11, closes=[100.0] * 10 + [120.0], signal_days=(2,), n=11)
    b = make([50.0] * 30, signal_days=(15,))
    r = run_backtest(cfg(HOLD, max_positions=1), frames={"A": a, "B": b}, bench=None, fund={})
    ta = next(t for t in r["trades"] if t["symbol"] == "A")
    assert ta["reason"] == "delisted"
    assert ta["exit"] == pytest.approx(120.0 * 0.99)
    assert ta["exit_date"] == IDX[11].strftime("%Y-%m-%d")
    assert any(t["symbol"] == "B" for t in r["trades"])


def test_no_entry_on_last_bar():
    a = make([100.0] * 6, signal_days=(5,), n=6)
    b = flat(signal_days=())
    r = run_backtest(cfg(HOLD), frames={"A": a, "B": b}, bench=None, fund={})
    assert r["trades"] == []


def test_gap_then_resume_is_not_delisted():
    a = flat(signal_days=(2,))
    a = a.drop(a.index[10:20])
    b = flat(signal_days=())
    r = run_backtest(cfg(HOLD), frames={"A": a, "B": b}, bench=None, fund={})
    assert [t["reason"] for t in r["trades"]] == ["end of test"]


def test_equity_after_delisting_is_cash_only():
    a = make([100.0] * 10, signal_days=(2,), n=10)
    b = flat(signal_days=())
    r = run_backtest(cfg(HOLD, max_positions=2), frames={"A": a, "B": b}, bench=None, fund={})
    eq = {e["t"]: e["v"] for e in r["equity"]}
    assert eq[IDX[10].strftime("%Y-%m-%d")] == pytest.approx(1_000_000)
    assert r["trades"][0]["reason"] == "delisted"


def test_trailing_stop_follows_highest_close():
    d = exits_mod.EXITS["stop_trail_atr"]
    state = d.setup({"entry_fill": 100.0, "atr14": 2.0}, exits_mod.resolve_params(d, {"k": 3}))
    assert state["level"] == 94.0
    bar = lambda o, h, lo, c: pd.Series({"open": o, "high": h, "low": lo, "close": c})  # noqa: E731
    assert d.check(state, bar(100, 112, 99, 110), {})[0] is False
    assert state["level"] == 104.0  # 110 - 3*2: the stop moved up with the close
    assert d.check(state, bar(109, 111, 105, 106), {})[0] is False
    assert state["level"] == 104.0  # a lower close never lowers the stop
    hit, price, reason = d.check(state, bar(105, 106, 103, 105), {})
    assert hit and price == 104.0 and reason == "trailing stop"
    assert exits_mod.is_stop("stop_trail_atr")


def test_trailing_stop_gap_fills_at_open():
    d = exits_mod.EXITS["stop_trail_atr"]
    state = d.setup({"entry_fill": 100.0, "atr14": 2.0}, {"k": 3.0})
    hit, price, _ = d.check(state, pd.Series({"open": 90, "high": 91, "low": 89, "close": 90}), {})
    assert hit and price == 90.0


def test_series_fund_value_enters_only_after_switch():
    rule = {"all": [{"left": {"fund": "profit_growth_yoy_pct"}, "op": ">", "right": {"value": 10}}]}
    s = pd.Series(np.where(np.arange(30) < 10, np.nan, 20.0), index=IDX)
    c = BacktestConfig(
        entry_rule=rule, exits=[{"type": "time_stop", "params": {"days": 3}}], start="2024-01-01"
    )
    r = run_backtest(c, frames={"A": flat()}, bench=None, fund={"A": {"profit_growth_yoy_pct": s}})
    assert r["trades"] and min(t["entry_date"] for t in r["trades"]) >= str(IDX[10].date())


def test_warnings_split_quarterly_and_snapshot_fields():
    from app.backtest.engine import _warnings

    q = {"all": [{"left": {"fund": "profit_growth_yoy_pct"}, "op": ">", "right": {"value": 10}}]}
    w = _warnings(BacktestConfig(entry_rule=q, start="2024-01-01"))
    assert len(w) == 1 and "as they were published" in w[0]
    roce = {"all": [{"left": {"fund": "roce_pct"}, "op": ">", "right": {"value": 10}}]}
    w = _warnings(BacktestConfig(entry_rule=roce, start="2024-01-01"))
    assert len(w) == 1 and "Yearly figures" in w[0] and "look-ahead" not in w[0]
    pe = {"all": [{"left": {"fund": "pe"}, "op": "<", "right": {"value": 30}}]}
    w = _warnings(BacktestConfig(entry_rule=pe, start="2024-01-01"))
    assert len(w) == 1 and "look-ahead" in w[0] and w[0].endswith("Fields: P/E")
    both = {"all": [roce["all"][0], pe["all"][0]]}
    w = _warnings(BacktestConfig(entry_rule=both, start="2024-01-01"))
    assert len(w) == 2 and "Yearly figures" in w[0] and w[1].endswith("Fields: P/E")


def test_overlay_replaces_snapshot_with_history(client):
    import json

    from app import db
    from app.backtest.engine import _overlay_pit_fields

    detail = {
        "profit_loss": {"periods": ["Mar 2022", "Mar 2023"], "rows": {"Sales": [1, 1]}},
        "balance_sheet": {"periods": [], "rows": {}},
        "ratios_hist": {"periods": ["Mar 2022", "Mar 2023"], "rows": {"ROCE %": [10.0, 20.0]}},
    }
    with db.tx() as c:
        c.execute(
            "INSERT INTO fund_snapshots(source, symbol, fetched_at, fields, detail) "
            "VALUES ('screener','A','2024-01-01','{}', ?)",
            (json.dumps(detail),),
        )
    idx = pd.DatetimeIndex(["2022-06-01", "2023-05-29", "2023-06-01"])
    rule = {"all": [{"left": {"fund": "roce_pct"}, "op": ">=", "right": {"value": 15}}]}
    cfg = BacktestConfig(entry_rule=rule, start="2022-01-01")
    out = _overlay_pit_fields(cfg, {"A": pd.DataFrame(index=idx)}, {"A": {"roce_pct": 30.0}})
    s = out["A"]["roce_pct"]
    assert list(s.to_numpy()) == [10.0, 10.0, 20.0]  # snapshot's 30 never used


def test_rank_operand_uses_eligible_mask_per_month():
    n = 80
    idx = pd.bdate_range("2023-01-02", periods=n)
    syms = [f"S{k:02d}" for k in range(25)]

    def frame(k):
        c = 100 * (1 + 0.001 * (k + 1)) ** np.arange(n)
        return pd.DataFrame(
            {"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": np.ones(n)}, index=idx
        )

    frames = {s: frame(k) for k, s in enumerate(syms)}
    top = syms[-1]
    month2 = idx >= pd.Timestamp("2023-02-01")
    eligible = {s: pd.Series(True, index=idx) for s in syms}
    eligible[top] = pd.Series(month2, index=idx)
    rule = {"all": [{"left": {"ind": "return_pct", "params": {"n": 5}, "rank": True}, "op": ">=",
                     "right": {"value": 99}}]}
    c = BacktestConfig(
        entry_rule=rule, exits=[{"type": "time_stop", "params": {"days": 3}}], start="2023-01-01",
        max_positions=1,
    )
    r = run_backtest(c, frames=frames, bench=None, fund={}, eligible=eligible)
    first = [t for t in r["trades"] if pd.Timestamp(t["entry_date"]) < pd.Timestamp("2023-02-01")]
    assert first and all(t["symbol"] != top for t in first)
    assert any(t["symbol"] == top for t in r["trades"])


# ---- T105: ranking choice, industry cap, regime scaling ------------------------------------


def _frame_at(closes, signal_days):
    c = np.asarray(closes, dtype=float)
    v = np.ones(len(c))
    for s in signal_days:
        v[s] = 10
    idx = pd.bdate_range("2023-01-02", periods=len(c))
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": v}, index=idx)


def _t105_cfg(**kw):
    return BacktestConfig(
        entry_rule=RULE,
        exits=[{"type": "time_stop", "params": {"days": 100}}],
        start="2023-01-01",
        **kw,
    )


def _bench(n=200):
    return pd.Series(100.0, index=pd.bdate_range("2023-01-02", periods=n))


def _slope_frames(slopes, signal_days=(197,)):
    n = 200
    return {s: _frame_at(100 * (1 + k) ** np.arange(n), signal_days) for s, k in slopes.items()}


def test_rank_by_changes_which_stock_is_picked():
    n = 200
    old = 100 * 1.01 ** np.minimum(np.arange(n), 100)
    new = np.full(n, 100.0)
    new[180:] = np.linspace(100, 120, n - 180)
    frames = {"OLD": _frame_at(old, (197,)), "NEW": _frame_at(new, (197,))}
    base = run_backtest(_t105_cfg(max_positions=1), frames=frames, bench=_bench(), fund={})
    alt_cfg = _t105_cfg(max_positions=1, rank_by={"ind": "return_pct", "params": {"n": 10}})
    alt = run_backtest(alt_cfg, frames=frames, bench=_bench(), fund={})
    assert [t["symbol"] for t in base["trades"]] == ["OLD"]
    assert [t["symbol"] for t in alt["trades"]] == ["NEW"]


def test_bad_rank_by_is_rejected():
    with pytest.raises(ValueError):
        _t105_cfg(rank_by={"ind": "rel_strength", "rank": True})
    with pytest.raises(ValueError):
        _t105_cfg(rank_by={"ind": "nope"})


def test_industry_cap_skips_full_industry_and_never_caps_unknown():
    frames = _slope_frames({"A1": 0.004, "A2": 0.003, "A3": 0.0025, "B1": 0.001, "C1": 0.0005})
    ind = {"A1": "X", "A2": "X", "A3": "X", "B1": "Y"}
    r = run_backtest(
        _t105_cfg(max_positions=4, max_per_industry=1),
        frames=frames, bench=_bench(), fund={}, industries=ind,
    )
    assert sorted(t["symbol"] for t in r["trades"]) == ["A1", "B1", "C1"]
    assert any(w.startswith("Industry cap: 33% of trades") for w in r["warnings"])


def test_industry_cap_warning_only_when_unknown_share_is_big():
    frames = _slope_frames({f"S{i}": 0.001 * (i + 1) for i in range(11)})
    ind = {s: f"I{i}" for i, s in enumerate(frames)}  # 11 industries, all known
    r = run_backtest(
        _t105_cfg(max_positions=11, max_per_industry=1),
        frames=frames, bench=_bench(), fund={}, industries=ind,
    )
    assert len(r["trades"]) == 11
    assert not any(w.startswith("Industry cap") for w in r["warnings"])


def _regime_frames():
    c = 100 * 1.002 ** np.arange(200)
    return {
        "A": _frame_at(c, (100,)),
        "B": _frame_at(c, (100,)),
        "C": _frame_at(c, (150,)),
        "D": _frame_at(c, (150,)),
    }


def _breadth(low_from=120, low=40.0, n=200):
    v = np.full(n, 80.0)
    v[low_from:] = low
    return pd.Series(v, index=pd.bdate_range("2023-01-02", periods=n))


def test_regime_scale_limits_new_buys_and_keeps_open_positions():
    scale = {"breadth_below": 50, "slots_pct": 50}
    r = run_backtest(
        _t105_cfg(max_positions=4, regime_scale=scale),
        frames=_regime_frames(), bench=_bench(), fund={}, breadth=_breadth(),
    )
    assert sorted(t["symbol"] for t in r["trades"]) == ["A", "B"]
    assert all(t["reason"] == "end of test" for t in r["trades"])


def test_regime_scale_caps_slots_on_weak_day_and_nan_means_no_limit():
    scale = {"breadth_below": 50, "slots_pct": 50}
    frames = {k: v for k, v in _regime_frames().items() if k in ("C", "D")}
    weak_cfg = _t105_cfg(max_positions=4, regime_scale={**scale, "slots_pct": 25})
    weak = run_backtest(weak_cfg, frames=frames, bench=_bench(), fund={}, breadth=_breadth(low_from=0))
    assert len(weak["trades"]) == 1
    nan = pd.Series(np.nan, index=_bench().index)
    free = run_backtest(
        _t105_cfg(max_positions=4, regime_scale=scale), frames=frames, bench=_bench(), fund={}, breadth=nan
    )
    assert len(free["trades"]) == 2


# ---- T106: monthly rotation ---------------------------------------------------------------

_ROT_IDX = pd.bdate_range("2023-01-02", periods=90)


def _month_ends() -> list[int]:
    m = _ROT_IDX.month
    return [t for t in range(len(_ROT_IDX) - 1) if m[t + 1] != m[t]]


def _rot_frame(vol_at: dict[int, float], close=None):
    c = np.full(90, 100.0) if close is None else np.asarray(close, dtype=float)
    v = np.ones(90)
    for t, x in vol_at.items():
        v[t] = x
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": v}, index=_ROT_IDX)


def _rot_cfg(**kw):
    kw.setdefault("exits", [{"type": "time_stop", "params": {"days": 200}}])
    return BacktestConfig(
        entry_rule=RULE, start="2023-01-01", mode="rotate_monthly", rank_by={"ind": "volume"}, **kw
    )


def _run_rot(frames, **kw):
    return run_backtest(_rot_cfg(**kw), frames=frames, bench=_bench(90), fund={})


def test_rotation_buys_first_day_of_month_and_buffer_keeps_or_sells():
    e1, e2 = _month_ends()[:2]
    month1 = {f"S{i}": 100.0 - i for i in range(30)}  # S0 best
    month2 = dict(month1)
    month2["S0"] = 100.0 - 4.5  # falls to rank 5 -> kept (buffer keeps the top 6)
    month2["S1"] = 100.0 - 20.5  # falls to rank ~21 -> sold
    frames = {s: _rot_frame({e1: month1[s], e2: month2[s]}) for s in month1}
    r = _run_rot(frames, max_positions=4, hold_buffer=1.5)
    first_days = {_ROT_IDX[e1 + 1].strftime("%Y-%m-%d"), _ROT_IDX[e2 + 1].strftime("%Y-%m-%d")}
    assert {t["entry_date"] for t in r["trades"]} <= first_days
    by = {t["symbol"]: t for t in r["trades"]}
    assert by["S1"]["reason"] == "rotation"
    assert by["S1"]["exit_date"] == _ROT_IDX[e2 + 1].strftime("%Y-%m-%d")
    # S0 survived the February rebalance; it only leaves at March month end, when nothing passes
    assert by["S0"]["exit_date"] > by["S1"]["exit_date"]
    assert sorted(by) == ["S0", "S1", "S2", "S3", "S4"]


def test_stop_mid_month_leaves_slot_empty_until_next_rebalance():
    e1, e2 = _month_ends()[:2]
    close = np.full(90, 100.0)
    close[e1 + 10 :] = 50.0  # crash mid-February
    frames = {
        "A": _rot_frame({e1: 20}, close=close),
        "B": _rot_frame({e1: 15, e2: 20}),
    }
    exits = [{"type": "stop_atr", "params": {"k": 2}}]
    r = _run_rot(frames, max_positions=1, hold_buffer=1.0, exits=exits)
    by = {t["symbol"]: t for t in r["trades"]}
    assert by["A"]["reason"] != "rotation" and by["A"]["exit_date"] < by["B"]["entry_date"]
    assert by["B"]["entry_date"] == _ROT_IDX[e2 + 1].strftime("%Y-%m-%d")
    assert len(r["trades"]) == 2


def test_mode_defaults_to_signals_and_buffer_is_validated():
    assert _t105_cfg().mode == "signals"
    with pytest.raises(ValueError):
        _rot_cfg(hold_buffer=3.5)
    with pytest.raises(ValueError):
        _rot_cfg(hold_buffer=0.9)


def test_initial_capital_is_validated():
    assert _t105_cfg(initial_capital=250_000).initial_capital == 250_000
    with pytest.raises(ValueError):
        _t105_cfg(initial_capital=0)
    with pytest.raises(ValueError):
        _t105_cfg(initial_capital=5_000)
