import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from app.sources.adapters import yfinance as yfa
from app.sources.base import NotFound, SourceError, SourceRefused

D1, D7 = pd.Timestamp("2026-11-01").date(), pd.Timestamp("2026-11-07").date()
FAKE = Path(__file__).parent / "fixtures/sources/yfinance/fake.py"


@pytest.fixture
def fake(monkeypatch):
    spec = importlib.util.spec_from_file_location("yf_fake", FAKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.install(monkeypatch, FAKE.parent)
    return mod


def test_two_for_one_split_factor_half(fake):
    acts = yfa.YFinance().actions("TCS")
    assert len(acts) == 1
    a = acts[0]
    assert (a.kind, a.factor, a.ex_date, a.subject) == ("split", 0.5, "2026-10-01", "Split 2:1 (Yahoo)")


def test_reverse_split_is_unparsed(fake, monkeypatch):
    class T:
        splits = pd.Series([0.1], index=pd.DatetimeIndex(["2026-10-01"]))

    monkeypatch.setattr(yfa, "_ticker", lambda n: T())
    a = yfa.YFinance().actions("X")[0]
    assert (a.kind, a.factor) == ("unparsed", None)


def test_tz_aware_dates_become_ist_dates(fake, monkeypatch):
    class T:
        def history(self, **kw):  # 2026-11-05 20:00 UTC is already 6 Nov in IST
            idx = pd.DatetimeIndex(["2026-11-05 20:00"], tz="UTC")
            return pd.DataFrame(
                {"Open": [1.0], "High": [2.0], "Low": [1.0], "Close": [2.0], "Volume": [10]}, index=idx
            )

    monkeypatch.setattr(yfa, "_ticker", lambda n: T())
    bars = yfa.YFinance().bars_for_symbol("X", D1, D7)
    assert bars[0].date == "2026-11-06"


def test_empty_history_not_found(fake):
    with pytest.raises(NotFound):
        yfa.YFinance().bars_for_symbol("NOPE", D1, D7)


def test_error_mapping(fake, monkeypatch):
    class Boom:
        def __init__(self, msg):
            self.msg = msg

        def history(self, **kw):
            raise RuntimeError(self.msg)

    d = pd.Timestamp("2026-11-01").date()
    monkeypatch.setattr(yfa, "_ticker", lambda n: Boom("HTTP Error 403: Forbidden"))
    with pytest.raises(SourceRefused):
        yfa.YFinance().bars_for_symbol("X", d, d)
    monkeypatch.setattr(yfa, "_ticker", lambda n: Boom("connection reset"))
    with pytest.raises(SourceError):
        yfa.YFinance().bars_for_symbol("X", d, d)


def test_index_unknown_name(fake):
    with pytest.raises(NotFound):
        yfa.YFinance().index_bars("NIFTY 50", pd.Timestamp("2026-11-01").date())


def test_fundamentals_unit_conversions(fake, monkeypatch):
    class T:
        info = {"returnOnEquity": 0.25, "debtToEquity": 45, "marketCap": 1e12, "heldPercentInsiders": 0.5,
                "trailingPE": float("nan"), "priceToBook": 3.0, "sector": " Tech "}  # fmt: skip

    monkeypatch.setattr(yfa, "_ticker", lambda name: T())
    snap = yfa.YFinance().fundamentals("tcs")
    f = snap.fields
    assert snap.symbol == "TCS"
    assert f["roe_pct"] == pytest.approx(25.0) and f["debt_to_equity"] == pytest.approx(0.45)
    assert f["market_cap_cr"] == pytest.approx(100000.0) and f["promoter_pct"] == pytest.approx(50.0)
    assert f["pe"] is None and f["pb"] == 3.0 and f["sector"] == "Tech" and f["industry"] is None
    assert snap.detail["raw_keys"]["debtToEquity"] == 45 and "trailingPE" not in snap.detail["raw_keys"]


def test_fundamentals_empty_info_not_found(fake):
    with pytest.raises(NotFound):
        yfa.YFinance().fundamentals("NOPE")


def test_fundamentals_error_mapping(fake, monkeypatch):
    class Boom:
        @property
        def info(self):
            raise RuntimeError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(yfa, "_ticker", lambda name: Boom())
    with pytest.raises(SourceRefused):
        yfa.YFinance().fundamentals("TCS")


def _history_of(monkeypatch, rows):
    class T:
        def history(self, **kw):
            idx = pd.DatetimeIndex([r[0] for r in rows])
            names = ("Open", "High", "Low", "Close", "Volume")
            data = {n: [r[i + 1] for r in rows] for i, n in enumerate(names)}
            return pd.DataFrame(data, index=idx)

    monkeypatch.setattr(yfa, "_ticker", lambda n: T())


def test_flat_zero_volume_bar_dropped(monkeypatch):
    _history_of(monkeypatch, [("2026-11-02", 5, 5, 5, 5, 0), ("2026-11-03", 5, 6, 4, 5, 100)])
    bars = yfa.YFinance().bars_for_symbol("X", D1, D7)
    assert [b.date for b in bars] == ["2026-11-03"]


def test_zero_volume_with_range_kept(monkeypatch):
    _history_of(monkeypatch, [("2026-11-02", 5, 6, 5, 5, 0)])
    assert len(yfa.YFinance().bars_for_symbol("X", D1, D7)) == 1


def test_all_flat_rows_not_found(monkeypatch):
    _history_of(monkeypatch, [("2026-11-02", 5, 5, 5, 5, 0)])
    with pytest.raises(NotFound):
        yfa.YFinance().bars_for_symbol("X", D1, D7)
