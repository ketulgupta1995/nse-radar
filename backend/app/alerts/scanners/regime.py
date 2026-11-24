"""Market trend changes: the index crossing its 200-day average, breadth crossing 50% (SPEC §13.2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pandas as pd

from app.alerts.base import AlertDraft, AlertScanner, day_name, register
from app.analytics import frames

REGIME_LOOKBACK = 10
SMA_DAYS = 200
BREADTH_LEVEL = 50.0


def _latest_cross(line: pd.Series, level: float) -> tuple[pd.Timestamp, bool] | None:
    """Latest crossing of `level` within the last REGIME_LOOKBACK bars: (bar date, went_up)."""
    vals = line.dropna()
    n = len(vals)
    for i in range(n - 1, max(n - 1 - REGIME_LOOKBACK, 0), -1):
        prev, cur = float(vals.iloc[i - 1]), float(vals.iloc[i])
        if prev >= level > cur:
            return vals.index[i], False
        if prev < level <= cur:
            return vals.index[i], True
    return None


def _index_alert() -> AlertDraft | None:
    bench = frames.load_benchmark()
    if len(bench) <= SMA_DAYS:
        return None
    hit = _latest_cross((bench / bench.rolling(SMA_DAYS).mean() - 1) * 100, 0.0)
    if hit is None:
        return None
    iso = hit[0].date().isoformat()
    day = day_name(iso)
    if hit[1]:
        msg, sev = f"The Nifty 500 closed back above its 200-day average on {day}.", "info"
    else:
        msg = (f"The Nifty 500 closed below its 200-day average on {day}. "
               "In tests, new trend entries did poorly in periods like this.")  # fmt: skip
        sev = "warn"
    return AlertDraft("market_regime", msg, f"regime:index:{iso}", None, "/", sev)


def _breadth_alert() -> AlertDraft | None:
    breadth = frames.load_breadth(SMA_DAYS)
    if not breadth.notna().any():
        return None
    hit = _latest_cross(breadth, BREADTH_LEVEL)
    if hit is None:
        return None
    iso = hit[0].date().isoformat()
    x, day = f"{float(breadth.loc[hit[0]]):.0f}", day_name(iso)
    if hit[1]:
        msg, sev = f"{x}% of stocks are back above their 200-day average (as of {day}).", "info"
    else:
        msg = (f"Only {x}% of stocks are above their 200-day average (as of {day}). "
               "Most stocks are falling even if the index looks fine.")  # fmt: skip
        sev = "warn"
    return AlertDraft("market_regime", msg, f"regime:breadth:{iso}", None, "/", sev)


def scan(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    return [d for d in (_index_alert(), _breadth_alert()) if d is not None]


register(AlertScanner("market_regime", "Market trend changed", scan))
