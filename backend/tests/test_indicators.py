import json

import numpy as np
import pandas as pd
import pytest

from app.analytics import explain
from app.analytics import indicators as ind


@pytest.fixture
def frame():
    idx = pd.bdate_range("2026-01-01", periods=30)
    close = pd.Series(np.arange(100.0, 130.0), index=idx)
    return pd.DataFrame(
        {"open": close - 0.5, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0},
        index=idx,
    )


def test_sma(frame):
    assert ind.compute("sma", frame, n=5).iloc[-1] == pytest.approx(127.0)  # mean(125..129)


def test_ema(frame):
    c = frame["close"].iloc[:3].tolist()
    expected = c[0]
    for x in c[1:]:
        expected = 0.5 * x + 0.5 * expected  # span 3 -> alpha 0.5
    assert ind.compute("ema", frame, n=3).iloc[2] == pytest.approx(expected)


def test_rsi_monotonic_up(frame):
    assert ind.compute("rsi", frame, n=14).iloc[-1] == pytest.approx(100.0)


def test_rsi_monotonic_down(frame):
    down = frame.copy()
    down["close"] = down["close"].iloc[::-1].values
    assert ind.compute("rsi", down, n=14).iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_atr_known_true_range():
    idx = pd.bdate_range("2026-01-01", periods=4)
    f = pd.DataFrame(
        {"open": 10.0, "high": [11, 12, 14, 13], "low": [9, 10, 11, 12], "close": [10, 11, 13, 12.5],
         "volume": 1.0},
        index=idx,
    )
    # TR: 2, max(2,2,0)=2, max(3,3,0)=3, max(1,0,1)=1 ; Wilder n=3 -> alpha 1/3
    expected = 2.0
    for tr in (2, 3, 1):
        expected = expected + (tr - expected) / 3
    assert ind.compute("atr", f, n=3).iloc[-1] == pytest.approx(expected)


def test_highest_excludes_today(frame):
    f = frame.copy()
    f.iloc[-1, f.columns.get_loc("high")] = 500.0
    f.iloc[-1, f.columns.get_loc("close")] = 499.0
    assert ind.compute("highest", f, n=5).iloc[-1] == pytest.approx(f["high"].iloc[-6:-1].max())
    assert f["close"].iloc[-1] > ind.compute("highest", f, n=5).iloc[-1]


def test_rel_strength(frame):
    bench = pd.Series(np.linspace(1000, 1100, 30), index=frame.index)
    n = 10
    stock = (frame["close"].iloc[-1] / frame["close"].iloc[-1 - n] - 1) * 100
    b = (bench.iloc[-1] / bench.iloc[-1 - n] - 1) * 100
    assert ind.compute("rel_strength", frame, bench, n=n).iloc[-1] == pytest.approx(stock - b)
    assert ind.compute("rel_strength", frame, None, n=n).isna().all()


def test_others_run(frame):
    for name in ("close", "volume", "atr_pct", "return_pct", "pct_from_high", "pct_from_low", "lowest",
                 "volume_ratio", "sma_slope", "range_pct"):  # fmt: skip
        kwargs = {"n": 20} if name in ("pct_from_high", "pct_from_low") else {}
        assert len(ind.compute(name, frame, **kwargs)) == len(frame)
    assert ind.compute("return_pct", frame, n=10).iloc[-1] == pytest.approx((129 / 119 - 1) * 100)
    assert ind.compute("volume_ratio", frame, n=5).iloc[-1] == pytest.approx(1.0)


def test_compute_defaults_and_range(frame):
    assert ind.compute("sma", frame).iloc[19] == pytest.approx(frame["close"].iloc[:20].mean())
    with pytest.raises(ValueError, match="sma.n"):
        ind.compute("sma", frame, n=1)
    with pytest.raises(ValueError, match="unknown parameter"):
        ind.compute("sma", frame, z=3)
    with pytest.raises(ValueError, match="unknown indicator"):
        ind.compute("nope", frame)


def test_duplicate_register():
    with pytest.raises(ValueError):
        ind.register(ind.get("sma"))


def test_catalogue_serialisable_and_explained():
    cat = ind.catalogue()
    json.dumps(cat)
    assert {c["name"] for c in cat} >= {"sma", "ema", "rsi", "atr", "sma_slope", "range_pct", "close"}
    for c in cat:
        assert c["explain"] and len(c["explain_default"]) <= 140 and "{" not in c["explain_default"]


def test_explain_helpers():
    assert explain.explain_indicator("sma", {"n": 50}).startswith("Average closing price of the last 50 days")
    assert explain.label_operand({"ind": "sma", "params": {"n": 200}}) == "200-day average"
    assert explain.label_operand({"ind": "rsi", "params": {"n": 14}}) == "RSI (14)"
    assert explain.label_operand({"ind": "volume", "times": 2}) == "Volume ×2"
    assert explain.label_operand({"fund": "roce_pct"}) == "ROCE %"
    assert explain.label_operand({"value": 15}) == "15"


