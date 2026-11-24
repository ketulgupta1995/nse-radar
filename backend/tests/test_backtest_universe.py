import numpy as np
import pandas as pd
import pytest

from app import db
from app.analytics import frames
from app.backtest import metrics
from app.backtest import universe as uni
from app.backtest.engine import BacktestConfig, run_backtest
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec
from app.sources.store import save_bars

MONTHS = pd.period_range("2024-01", periods=8, freq="M")


@pytest.fixture
def world():
    db.init_db()
    registry.clear()
    caps = (CapabilitySpec("bars", "by_symbol", (), adjusted=True),)
    registry.register(
        type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d", "homepage": "h",
                                   "capabilities": caps})()  # fmt: skip
    )
    frames.invalidate()
    yield
    registry.clear()
    frames.invalidate()


def _bars(sym: str, per_month: list[float], use_value: bool = False) -> list[Bar]:
    out = []
    for m, v in zip(MONTHS, per_month, strict=False):
        d = f"{m}-10"
        if use_value:
            out.append(Bar(sym, d, 10, 10, 10, 10, 1.0, value=v))
        else:
            out.append(Bar(sym, d, 10, 10, 10, 10, v / 10))
    return out


def _seed(rows: dict[str, list[Bar]]) -> None:
    with db.tx() as c:
        for sym, bars in rows.items():
            c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES (?,?,0)", (sym, sym))
            save_bars("px", bars, c)


def test_ranks_follow_value_and_need_three_months(world):
    _seed({
        "BIG": _bars("BIG", [1000] * 8),
        "MID": _bars("MID", [500] * 8, use_value=True),  # value preferred over close x volume
        "LOW": _bars("LOW", [10] * 8),
    })  # fmt: skip
    with db.tx() as c:  # value column wins even when close*volume says otherwise
        c.execute("UPDATE bars SET value=500 WHERE sym_id=(SELECT id FROM bar_symbols WHERE symbol='MID')")
    r = uni.liquidity_ranks()
    assert list(r.index) == [str(m) for m in MONTHS]
    assert r["BIG"].isna().sum() == 2 and r["BIG"].iloc[2] == 1
    assert r.loc["2024-08", ["BIG", "MID", "LOW"]].tolist() == [1, 2, 3]


def _tag(bars: list[Bar], isin: str, series: str) -> list[Bar]:
    return [
        Bar(b.symbol, b.date, b.open, b.high, b.low, b.close, b.volume, b.value, b.trades, series, isin)
        for b in bars
    ]


def test_funds_and_reits_are_not_ranked(world):
    _seed({
        "ETF": _tag(_bars("ETF", [9000] * 8), "INF204KB14I2", "EQ"),
        "REIT": _tag(_bars("REIT", [8000] * 8), "INE0BWS23018", "RR"),
        "STK": _tag(_bars("STK", [100] * 8), "INE002A01018", "EQ"),
        "NOROW": _bars("NOROW", [50] * 8),
    })  # fmt: skip
    r = uni.liquidity_ranks()
    assert "ETF" not in r.columns and "REIT" not in r.columns
    assert r.loc["2024-08", ["STK", "NOROW"]].tolist() == [1, 2]


def test_eligible_uses_previous_month(world):
    # NEW is quiet until March, then the most traded
    _seed({
        "OLD": _bars("OLD", [100] * 8),
        "NEW": _bars("NEW", [1, 1, 10_000, 10_000, 10_000, 10_000, 10_000, 10_000]),
    })  # fmt: skip
    r = uni.liquidity_ranks()
    # smoothed: NEW only outranks OLD once its 6m mean beats 100 -> from March (mean 3334)
    dates = pd.DatetimeIndex(["2024-03-29", "2024-04-01", "2024-05-02"])
    m = uni.eligible_mask(r, dates, "NEW", top_n=1)
    assert m.tolist() == [False, True, True]
    assert uni.eligible_mask(r, dates, "NOPE").tolist() == [False] * 3


