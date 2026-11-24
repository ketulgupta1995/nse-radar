"""Yahoo Finance via the yfinance library: adjusted prices, splits, Nifty 500 index.

The library doesn't use sources/http.py, so this module throttles itself (1 call per second)
and wraps library errors into the §3.2 exceptions.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import date, datetime, timedelta

import yfinance as yf

from app import config
from app.sources import registry
from app.sources.base import (
    Action,
    Bar,
    BaseSource,
    CapabilitySpec,
    FundSnapshot,
    IndexBar,
    JobVariant,
    NotFound,
    SourceError,
    SourceRefused,
)

log = logging.getLogger(__name__)

INDEX_TICKERS = {"NIFTY 500": "^CRSLDX"}
MIN_INTERVAL_S = 1.0

_lock = threading.Lock()
_last_call = 0.0


def _ticker(symbol_or_index: str):
    """Hook for tests: returns an object with .history(...), .splits and .info."""
    return yf.Ticker(symbol_or_index)


def _throttle() -> None:
    global _last_call
    with _lock:
        gap = MIN_INTERVAL_S - (time.monotonic() - _last_call)
        if gap > 0:
            time.sleep(gap)
        _last_call = time.monotonic()


def _wrap(e: Exception, what: str) -> Exception:
    text = f"{type(e).__name__}: {e}"
    low = text.lower()
    if any(t in low for t in ("401", "403", "429", "too many requests", "ratelimit", "rate limit")):
        return SourceRefused(f"Yahoo refused {what}: {text}")
    return SourceError(f"Yahoo failed for {what}: {text}")


def _to_date(ts) -> date:
    if getattr(ts, "tzinfo", None) is not None:
        return ts.tz_convert(config.TZ).date()
    return ts.date() if isinstance(ts, datetime) or hasattr(ts, "date") else ts


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# §9.3: Yahoo `info` key -> (our field, converter)
_INFO_MAP = {
    "trailingPE": ("pe", lambda v: v),
    "priceToBook": ("pb", lambda v: v),
    "returnOnEquity": ("roe_pct", lambda v: v * 100),
    "debtToEquity": ("debt_to_equity", lambda v: v / 100),
    "marketCap": ("market_cap_cr", lambda v: v / 1e7),
    "heldPercentInsiders": ("promoter_pct", lambda v: v * 100),
}
_INFO_TEXT = {"sector": "sector", "industry": "industry"}


def _history(ticker: str, start: date, end: date):
    _throttle()
    try:
        df = _ticker(ticker).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            actions=False,
        )
    except Exception as e:
        raise _wrap(e, ticker) from e
    if df is None or len(df) == 0:
        raise NotFound(f"Yahoo has no data for {ticker}")
    return df


class YFinance(BaseSource):
    name = "yfinance"
    label = "Yahoo Finance"
    description = "Yahoo Finance: split-adjusted prices, splits, the Nifty 500 index and basic fundamentals."
    homepage = "https://finance.yahoo.com"
    capabilities = (
        CapabilitySpec(
            "bars",
            "by_symbol",
            (
                JobVariant(
                    schedule={"kind": "daily", "at_time": "20:30", "weekdays_only": 1},
                    refresh=True,
                ),
            ),
            adjusted=True,
        ),
        CapabilitySpec(
            "actions",
            "by_symbol",
            (JobVariant(schedule={"kind": "weekly", "weekday": 5, "at_time": "10:00"}, min_age_hours=144),),
        ),
        CapabilitySpec(
            "fundamentals",
            "by_symbol",
            (JobVariant(schedule={"kind": "weekly", "weekday": 6, "at_time": "10:00"}, min_age_hours=144),),
        ),
        CapabilitySpec(
            "index",
            "whole",
            (JobVariant(schedule={"kind": "daily", "at_time": "20:15", "weekdays_only": 1}, refresh=True),),
        ),
    )

    def bars_for_symbol(self, symbol: str, start: date, end: date) -> list[Bar]:
        df = _history(f"{symbol}.NS", start, end)
        bars = []
        for ts, row in df.iterrows():
            o, h, lo, c = (_num(row.get(k)) for k in ("Open", "High", "Low", "Close"))
            if None in (o, h, lo, c):
                continue
            vol = _num(row.get("Volume"))
            if not vol and o == h == lo == c:  # invented flat bar on an NSE holiday
                continue
            bars.append(Bar(symbol.upper(), _to_date(ts).isoformat(), o, h, lo, c, vol))
        if not bars:
            raise NotFound(f"Yahoo returned no usable rows for {symbol}")
        return bars

    def actions(self, symbol: str) -> list[Action]:
        _throttle()
        try:
            splits = _ticker(f"{symbol}.NS").splits
        except Exception as e:
            raise _wrap(e, f"{symbol} splits") from e
        out = []
        for ts, ratio in (splits.items() if splits is not None else []):
            r = _num(ratio)
            if r is None or r <= 0:
                continue
            subject = f"Split {r:g}:1 (Yahoo)"
            if r > 1:
                out.append(Action(symbol.upper(), _to_date(ts).isoformat(), subject, "split", 1 / r))
            elif r < 1:  # reverse split: not adjusted in v1
                out.append(Action(symbol.upper(), _to_date(ts).isoformat(), subject, "unparsed", None))
        return out

    def fundamentals(self, symbol: str) -> FundSnapshot:
        _throttle()
        try:
            info = _ticker(f"{symbol}.NS").info
        except Exception as e:
            raise _wrap(e, f"{symbol} fundamentals") from e
        fields: dict[str, float | str | None] = {}
        raw: dict = {}
        for key, (field, convert) in _INFO_MAP.items():
            v = _num((info or {}).get(key))
            fields[field] = None if v is None else convert(v)
            if v is not None:
                raw[key] = v
        for key, field in _INFO_TEXT.items():
            text = (info or {}).get(key)
            fields[field] = text.strip() if isinstance(text, str) and text.strip() else None
            if fields[field]:
                raw[key] = fields[field]
        if not raw:
            raise NotFound(f"Yahoo has no fundamentals for {symbol}")
        return FundSnapshot(symbol.upper(), fields, {"raw_keys": raw})

    def index_bars(self, index_name: str, start: date) -> list[IndexBar]:
        ticker = INDEX_TICKERS.get(index_name)
        if ticker is None:
            raise NotFound(f"no Yahoo ticker for index {index_name}")
        df = _history(ticker, start, config_today())
        out = []
        for ts, row in df.iterrows():
            c = _num(row.get("Close"))
            if c is not None and c > 0:
                out.append(IndexBar(index_name, _to_date(ts).isoformat(), c))
        if not out:
            raise NotFound(f"Yahoo returned no usable rows for {index_name}")
        return out


def config_today() -> date:
    from app import timeutil

    return timeutil.today()


registry.register(YFinance())
