"""Clean, adjusted daily frames from the best available source (SPEC §7.4)."""

from __future__ import annotations

import hashlib
import math
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import Any

import pandas as pd

from app import bardb, config, db
from app.analytics import adjust, indicators, price_store
from app.sources import registry

INDEX_NAME = "NIFTY 500"
# ~124 KB each. Must exceed the liquid500-from-2012 set (~1,700 symbols), or a full scan
# evicts every frame before it is reused.
CACHE_SIZE = 2500
# Vercel mode (SPEC §17.2): every price-derived cache entry lives at most this long, because another
# process (the cloud worker) writes new prices and nothing tells this one.
VERCEL_CACHE_TTL_S = 300

_cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
_breadth: dict[tuple, pd.Series] = {}
_results: dict[tuple, list[pd.Timestamp]] = {}
_industry_returns: dict[tuple, pd.DataFrame] = {}
_industries: dict[str, str | None] = {}
_memo: dict[str, Any] = {}
_lock = threading.Lock()
_extra_caches: list[dict] = []  # caches in other modules that are derived from prices
_cleared_at = time.monotonic()


def register_cache(cache: dict) -> dict:
    """Have `invalidate()` clear `cache` too; returns it."""
    _extra_caches.append(cache)
    return cache


register_cache(price_store.holder)  # invalidate() forces the price store to re-validate
register_cache(registry.ordered_cache)  # vercel's cached source orders (priority or on/off changed)

BREADTH_MIN_STOCKS = 20
INDUSTRY_MIN_STOCKS = 3
MARKET_MIN_STOCKS = 20
MARKET_COLUMN = "__market__"


def invalidate() -> None:
    """Call after any write that changes prices, actions, priorities or manual adjustments.

    Clears now and again when the caller's open `db.tx()` commits: a load on another thread between
    the two would otherwise cache (and, with the price store, trust) the pre-commit rows.
    """
    _clear()
    db.after_commit(_clear)


def _clear() -> None:
    global _cleared_at
    with _lock:
        _cache.clear()
        _breadth.clear()
        _results.clear()
        _industry_returns.clear()
        _industries.clear()
        _memo.clear()
        _cleared_at = time.monotonic()
    indicators.clear_memo()
    for cache in _extra_caches:
        cache.clear()


def _expire() -> None:
    """Vercel mode: drop every price-derived cache once it is `VERCEL_CACHE_TTL_S` old (SPEC §17.2)."""
    if config.RUNTIME == "vercel" and time.monotonic() - _cleared_at > VERCEL_CACHE_TTL_S:
        _clear()


def memo(key: str, fn: Callable[[], Any]) -> Any:
    """`fn()`, reused for up to `VERCEL_CACHE_TTL_S` in vercel mode, so a page polled every few seconds
    doesn't re-read Turso each time. Locally (and in the drain) always fresh. Cleared by `invalidate()`."""
    if config.RUNTIME != "vercel":
        return fn()
    _expire()
    with _lock:
        if key in _memo:
            return _memo[key]
    value = fn()
    with _lock:
        _memo[key] = value
    return value


def bars_source(symbol: str, conn: sqlite3.Connection | None = None) -> str | None:
    """First enabled bars source (in priority order) that has any bars for `symbol`."""
    ctx = price_store.current()
    if ctx is not None:
        return next((s for s in ctx["orders"]["bars"] if (s, symbol) in ctx["fresh"]), None)
    with adjust.use_conn(conn) as c:
        for src in registry.ordered("bars", c):
            q = f"SELECT 1 FROM bars WHERE source_id={bardb.SRC_ID} AND sym_id={bardb.SYM_ID} LIMIT 1"
            if c.execute(q, (src.name, symbol)).fetchone():
                return src.name
    return None


def _tag(key: tuple) -> str:
    """Short cache tag: pandas deep-copies `attrs` on every slice, so a tuple there is costly."""
    return hashlib.blake2b(repr(key).encode(), digest_size=10).hexdigest()


def _validated() -> dict | None:
    _expire()
    ctx = price_store.current()
    if ctx is None and price_store.enabled():
        with adjust.use_conn(None) as c:
            ctx = price_store.ensure_valid(c)
    return ctx


