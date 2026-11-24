"""Split/bonus adjustment (SPEC §7.2). No source names here: the registry decides everything."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import pandas as pd

from app import bardb, db
from app.analytics import price_store
from app.sources import registry

SAME_EVENT_DAYS = 2
COLUMNS = ["open", "high", "low", "close", "volume"]


@contextmanager
def use_conn(conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """The given connection, or a short-lived one for read-only work."""
    if conn is not None:
        yield conn
        return
    c = db.connect()
    try:
        yield c
    finally:
        c.close()


def _days_apart(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _ordered(kind: str, conn: sqlite3.Connection | None, ref: dict | None) -> list[str]:
    if ref is not None:
        return ref["orders"][kind]
    return [s.name for s in registry.ordered(kind, conn)]


def adjustment_factors(
    symbol: str, conn: sqlite3.Connection | None, include_events: bool = True
) -> list[tuple[str, float]]:
    """(ex_date, factor) for splits and bonuses, merged across sources, sorted by ex_date.

    Demerger/rights `event_factors` (SPEC §7.2a) are added after the merge unless
    `include_events=False` (events.py uses that to avoid circularity).

    Per event the first source in ordered("actions") wins (events within ±2 days are the same
    event). Manual adjustments replace source factors around the same ex_date.
    `conn` may be None only while the price store is validated (`frames.load_frame`).
    """
    ref = price_store.current()
    accepted: list[tuple[str, float, int]] = []  # (ex_date, factor, source rank)
    for rank, name in enumerate(_ordered("actions", conn, ref)):
        if ref is not None:
            rows = ref["actions"].get((name, symbol), [])
        else:
            rows = [
                (r[0], r[1])
                for r in conn.execute(
                    "SELECT ex_date, factor FROM corp_actions WHERE source=? AND symbol=? "
                    "AND kind IN ('split','bonus') AND factor IS NOT NULL ORDER BY ex_date",
                    (name, symbol),
                )
            ]
        earlier = [a for a in accepted if a[2] < rank]
        for ex_date, factor in rows:
            if any(_days_apart(a[0], ex_date) <= SAME_EVENT_DAYS for a in earlier):
                continue
            accepted.append((ex_date, factor, rank))
    merged: dict[str, float] = {}
    for ex, f, _ in accepted:
        merged[ex] = merged.get(ex, 1.0) * f
    if include_events:
        if ref is not None:
            events = ref["events"].get(symbol, [])
        else:
            events = [
                (e[0], e[1])
                for e in conn.execute(
                    "SELECT ex_date, factor FROM event_factors WHERE symbol=? AND factor IS NOT NULL",
                    (symbol,),
                )
            ]
        for ex_date, factor in events:
            merged[ex_date] = merged.get(ex_date, 1.0) * factor
    if ref is not None:
        manual = ref["manual"].get(symbol, [])
    else:
        manual = [
            (m[0], m[1])
            for m in conn.execute("SELECT ex_date, factor FROM manual_adjustments WHERE symbol=?", (symbol,))
        ]
    for m_date, m_factor in manual:
        for ex in [e for e in merged if _days_apart(e, m_date) <= SAME_EVENT_DAYS]:
            del merged[ex]
        merged[m_date] = m_factor
    return sorted(merged.items())


MAX_LINEAGE_STEPS = 10


def _latest_change(
    conn: sqlite3.Connection | None, ref: dict | None, cur: str, names: list[str], bound: str | None
) -> tuple[str, str] | None:
    """(old_symbol, effective_date) of the newest rename into `cur` on or before `bound`."""
    if ref is not None:
        for eff, old, source in ref["changes"].get(cur, []):  # newest first
            if source in names and (bound is None or eff <= bound):
                return old, eff
        return None
    marks = ",".join("?" * len(names))
    sql = (
        "SELECT old_symbol, effective_date FROM symbol_changes "
        f"WHERE new_symbol=? AND source IN ({marks})"
    )
    args: list[str] = [cur, *names]
    if bound is not None:
        sql += " AND effective_date <= ?"
        args.append(bound)
    row = conn.execute(sql + " ORDER BY effective_date DESC LIMIT 1", args).fetchone()
    return None if row is None else (row["old_symbol"], row["effective_date"])


def lineage(symbol: str, conn: sqlite3.Connection | None) -> list[tuple[str, str | None, str | None]]:
    """[(ticker, from_date, until_date)], oldest first, `symbol` last (SPEC §7.4).

    from_date is inclusive, until_date exclusive, None = open.
    `conn` may be None only while the price store is validated.
    """
    ref = price_store.current()
    names = [*_ordered("symbol_changes", conn, ref), "manual"]
    segments: list[tuple[str, str | None, str | None]] = []
    cur, until, bound = symbol, None, None
    seen = {symbol}
    for _ in range(MAX_LINEAGE_STEPS):
        found = _latest_change(conn, ref, cur, names, bound)
        if found is None:
            break
        old, eff = found
        segments.append((cur, eff, until))
        if old in seen:
            segments.reverse()
            return segments
        seen.add(old)
        cur, until, bound = old, eff, eff
    segments.append((cur, None, until))
    segments.reverse()
    return segments


def _read_bars(
    source: str, ticker: str, frm: str | None, until: str | None, conn: sqlite3.Connection
) -> list[sqlite3.Row]:
    sql = f"SELECT {bardb.OHLCV_SQL} FROM bars WHERE source_id={bardb.SRC_ID} AND sym_id={bardb.SYM_ID}"
    args: list[str | int] = [source, ticker]
    if frm is not None:
        sql += " AND day >= ?"
        args.append(bardb.day(frm))
    if until is not None:
        sql += " AND day < ?"
        args.append(bardb.day(until))
    return conn.execute(sql + " ORDER BY day", args).fetchall()


def _has_bars(source: str, ticker: str, conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM bars WHERE source_id=" + bardb.SRC_ID + " AND sym_id=" + bardb.SYM_ID + " LIMIT 1",
        (source, ticker),
    ).fetchone()
    return row is not None


def _load_raw_stored(symbol: str, source: str, conn: sqlite3.Connection, ctx: dict) -> pd.DataFrame:
    """`load_raw` from the price store: the same rows, sliced per segment like `_read_bars`."""
    fresh = ctx["fresh"]
    *older, current = lineage(symbol, conn)
    segments = [seg for seg in older if (source, seg[0]) in fresh] + [current]
    if len(segments) == 1:
        return price_store.raw_frame(source, symbol, conn).copy()
    parts = []
    for ticker, frm, until in segments:
        df = price_store.raw_frame(source, ticker, conn)
        keep = pd.Series(True, index=df.index)
        if frm is not None:
            keep &= df.index >= pd.Timestamp(frm)
        if until is not None:
            keep &= df.index < pd.Timestamp(until)
        parts.append(df[keep.to_numpy()])
    df = pd.concat(parts)
    return df[~df.index.duplicated(keep="last")]


def load_raw(symbol: str, source: str, conn: sqlite3.Connection) -> pd.DataFrame:
    ctx = price_store.current()
    if ctx is not None:
        return _load_raw_stored(symbol, source, conn, ctx)
    *older, current = lineage(symbol, conn)
    segments = [seg for seg in older if _has_bars(source, seg[0], conn)] + [current]
    if len(segments) == 1:
        rows = conn.execute(
            "SELECT " + bardb.OHLCV_SQL + " FROM bars WHERE source_id=" + bardb.SRC_ID
            + " AND sym_id=" + bardb.SYM_ID + " ORDER BY day",
            (source, symbol),
        ).fetchall()
    else:
        rows = []
        for ticker, frm, until in segments:
            rows.extend(_read_bars(source, ticker, frm, until, conn))
    df = price_store.rows_to_frame(rows)
    if len(segments) > 1:
        df = df[~df.index.duplicated(keep="last")]
    return df


def apply_factors(df: pd.DataFrame, factors: list[tuple[str, float]]) -> pd.DataFrame:
    """Prices before each ex_date × factor, volume ÷ factor."""
    df = df.copy()
    for ex, f in factors:
        before = df.index < pd.Timestamp(ex)
        df.loc[before, ["open", "high", "low", "close"]] *= f
        df.loc[before, "volume"] /= f
    return df


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([])).astype(float)


def adjusted_ohlcv(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> tuple[pd.DataFrame, str]:
    """(frame, source). Frame: DatetimeIndex, float columns open, high, low, close, volume."""
    from app.analytics import frames

    with use_conn(conn) as c:
        source = frames.bars_source(symbol, c)
        if source is None:
            return empty_frame(), ""
        df = load_raw(symbol, source, c)
        spec = registry.spec(source, "bars")
        if spec is not None and spec.adjusted is False:
            df = apply_factors(df, adjustment_factors(symbol, c))
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return df, source