def test_candidates(world):
    _seed({"A": _bars("A", [100] * 8), "B": _bars("B", [50] * 8), "C": _bars("C", [10] * 8)})
    with db.tx() as c:
        c.execute("UPDATE symbols SET in_universe=1 WHERE symbol='C'")
    r = uni.liquidity_ranks()
    assert uni.candidate_symbols(r, "2024-01-01", top_n=1) == ["A", "C"]
    assert uni.candidate_symbols(r, "2024-01-01", top_n=2) == ["A", "B", "C"]
    assert uni.candidate_symbols(r, "2030-01-01", top_n=1) == ["C"]


# ---- engine -------------------------------------------------------------------------------

ZERO = dict.fromkeys(
    ("brokerage_pct", "brokerage_cap_inr", "stt_pct", "exchange_pct", "sebi_pct", "stamp_buy_pct",
     "gst_pct", "dp_charge_inr", "slippage_pct"), 0)  # fmt: skip
IDX = pd.bdate_range("2024-01-01", periods=30)
RULE = {"all": [{"left": {"ind": "volume"}, "op": ">", "right": {"value": 5}}]}


def _frame(signal_days) -> pd.DataFrame:
    vol = np.ones(30)
    for s in signal_days:
        vol[s] = 10
    p = np.full(30, 100.0)
    return pd.DataFrame({"open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": vol}, index=IDX)


def _cfg(exits, universe="current") -> BacktestConfig:
    return BacktestConfig(
        entry_rule=RULE, exits=exits, start="2024-01-01", max_positions=1, universe=universe
    )


def _mask(true_days) -> pd.Series:
    return pd.Series([i in true_days for i in range(30)], index=IDX)


def test_masked_symbol_never_enters(world):
    db.set_setting("cost_model", ZERO)
    r = run_backtest(
        _cfg([{"type": "time_stop", "params": {"days": 5}}]),
        frames={"A": _frame([2])}, bench=None, fund={}, eligible={"A": _mask(set())},
    )  # fmt: skip
    assert r["trades"] == []


def test_mask_off_after_entry_still_exits(world):
    db.set_setting("cost_model", ZERO)
    r = run_backtest(
        _cfg([{"type": "time_stop", "params": {"days": 5}}]),
        frames={"A": _frame([2])}, bench=None, fund={}, eligible={"A": _mask({2})},
    )  # fmt: skip
    assert len(r["trades"]) == 1 and r["trades"][0]["reason"] != "end of test"


def test_no_eligible_means_no_mask(world):
    db.set_setting("cost_model", ZERO)
    r = run_backtest(
        _cfg([{"type": "time_stop", "params": {"days": 5}}], universe="liquid500"),
        frames={"A": _frame([2])}, bench=None, fund={},
    )  # fmt: skip
    assert len(r["trades"]) == 1


# ---- warnings -----------------------------------------------------------------------------


def test_warnings_by_universe():
    res = {"equity": [], "trades": [], "warnings": [], "metrics": {}}
    cur = metrics.warnings_for(res, BacktestConfig(entry_rule=RULE, universe="current"))
    liq = metrics.warnings_for(res, BacktestConfig(entry_rule=RULE, universe="liquid500"))
    assert cur[0] == metrics.SURVIVORSHIP and metrics.UNIVERSE not in cur
    assert liq[0] == metrics.UNIVERSE and metrics.SURVIVORSHIP not in liq
    assert not any("left out" in w for w in liq)
    res["warnings"] = ["3 stocks with price jumps that could not be explained were left out."]
    assert any(w.startswith("3 stocks") for w in metrics.warnings_for(res, BacktestConfig(entry_rule=RULE)))


def test_old_stored_config_loads():
    assert BacktestConfig(entry_rule=RULE, **{"universe": "current"}).universe == "current"
