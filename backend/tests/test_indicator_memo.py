"""Indicator results memo used by repeat backtests and screens."""

import pandas as pd
import pytest
from test_adjust_frames import make

from app import db
from app.analytics import frames, indicators
from app.sources import registry
from app.sources.base import Bar
from app.sources.store import save_bars

DAYS = pd.bdate_range("2026-01-01", periods=40).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _setup():
    db.init_db()
    registry.clear()
    registry.register(make("raw", adjusted=False))
    db.set_setting("source_priority", {"bars": ["raw"], "actions": ["raw"], "index": ["raw"]})
    frames.invalidate()
    with db.tx() as c:
        save_bars("raw", [Bar("AAA", d, 10 + i, 11 + i, 9 + i, 10 + i, 100) for i, d in enumerate(DAYS)], c)
    yield
    registry.clear()
    frames.invalidate()


def test_repeat_compute_hits_memo_and_matches():
    f = frames.load_frame("AAA")
    first = indicators.compute("sma", f, None, n=5)
    assert len(indicators._memo) == 1
    again = indicators.compute("sma", frames.load_frame("AAA"), None, n=5)
    assert len(indicators._memo) == 1
    pd.testing.assert_series_equal(first, again)
    again.iloc[-1] = -1.0  # callers get a copy, never the stored series
    assert indicators.compute("sma", f, None, n=5).iloc[-1] == first.iloc[-1]


def test_untagged_or_sliced_frames_are_not_confused():
    f = frames.load_frame("AAA")
    full = indicators.compute("return_pct", f, None, n=1)
    head = f.iloc[:10]  # attrs (and the cache key) survive slicing
    sliced = indicators.compute("return_pct", head, None, n=1)
    assert len(sliced) == 10 and len(full) == 40
    plain = pd.DataFrame(f.to_dict("series"))
    plain["close"] = plain["close"] * 2  # same shape, different values, no tag: computed fresh
    assert indicators.compute("sma", plain, None, n=5).iloc[-1] == 2 * indicators.compute(
        "sma", f, None, n=5
    ).iloc[-1]


def test_price_write_clears_memo():
    indicators.compute("sma", frames.load_frame("AAA"), None, n=5)
    assert indicators._memo
    with db.tx() as c:
        save_bars("raw", [Bar("AAA", "2026-03-02", 1, 1, 1, 1, 1)], c)
    assert not indicators._memo


def test_repaired_frame_drops_the_tag():
    from app.backtest.history import repair_frame

    with db.tx() as c:  # last close 49 -> 24.5: an unexplained 2:1 split the repair will undo
        save_bars("raw", [Bar("AAA", "2026-03-02", 24.5, 24.5, 24.5, 24.5, 1)], c)
    out, fixes = repair_frame(frames.load_frame("AAA"))
    assert fixes == 1 and "cache_key" not in out.attrs
