"""Demerger and rights adjustment factors (SPEC §7.2a). No source names here."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, timedelta

import pandas as pd

from app import bardb, timeutil
from app.analytics import adjust, frames
from app.sources import registry

log = logging.getLogger(__name__)

SAME_EVENT_DAYS = 2
MIN_DATES = 5
WINDOW = 10
STEP_LOW, STEP_HIGH = 0.05, 0.995
OPEN_LOW, OPEN_HIGH = 0.05, 0.97
OPEN_LOOKAHEAD_DAYS = 5
GUARD_MOVE = 0.10
OPEN_SANITY = 0.15
CLOSE_LOW, CLOSE_HIGH = 0.05, 0.97


def _primary_frame(symbol: str, conn: sqlite3.Connection) -> tuple[str | None, pd.DataFrame]:
    """Primary bars adjusted for splits/bonuses/manual only (never event factors)."""
    source = frames.bars_source(symbol, conn)
    if source is None:
        return None, pd.DataFrame()
    df = adjust.load_raw(symbol, source, conn)
    spec = registry.spec(source, "bars")
    if spec is not None and spec.adjusted is False:
        df = adjust.apply_factors(df, adjust.adjustment_factors(symbol, conn, include_events=False))
    return source, df


def _reference_close(symbol: str, primary: str, conn: sqlite3.Connection) -> tuple[str | None, pd.Series]:
    names = [s.name for s in registry.ordered("bars", conn)]
    if primary not in names:
        return None, pd.Series(dtype=float)
    for name in names[names.index(primary) + 1 :]:
        spec = registry.spec(name, "bars")
        if spec is None or spec.adjusted is not True:
            continue
        q = "SELECT 1 FROM bars WHERE source_id=" + bardb.SRC_ID + " AND sym_id=" + bardb.SYM_ID + " LIMIT 1"
        if conn.execute(q, (name, symbol)).fetchone():
            return name, adjust.load_raw(symbol, name, conn)["close"]
    return None, pd.Series(dtype=float)


def _by_reference(prim: pd.Series, ref: pd.Series, ex: pd.Timestamp) -> tuple[float | None, dict]:
    both = pd.concat({"p": prim, "r": ref}, axis=1).dropna()
    both = both[both["r"] > 0]
    ratio = both["p"] / both["r"]
    b = ratio[ratio.index < ex].tail(WINDOW)
    a = ratio[ratio.index >= ex].head(WINDOW)
    detail: dict = {"n_before": len(b), "n_after": len(a)}
    if len(b) < MIN_DATES or len(a) < MIN_DATES:
        return None, detail
    before, after = float(b.median()), float(a.median())
    detail.update(before=before, after=after)
    if before <= 0:
        return None, detail
    step = after / before
    return (step if STEP_LOW < step < STEP_HIGH else None), detail


def _ex_day(df: pd.DataFrame, ex: pd.Timestamp) -> tuple[float, float, float] | None:
    """(prev_close, ex_open, ex_close) around the ex-date, or None."""
    prev = df[df.index < ex]
    nxt = df[(df.index >= ex) & (df.index <= ex + pd.Timedelta(days=OPEN_LOOKAHEAD_DAYS))]
    if prev.empty or nxt.empty:
        return None
    prev_close = float(prev["close"].iloc[-1])
    if prev_close <= 0:
        return None
    return prev_close, float(nxt["open"].iloc[0]), float(nxt["close"].iloc[0])


def _by_open(df: pd.DataFrame, ex: pd.Timestamp) -> tuple[float | None, dict]:
    day = _ex_day(df, ex)
    if day is None:
        return None, {}
    prev_close, opened, closed = day
    detail = {"open": opened, "prev_close": prev_close}
    factor = opened / prev_close
    if not OPEN_LOW < factor <= OPEN_HIGH:
        return None, detail
    if opened <= 0 or abs(closed / opened - 1) > OPEN_SANITY:
        return None, detail
    return factor, detail


def _by_close(df: pd.DataFrame, ex: pd.Timestamp) -> tuple[float | None, dict]:
    day = _ex_day(df, ex)
    if day is None:
        return None, {}
    prev_close, opened, closed = day
    detail = {"open": opened, "prev_close": prev_close, "close": closed}
    open_factor = opened / prev_close
    in_range = OPEN_LOW < open_factor <= OPEN_HIGH
    if not in_range or (opened > 0 and abs(closed / opened - 1) <= OPEN_SANITY):
        return None, detail
    factor = closed / prev_close
    return (factor if CLOSE_LOW < factor <= CLOSE_HIGH else None), detail


def _guard(df: pd.DataFrame, ex: pd.Timestamp, factor: float) -> tuple[bool, dict]:
    """Does the adjusted ex-date move stay plausible? Returns (passes, {open_move, close_move})."""
    day = _ex_day(df, ex)
    if day is None:
        return True, {}
    prev_close, opened, closed = day
    base = prev_close * factor
    om, cm = opened / base - 1, closed / base - 1
    moves = {"open_move": round(om, 4), "close_move": round(cm, 4)}
    return min(abs(om), abs(cm)) <= GUARD_MOVE, moves


def compute_event_factor(
    symbol: str, ex_date: str, kind: str, conn: sqlite3.Connection
) -> tuple[float | None, str, dict]:
    """(factor, method, detail); method is 'reference', 'open', 'close' or 'none'."""
    primary, df = _primary_frame(symbol, conn)
    if primary is None or df.empty:
        return None, "none", {}
    ex = pd.Timestamp(ex_date)
    detail: dict = {}
    ref_name, ref_close = _reference_close(symbol, primary, conn)
    if ref_name is not None:
        factor, d = _by_reference(df["close"], ref_close, ex)
        detail.update(d)
        detail["reference"] = ref_name
        if factor is not None:
            ok, moves = (True, {}) if kind != "demerger" else _guard(df, ex, factor)
            if ok:
                return factor, "reference", detail
            detail["rejected"] = "reference"
            detail.update(moves)
    if kind == "demerger":
        for method, fn in (("open", _by_open), ("close", _by_close)):
            factor, d = fn(df, ex)
            detail.update(d)
            if factor is not None:
                return factor, method, detail
    return None, "none", detail


def _events(conn: sqlite3.Connection, symbols: list[str]) -> list[tuple[str, str, str]]:
    """(symbol, ex_date, kind), deduplicated per (symbol, kind) within ±2 days, earliest wins."""
    out: list[tuple[str, str, str]] = []
    for sym in symbols:
        rows = conn.execute(
            "SELECT DISTINCT kind, ex_date FROM corp_actions "
            "WHERE symbol=? AND kind IN ('demerger','rights') ORDER BY kind, ex_date",
            (sym,),
        ).fetchall()
        last: dict[str, date] = {}
        for r in rows:
            d = date.fromisoformat(r["ex_date"])
            if r["kind"] in last and d - last[r["kind"]] <= timedelta(days=SAME_EVENT_DAYS):
                continue
            last[r["kind"]] = d
            out.append((sym, r["ex_date"], r["kind"]))
    return out


def refresh_event_factors(conn: sqlite3.Connection, symbols: list[str] | None = None) -> int:
    """Delete and recompute event_factors for `symbols` (default: the universe); returns rows written."""
    syms = symbols if symbols is not None else frames.universe(conn)
    for sym in syms:
        conn.execute("DELETE FROM event_factors WHERE symbol=?", (sym,))
    now = timeutil.now_iso()
    n = 0
    for sym, ex, kind in _events(conn, syms):
        factor, method, detail = compute_event_factor(sym, ex, kind, conn)
        conn.execute(
            "INSERT INTO event_factors(symbol, ex_date, kind, factor, method, detail, computed_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (sym, ex, kind, factor, method, json.dumps(detail), now),
        )
        n += 1
    frames.invalidate()
    return n