def _load_stored(symbol: str, start: str | None, ctx: dict) -> pd.DataFrame:
    """`load_frame` with the freshness table: a cache hit makes no SQL query at all."""
    fresh = ctx["fresh"]
    source = bars_source(symbol)
    if source is None:
        df = adjust.empty_frame()
        df.attrs["source"] = ""
        df.attrs["symbol"] = symbol.upper()
        return df
    lin = tuple(adjust.lineage(symbol, None))
    factors = tuple(adjust.adjustment_factors(symbol, None))
    key = (symbol, start, source, fresh[(source, symbol)], factors, lin,
           tuple(fresh.get((source, t)) for t, _, _ in lin))  # fmt: skip
    tag = _tag(key)
    with _lock:
        hit = _cache.get(tag)
        if hit is not None:
            _cache.move_to_end(tag)
            return hit.copy()
    with adjust.use_conn(None) as c:
        df, source = adjust.adjusted_ohlcv(symbol, start, None, c)
    df.attrs["source"] = source
    df.attrs["symbol"] = symbol.upper()
    df.attrs["cache_key"] = tag  # lets indicators.compute memoise results for this exact frame
    with _lock:
        _cache[tag] = df
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return df.copy()


def load_frame(symbol: str, start: str | None = None) -> pd.DataFrame:
    """Adjusted bars; `frame.attrs["source"]` is the bars source ("" and an empty frame if none)."""
    ctx = _validated()
    if ctx is not None:
        return _load_stored(symbol, start, ctx)
    with adjust.use_conn(None) as c:
        source = bars_source(symbol, c)
        if source is None:
            df, _ = adjust.adjusted_ohlcv(symbol, start, None, c)
            df.attrs["source"] = ""
            df.attrs["symbol"] = symbol.upper()
            return df
        mx, n = c.execute(
            f"SELECT MAX(day), COUNT(*) FROM bars WHERE source_id={bardb.SRC_ID} AND sym_id={bardb.SYM_ID}",
            (source, symbol),
        ).fetchone()
        factors = tuple(adjust.adjustment_factors(symbol, c))
        key = (symbol, start, source, mx, n, factors, tuple(adjust.lineage(symbol, c)))
        tag = _tag(key)
        with _lock:
            hit = _cache.get(tag)
            if hit is not None:
                _cache.move_to_end(tag)
                return hit.copy()
        df, source = adjust.adjusted_ohlcv(symbol, start, None, c)
    df.attrs["source"] = source
    df.attrs["symbol"] = symbol.upper()
    df.attrs["cache_key"] = tag
    with _lock:
        _cache[tag] = df
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return df.copy()


def results_dates(symbol: str) -> list[pd.Timestamp]:
    """First day the market could trade on each quarterly result (point-in-time, SPEC §9.4)."""
    from app.analytics import fundamentals  # lazy: keeps module import order simple

    _expire()
    symbol = symbol.upper()
    with adjust.use_conn(None) as c:
        n = c.execute("SELECT COUNT(*) FROM quarters WHERE symbol=?", (symbol,)).fetchone()[0]
        key = (symbol, n)
        with _lock:
            hit = _results.get(key)
        if hit is not None:
            return list(hit)
        out = [pd.Timestamp(d) for d in fundamentals.known_on_dates(symbol, c)]
    with _lock:
        _results[key] = out
    return list(out)


def load_benchmark(start: str | None = None) -> pd.Series:
    """Nifty 500 closes merged across enabled index sources.

    Per date the first source in priority order wins; lower-priority sources fill dates it lacks
    (a source with only recent days must not cut the history short). `attrs["source"]` is the
    highest-priority source that contributed.
    """
    merged: pd.Series | None = None
    top = ""
    with adjust.use_conn(None) as c:
        for src in registry.ordered("index", c):
            rows = c.execute(
                "SELECT date, close FROM index_bars WHERE source=? AND index_name=? ORDER BY date",
                (src.name, INDEX_NAME),
            ).fetchall()
            if not rows:
                continue
            s = pd.Series(
                [r["close"] for r in rows],
                index=pd.DatetimeIndex(pd.to_datetime([r["date"] for r in rows])),
                dtype=float,
            )
            merged, top = (s, src.name) if merged is None else (merged.combine_first(s), top)
    if merged is None:
        return pd.Series([], index=pd.DatetimeIndex([]), name=INDEX_NAME, dtype=float)
    merged = merged.sort_index().rename(INDEX_NAME)
    merged.attrs["source"] = top
    return merged[merged.index >= pd.Timestamp(start)] if start else merged


