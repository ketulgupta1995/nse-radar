import numpy as np
import pandas as pd
import pytest

from app.analytics import frames
from app.analytics import indicators as ind


def _world(monkeypatch, with_two=False):
    idx = pd.bdate_range("2026-01-01", periods=10)
    data, inds = {}, {}
    growth = {"A": [0.01, 0.02, 0.03], "B": [0.0, 0.0, 0.0], "C": [-0.01, -0.02, -0.03]}
    for name, rates in growth.items():
        for i, r in enumerate(rates):
            sym = f"{name}{i}"
            data[sym] = pd.DataFrame({"close": 100 * (1 + r) ** np.arange(10)}, index=idx)
            inds[sym] = name
    if with_two:
        for sym in ("D0", "D1"):
            data[sym] = pd.DataFrame({"close": 100 * 1.05 ** np.arange(10)}, index=idx)
            inds[sym] = "D"
    monkeypatch.setattr(frames, "universe", lambda conn=None: list(data))
    monkeypatch.setattr(frames, "last_trading_date", lambda conn=None: "2026-01-14")
    monkeypatch.setattr(frames, "load_frame", lambda sym, start=None: data[sym])
    monkeypatch.setattr(frames, "industry_of", lambda sym: inds.get(sym))
    frames.invalidate()
    return data


def test_load_industry_returns_medians_min_stocks_and_cache(monkeypatch):
    _world(monkeypatch, with_two=True)
    monkeypatch.setattr(frames, "MARKET_MIN_STOCKS", 9)
    out = frames.load_industry_returns(5)
    assert set(out.columns) == {"A", "B", "C", "D", "__market__"}
    assert out["A"].iloc[:5].isna().all()
    assert out["A"].iloc[-1] == pytest.approx((1.02**5 - 1) * 100)  # median of 1/2/3%
    assert out["B"].iloc[-1] == pytest.approx(0.0)
    assert out["D"].isna().all()  # only 2 stocks
    assert out["__market__"].iloc[-1] == pytest.approx(0.0)  # median of 11 stocks = a 0% one
    monkeypatch.setattr(frames, "load_frame", lambda sym, start=None: 1 / 0)
    assert frames.load_industry_returns(5).equals(out)  # cached


def test_industry_indicators_values_and_missing_symbol(monkeypatch):
    data = _world(monkeypatch)
    f = data["A0"].copy()
    f.attrs["symbol"] = "A0"
    table = frames.load_industry_returns(5)
    stock = (f["close"].iloc[-1] / f["close"].iloc[-6] - 1) * 100
    rs = ind.compute("industry_rs", f, None, n=5)
    assert rs.iloc[-1] == pytest.approx(stock - table["A"].iloc[-1])
    assert rs.iloc[-1] < 0  # A0 is the slowest in its industry
    # the market column needs 20 stocks and there are only 9 here
    assert ind.compute("industry_strength", f, None, n=5).isna().all()
    monkeypatch.setattr(frames, "MARKET_MIN_STOCKS", 9)
    frames.invalidate()
    table = frames.load_industry_returns(5)
    strength = ind.compute("industry_strength", f, None, n=5)
    assert strength.iloc[-1] == pytest.approx(table["A"].iloc[-1])  # market median is 0%
    assert ind.compute("industry_rs", data["A0"].copy(), None, n=5).isna().all()  # no symbol attr
    assert "industry_rs" in [c["name"] for c in ind.catalogue()]