def test_api(client):
    r = client.get("/api/indicators")
    assert r.status_code == 200 and any(c["name"] == "rsi" for c in r.json())


def _bench(periods=300):
    idx = pd.bdate_range("2025-01-01", periods=periods)
    return pd.Series(np.arange(100.0, 100.0 + periods), index=idx)


def _flat_frame(index):
    return pd.DataFrame({"close": 1.0, "open": 1.0, "high": 1.0, "low": 1.0, "volume": 1.0}, index=index)


def test_index_vs_sma_rising_bench():
    b = _bench()
    out = ind.compute("index_vs_sma", _flat_frame(b.index), b, n=200)
    assert out.iloc[:199].isna().all()
    assert (out.iloc[199:] > 0).all()


def test_index_vs_sma_ffill_to_frame_dates():
    b = _bench()
    sub = b.index[250::2]
    full = (b / b.rolling(20).mean() - 1) * 100
    out = ind.compute("index_vs_sma", _flat_frame(sub), b, n=20)
    assert out.index.equals(sub)
    assert out.iloc[1] == pytest.approx(full.loc[sub[1]])
    shifted = sub + pd.Timedelta(hours=12)  # offset from the bench dates
    out2 = ind.compute("index_vs_sma", _flat_frame(shifted), b, n=20)
    assert out2.index.equals(shifted)
    assert out2.iloc[1] == pytest.approx(full.loc[sub[1]])


def test_index_vs_sma_no_bench(frame):
    for b in (None, pd.Series(dtype=float)):
        out = ind.compute("index_vs_sma", frame, b, n=20)
        assert out.isna().all() and out.index.equals(frame.index)


def test_index_vs_sma_rule_and_catalogue():
    from app.analytics import rules

    b = _bench()
    left = {"ind": "index_vs_sma", "params": {"n": 200}}
    rule = {"all": [{"left": left, "op": ">", "right": {"value": 0}}]}
    res = rules.evaluate(rule, _flat_frame(b.index), b)
    assert res.iloc[-1] and not res.iloc[0]
    assert "index_vs_sma" in [c["name"] for c in ind.catalogue()]


def test_breadth_indicator_uses_frames_and_ffills(monkeypatch, frame):
    from app.analytics import frames

    b = pd.Series([30.0, 60.0], index=pd.DatetimeIndex([frame.index[0], frame.index[10]]))
    monkeypatch.setattr(frames, "load_breadth", lambda n: b if n == 200 else pd.Series(dtype=float))
    out = ind.compute("breadth_above_sma", frame, None, n=200)
    assert out.index.equals(frame.index)
    assert out.iloc[0] == 30 and out.iloc[9] == 30 and out.iloc[10] == 60 and out.iloc[-1] == 60
    assert ind.compute("breadth_above_sma", frame, None, n=50).isna().all()
    assert "breadth_above_sma" in [c["name"] for c in ind.catalogue()]


def test_load_breadth_counts_stocks_above_average(monkeypatch):
    from app.analytics import frames

    idx = pd.bdate_range("2026-01-01", periods=12)
    up = pd.DataFrame({"close": np.arange(1.0, 13.0)}, index=idx)
    down = pd.DataFrame({"close": np.arange(12.0, 0.0, -1.0)}, index=idx)
    flat = pd.DataFrame({"close": 5.0}, index=idx[:6])  # stops trading half way
    data = {"UP": up, "DOWN": down, "FLAT": flat}
    monkeypatch.setattr(frames, "universe", lambda conn=None: list(data))
    monkeypatch.setattr(frames, "last_trading_date", lambda conn=None: "2026-01-16")
    monkeypatch.setattr(frames, "load_frame", lambda sym, start=None: data[sym])
    monkeypatch.setattr(frames, "BREADTH_MIN_STOCKS", 2)
    frames.invalidate()
    out = frames.load_breadth(3)
    assert out.index.equals(idx)
    assert out.iloc[:2].isna().all()  # no 3-day average yet
    assert out.iloc[2] == pytest.approx(100 / 3)  # UP above, DOWN below, FLAT equal (not above)
    assert out.iloc[-1] == pytest.approx(50.0)  # FLAT gone: UP of (UP, DOWN)
    monkeypatch.setattr(frames, "load_frame", lambda sym, start=None: 1 / 0)
    assert frames.load_breadth(3).equals(out)  # cached: frames are not reloaded


def _ohlc(close, volume=1000.0):
    idx = pd.bdate_range("2026-01-01", periods=len(close))
    c = pd.Series(np.asarray(close, dtype=float), index=idx)
    return pd.DataFrame(
        {"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": volume}, index=idx
    )