def load_breadth(n: int) -> pd.Series:
    """Market breadth: % of today's universe whose close is above its n-day average, per date.

    Uses each stock's adjusted frame, so splits don't count as drops. Dates with fewer than
    `BREADTH_MIN_STOCKS` stocks that have an n-day average are NaN. Cached until prices change.
    """
    _expire()
    symbols = universe()
    key = (n, last_trading_date(), len(symbols))
    with _lock:
        hit = _breadth.get(key)
    if hit is not None:
        return hit.copy()
    closes = {}
    for sym in symbols:
        f = load_frame(sym)
        if len(f):
            closes[sym] = f["close"].astype(float)
    if not closes:
        out = pd.Series([], index=pd.DatetimeIndex([]), dtype=float)
    else:
        df = pd.DataFrame(closes).sort_index()
        avg = df.rolling(n, min_periods=n).mean()
        valid = avg.notna() & df.notna()
        count = valid.sum(axis=1)
        out = ((df > avg) & valid).sum(axis=1) / count.where(count >= BREADTH_MIN_STOCKS) * 100
    out = out.rename("breadth")
    with _lock:
        _breadth.clear()
        _breadth[key] = out
    return out.copy()


def industry_of(symbol: str) -> str | None:
    """`symbols.industry`, stripped; None if empty or unknown. Cached until `invalidate()`."""
    _expire()
    with _lock:
        loaded = bool(_industries)
    if not loaded:
        with adjust.use_conn(None) as c:
            rows = c.execute("SELECT symbol, industry FROM symbols").fetchall()
        fresh = {r["symbol"]: ((r["industry"] or "").strip() or None) for r in rows}
        with _lock:
            _industries.update(fresh)
            _industries.setdefault("", None)  # marks the map as loaded even if the table is empty
    with _lock:
        return _industries.get(symbol.upper())


def load_industry_returns(n: int) -> pd.DataFrame:
    """Per date, median n-day return (%) of each industry's stocks, plus a "__market__" column.

    An industry needs `INDUSTRY_MIN_STOCKS` stocks with a value on a date, the market column
    `MARKET_MIN_STOCKS`; otherwise NaN. Cached per (n, last trading date, universe size).
    """
    _expire()
    symbols = universe()
    key = (n, last_trading_date(), len(symbols))
    with _lock:
        hit = _industry_returns.get(key)
    if hit is not None:
        return hit.copy()
    rets: dict[str, pd.Series] = {}
    for sym in symbols:
        f = load_frame(sym)
        if len(f):
            close = f["close"].astype(float)
            rets[sym] = (close / close.shift(n) - 1) * 100
    if not rets:
        out = pd.DataFrame(index=pd.DatetimeIndex([]), columns=[MARKET_COLUMN], dtype=float)
    else:
        df = pd.DataFrame(rets).sort_index()
        groups: dict[str, list[str]] = {}
        for sym in df.columns:
            name = industry_of(sym)
            if name:
                groups.setdefault(name, []).append(sym)
        cols = {}
        for name, syms in sorted(groups.items()):
            sub = df[syms]
            cols[name] = sub.median(axis=1).where(sub.notna().sum(axis=1) >= INDUSTRY_MIN_STOCKS)
        cols[MARKET_COLUMN] = df.median(axis=1).where(df.notna().sum(axis=1) >= MARKET_MIN_STOCKS)
        out = pd.DataFrame(cols, index=df.index)
    with _lock:
        _industry_returns.clear()
        _industry_returns[key] = out
    return out.copy()


def universe(conn: sqlite3.Connection | None = None) -> list[str]:
    """in_universe symbols ∪ watchlist ∪ open positions, sorted."""
    with adjust.use_conn(conn) as c:
        rows = c.execute(
            "SELECT symbol FROM symbols WHERE in_universe=1 "
            "UNION SELECT symbol FROM watchlist "
            "UNION SELECT symbol FROM positions WHERE status='open' ORDER BY symbol"
        ).fetchall()
    return [r["symbol"] for r in rows]


def last_trading_date(conn: sqlite3.Connection | None = None) -> str | None:
    """Latest bar date of the primary bars source, over universe symbols."""
    with adjust.use_conn(conn) as c:
        ordered = registry.ordered("bars", c)
        if not ordered:
            return None
        row = c.execute(  # one PK lookup per universe symbol, not a join over every bar
            "SELECT MAX((SELECT MAX(b.day) FROM bars b WHERE b.source_id=" + bardb.SRC_ID
            + " AND b.sym_id=y.id)) FROM symbols s JOIN bar_symbols y ON y.symbol=s.symbol "
            "WHERE s.in_universe=1",
            (ordered[0].name,),
        ).fetchone()
    return bardb.iso(row[0])


# ---- light reads for list pages (SPEC §17.5) ---------------------------------------------------

_LATEST = 99991231
_CHUNK = 200  # (symbol, day) pairs per statement: 2 variables each, well under SQLite's limit
Found = tuple[str, int | None, float | None]  # (source, bar day, raw close)


