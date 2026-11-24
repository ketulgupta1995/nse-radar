"""Fake Yahoo access for the contract suite (SPEC §3.7): no network, small inline frames."""

import importlib

import pandas as pd

MOD = "app.sources.adapters.yfinance"


def _frame(rows, tz="Asia/Kolkata"):
    idx = pd.DatetimeIndex([r[0] for r in rows], tz=tz)
    return pd.DataFrame(
        {"Open": [r[1] for r in rows], "High": [r[2] for r in rows], "Low": [r[3] for r in rows],
         "Close": [r[4] for r in rows], "Volume": [r[5] for r in rows]},
        index=idx,
    )  # fmt: skip


class FakeTicker:
    def __init__(self, name):
        self.name = name

    def history(self, **kwargs):
        if self.name == "TCS.NS":
            return _frame([
                ("2026-11-05 00:00", 100, 105, 99, 104, 1000),
                ("2026-11-06 00:00", 104, 108, 103, 107, 1500),
            ])  # fmt: skip
        if self.name == "^CRSLDX":
            return _frame([
                ("2026-11-05 00:00", 0, 0, 0, 23000.5, 0),
                ("2026-11-06 00:00", 0, 0, 0, 23100.0, 0),
            ])  # fmt: skip
        return pd.DataFrame()

    @property
    def splits(self):
        if self.name == "TCS.NS":
            return pd.Series([2.0], index=pd.DatetimeIndex(["2026-10-01"], tz="Asia/Kolkata"))
        return pd.Series([], dtype=float)


    @property
    def info(self):
        if self.name == "TCS.NS":
            return {"trailingPE": 25.0, "priceToBook": 12.0, "returnOnEquity": 0.5, "debtToEquity": 9.9,
                    "marketCap": 1.2e13, "heldPercentInsiders": 0.7177, "sector": "Technology",
                    "industry": "Information Technology Services", "dividendYield": float("nan")}  # fmt: skip
        return {}


class RefusingTicker:
    def __init__(self, name):
        pass

    def history(self, **kwargs):
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    @property
    def splits(self):
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    @property
    def info(self):
        raise RuntimeError("HTTP Error 429: Too Many Requests")


def install(monkeypatch, fixtures_dir):
    mod = importlib.import_module(MOD)
    monkeypatch.setattr(mod, "_ticker", FakeTicker)
    monkeypatch.setattr(mod, "MIN_INTERVAL_S", 0.0)


def install_refusal(monkeypatch, fixtures_dir):
    mod = importlib.import_module(MOD)
    monkeypatch.setattr(mod, "_ticker", RefusingTicker)
    monkeypatch.setattr(mod, "MIN_INTERVAL_S", 0.0)