def test_mom_smooth_steady_beats_jumpy_and_flat_is_nan():
    n = 40
    steady = _ohlc(100 * 1.002 ** np.arange(n + 1))
    jumpy_close = [100.0]
    for i in range(n):
        jumpy_close.append(jumpy_close[-1] * (1.03 if i % 2 == 0 else 0.9985))
    jumpy = _ohlc(jumpy_close)
    a = ind.compute("mom_smooth", steady, n=20).iloc[-1]
    b = ind.compute("mom_smooth", jumpy, n=20).iloc[-1]
    assert a > b
    assert ind.compute("mom_smooth", _ohlc([100.0] * 50), n=20).isna().all()


def test_adx_trend_vs_chop():
    n = 14
    trend = ind.compute("adx", _ohlc(np.arange(100.0, 200.0)), n=n)
    assert trend.iloc[: 2 * n].isna().all()
    assert trend.iloc[-1] > 40
    chop = ind.compute("adx", _ohlc([100.0 + (i % 2) for i in range(100)]), n=n)
    assert chop.iloc[-1] < 20


def test_efficiency():
    line = ind.compute("efficiency", _ohlc(np.arange(100.0, 130.0)), n=10)
    assert line.iloc[-1] == pytest.approx(100.0)
    zig = ind.compute("efficiency", _ohlc([100.0 + (i % 2) for i in range(30)]), n=10)
    assert zig.iloc[-1] == pytest.approx(0.0)


def test_days_since_high():
    f = _ohlc([100.0] * 30)
    f.iloc[-1, f.columns.get_loc("high")] = 200.0
    out = ind.compute("days_since_high", f, n=20)
    assert out.iloc[-1] == 0
    assert out.iloc[:19].isna().all()
    f2 = _ohlc([100.0] * 30)
    f2.iloc[-6, f2.columns.get_loc("high")] = 200.0
    assert ind.compute("days_since_high", f2, n=20).iloc[-1] == 5


def test_traded_value_cr():
    out = ind.compute("traded_value_cr", _ohlc([100.0] * 30, volume=100000.0), n=20)
    assert out.iloc[-1] == pytest.approx(1.0)


def test_new_indicators_in_catalogue():
    names = {c["name"]: c for c in ind.catalogue()}
    for n in ("mom_smooth", "adx", "efficiency", "days_since_high", "traded_value_cr"):
        assert n in names
        assert len(names[n]["explain_default"]) <= 140
        assert explain.label_operand({"ind": n})


# ---- results reaction (T102) -------------------------------------------------------------------


def _with_results(close, positions, monkeypatch, symbol="AAA"):
    from app.analytics import frames

    f = _ohlc(close)
    if symbol:
        f.attrs["symbol"] = symbol
    stamps = [f.index[p] for p in positions]
    monkeypatch.setattr(frames, "results_dates", lambda sym: stamps)
    return f


def test_results_move_carried_forward(monkeypatch):
    close = [100.0] * 10 + [100.0, 110.0] + [110.0] * 10
    f = _with_results(close, [10], monkeypatch)
    out = ind.compute("results_move", f, k=2)
    assert out.iloc[:11].isna().all()  # bar 10 is the first day, bar 11 the second
    assert out.iloc[11] == pytest.approx(10.0)
    assert out.iloc[-1] == pytest.approx(10.0)


def test_results_move_replaced_at_next_result(monkeypatch):
    close = [100.0] * 10 + [100.0, 110.0] + [110.0] * 5 + [110.0, 99.0] + [99.0] * 3
    f = _with_results(close, [10, 17], monkeypatch)
    out = ind.compute("results_move", f, k=2)
    assert out.iloc[16] == pytest.approx(10.0)
    assert out.iloc[17] == pytest.approx(10.0)  # waits for the k-th bar of the new result
    assert out.iloc[18] == pytest.approx(-10.0)


def test_results_move_stale_after_120_bars_and_no_symbol(monkeypatch):
    close = [100.0] * 10 + [100.0, 110.0] + [110.0] * 200
    f = _with_results(close, [10], monkeypatch)
    out = ind.compute("results_move", f, k=2)
    assert out.iloc[10 + 119] == pytest.approx(10.0)
    assert out.iloc[10 + 120 :].isna().all()
    f.attrs.pop("symbol")
    assert ind.compute("results_move", f, k=2).isna().all()


def test_days_since_results(monkeypatch):
    f = _with_results([100.0] * 20, [5], monkeypatch)
    out = ind.compute("days_since_results", f)
    assert out.iloc[:5].isna().all()
    assert list(out.iloc[5:8]) == [0, 1, 2]
    f.attrs.pop("symbol")
    assert ind.compute("days_since_results", f).isna().all()


def test_results_indicators_in_catalogue():
    names = {c["name"]: c for c in ind.catalogue()}
    for n in ("results_move", "days_since_results"):
        assert n in names
        assert len(names[n]["explain_default"]) <= 140