def _raw_closes(wanted: dict[str, int], c: sqlite3.Connection) -> dict[str, Found]:
    """{symbol: (source, bar day, raw close)} of the last bar on or before each wanted day.

    The source is `bars_source`'s choice (the first enabled source with any bars for the symbol), so
    the day/close are None when that source has no bar by then. One statement per chunk of symbols,
    covering every bars source; every lookup is a primary-key seek.
    """
    order = [s.name for s in registry.ordered("bars", c)]
    rank = {name: i for i, name in enumerate(order)}
    best: dict[str, tuple[int, Found]] = {}
    syms = sorted(wanted)
    seek = "FROM bars b WHERE b.source_id = s.id AND b.sym_id = y.id"
    for i in range(0, len(syms) if order else 0, _CHUNK):
        part = syms[i : i + _CHUNK]
        values = ",".join("(?,?)" for _ in part)
        rows = c.execute(
            f"WITH q(symbol, d) AS (VALUES {values}) SELECT q.symbol, s.name, "
            f"(SELECT MAX(b.day) {seek}), "
            f"(SELECT MAX(b.day) {seek} AND b.day <= q.d), "
            f"(SELECT b.close_p / 100.0 {seek} AND b.day <= q.d ORDER BY b.day DESC LIMIT 1) "
            "FROM q JOIN bar_symbols y ON y.symbol = q.symbol "
            f"JOIN bar_sources s ON s.name IN ({','.join('?' * len(order))})",
            [v for sym in part for v in (sym, wanted[sym])] + order,
        ).fetchall()
        for sym, src, any_day, day, close in rows:
            if any_day is not None and (sym not in best or rank[src] < best[sym][0]):
                best[sym] = (rank[src], (src, day, None if close is None else float(close)))
    return {sym: found for sym, (_, found) in best.items()}


def _later_factor(found: dict[str, Found], c: sqlite3.Connection) -> dict[str, float]:
    """{symbol: product of adjustment factors with an ex-date after its bar}, as `apply_factors` would
    scale that bar. Only symbols on an unadjusted source with such an event are read in full, so the
    usual case costs one query."""
    todo = {s: d for s, (src, d, _) in found.items()
            if d is not None and getattr(registry.spec(src, "bars"), "adjusted", None) is False}  # fmt: skip
    if not todo:
        return {}
    first = bardb.iso(min(todo.values()))
    marks = ",".join("?" * len(todo))
    syms = sorted(todo)
    rows = c.execute(
        f"SELECT symbol FROM corp_actions WHERE symbol IN ({marks}) AND kind IN ('split','bonus') "
        f"AND factor IS NOT NULL AND ex_date > ? UNION SELECT symbol FROM event_factors WHERE symbol IN "
        f"({marks}) AND factor IS NOT NULL AND ex_date > ? UNION SELECT symbol FROM manual_adjustments "
        f"WHERE symbol IN ({marks}) AND ex_date > ?",
        [*syms, first, *syms, first, *syms, first],
    ).fetchall()
    out: dict[str, float] = {}
    for (sym,) in rows:
        day = bardb.iso(todo[sym])
        later = [f for ex, f in adjust.adjustment_factors(sym, c) if ex > day]
        if later:
            out[sym] = math.prod(later)
    return out


def closes_on(days: dict[str, str | None], conn: sqlite3.Connection | None = None) -> dict[str, float | None]:
    """{symbol: adjusted close of the last bar on or before the day (None = the newest bar)}.

    Gives what `load_frame(symbol)` would show for that bar, without loading frames: a few key-seek
    statements in all, so list pages stay light on Vercel (SPEC §17.5). It reads the symbol's own
    ticker only (not the bars of a ticker it was renamed from). None when there is no such bar.
    """
    wanted = {s.upper(): (_LATEST if d is None else bardb.day(d[:10])) for s, d in days.items()}
    if not wanted:
        return {}
    with adjust.use_conn(conn) as c:
        found = _raw_closes(wanted, c)
        factor = _later_factor(found, c)
    out: dict[str, float | None] = {}
    for sym in wanted:
        close = found.get(sym, ("", None, None))[2]
        out[sym] = None if close is None else close * factor.get(sym, 1.0)
    return out


def latest_closes(symbols: Iterable[str], conn: sqlite3.Connection | None = None) -> dict[str, float | None]:
    """{symbol: newest adjusted close} (None without bars); `closes_on` for today."""
    return closes_on({s: None for s in symbols}, conn)
