"""Cross-check prices between two sources and flag suspicious jumps (SPEC §7.3)."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date

import pandas as pd

from app import bardb, db, timeutil
from app.analytics import adjust, frames
from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register
from app.sources import registry as sources

log = logging.getLogger(__name__)

WINDOW = 400  # common dates compared
MISMATCH_TOLERANCE = 0.02
MIN_STREAK = 4  # "more than 3 consecutive days"
GAP_LIMIT = 0.35
GAP_ACTION_DAYS = 3
JUMP_LIMIT = 0.15
JUMP_LOOKAHEAD_DAYS = 5
JUMP_FACTOR_DAYS = 2


def find_mismatches(primary: pd.Series, other: pd.Series, window: int | None = WINDOW) -> list[dict]:
    """One dict per streak of >3 consecutive common days where the sources differ by more than 2%.

    `date` is the first day of the streak. `ratio` is the median primary/other over the streak and
    `suggested_factor` its inverse (what to multiply the primary's earlier prices by). `ex_date` is the
    first day after the streak, or None if the streak runs to the end of the data. `window=None`
    compares every common date.
    """
    both = pd.concat({"p": primary, "o": other}, axis=1).dropna()
    if window is not None:
        both = both.tail(window)
    both = both[both["o"] > 0]
    if both.empty:
        return []
    ratio = both["p"] / both["o"]
    bad = ((ratio - 1).abs() > MISMATCH_TOLERANCE).tolist()
    dates = list(both.index)
    out: list[dict] = []
    i = 0
    while i < len(bad):
        if not bad[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(bad) and bad[j + 1]:
            j += 1
        if j - i + 1 >= MIN_STREAK:
            med = float(ratio.iloc[i : j + 1].median())
            out.append(
                {
                    "date": dates[i].date().isoformat(),
                    "end": dates[j].date().isoformat(),
                    "ratio": med,
                    "suggested_factor": round(1 / med, 4) if med > 0 else None,
                    "ex_date": dates[j + 1].date().isoformat() if j + 1 < len(dates) else None,
                }
            )
        i = j + 1
    return out


def find_gaps(adj_close: pd.Series, action_dates: list[str], window: int | None = WINDOW) -> list[dict]:
    """Days where the adjusted close moved >35% with no split/bonus within ±3 days.

    `window=None` scans the whole series.
    """
    s = adj_close.dropna()
    if window is not None:
        s = s.tail(window + 1)
    change = s.pct_change().dropna()
    actions = [date.fromisoformat(a) for a in action_dates]
    out = []
    for ts, ch in change.items():
        if abs(ch) <= GAP_LIMIT:
            continue
        d = ts.date()
        if any(abs((d - a).days) <= GAP_ACTION_DAYS for a in actions):
            continue
        out.append({"date": d.isoformat(), "change_pct": round(float(ch) * 100, 1)})
    return out


def find_adjustment_jumps(adj: pd.DataFrame, factors: list[tuple[str, float]],
                          window: int | None = WINDOW) -> list[dict]:  # fmt: skip
    """Ex-dates where the adjusted open AND close both jump by more than 15% (SPEC §7.3).

    `adj` is the adjusted OHLC frame. `window` limits ex-dates to the last `window + 1` bars
    (None = all). `suggested_factor` is the whole factor that would remove the jump.
    """
    if adj.empty:
        return []
    start = None if window is None else adj.index[-min(len(adj), window + 1)]
    out: list[dict] = []
    for ex in sorted({e for e, _ in factors}):
        ex_ts = pd.Timestamp(ex)
        if start is not None and ex_ts < start:
            continue
        before = adj[adj.index < ex_ts]
        after = adj[(adj.index >= ex_ts) & (adj.index <= ex_ts + pd.Timedelta(days=JUMP_LOOKAHEAD_DAYS))]
        if before.empty or after.empty:
            continue
        prev_close = float(before["close"].iloc[-1])
        ex_open, ex_close = float(after["open"].iloc[0]), float(after["close"].iloc[0])
        if prev_close <= 0 or ex_open <= 0 or ex_close <= 0:
            continue
        open_move, close_move = ex_open / prev_close - 1, ex_close / prev_close - 1
        if abs(open_move) <= JUMP_LIMIT or abs(close_move) <= JUMP_LIMIT:
            continue
        applied = 1.0
        for e, f in factors:
            if abs((pd.Timestamp(e) - ex_ts).days) <= JUMP_FACTOR_DAYS:
                applied *= f
        use_close = abs(ex_close / ex_open - 1) > JUMP_LIMIT
        ratio = ex_close / prev_close if use_close else ex_open / prev_close
        out.append(
            {
                "date": ex,
                "applied_factor": round(applied, 4),
                "open_move_pct": round(open_move * 100, 1),
                "close_move_pct": round(close_move * 100, 1),
                "suggested_factor": round(applied * ratio, 4),
            }
        )
    return out


def _adjusted_close(symbol: str, source: str, conn: sqlite3.Connection) -> pd.Series:
    df = adjust.load_raw(symbol, source, conn)
    spec = sources.spec(source, "bars")
    if spec is not None and spec.adjusted is False:
        df = adjust.apply_factors(df, adjust.adjustment_factors(symbol, conn))
    return df["close"]


def _has_bars(symbol: str, source: str, conn: sqlite3.Connection) -> bool:
    q = "SELECT 1 FROM bars WHERE source_id=" + bardb.SRC_ID + " AND sym_id=" + bardb.SYM_ID + " LIMIT 1"
    return conn.execute(q, (source, symbol)).fetchone() is not None


def _insert(conn: sqlite3.Connection, symbol: str, found: list[tuple], window: int | None,
            prim_close: pd.Series) -> int:  # fmt: skip
    """Store the new checks and close the resolved ones; returns the number of new check rows.

    Every read comes before every write, so on the cloud replica the reads stay local and the writes go
    out in one batch at COMMIT (docs/CLOUD_SPIKE.md, "First drain").
    """
    existing = {
        (r["date"], r["kind"])
        for r in conn.execute("SELECT date, kind FROM price_checks WHERE symbol=?", (symbol,))
    }
    fresh: dict[tuple[str, str], tuple] = {}
    for d, kind, primary, other, detail in found:
        if (d, kind) not in existing:
            row = (symbol, d, kind, primary, other, json.dumps(detail), timeutil.now_iso())
            fresh.setdefault((d, kind), row)
    _close_resolved(conn, symbol, prim_close, {(f[0], f[1]) for f in found}, window)
    if fresh:
        conn.executemany(
            "INSERT OR IGNORE INTO price_checks(symbol, date, kind, primary_source, other_source, detail, "
            "created_at) VALUES (?,?,?,?,?,?,?)",
            list(fresh.values()),
        )
    return len(fresh)


def check_symbol(symbol: str, conn: sqlite3.Connection, window: int | None = WINDOW) -> int:
    """Run both checks for one symbol; returns the number of new check rows."""
    ordered = [s.name for s in sources.ordered("bars", conn)]
    primary = frames.bars_source(symbol, conn)
    if primary is None:
        return 0
    prim_close = _adjusted_close(symbol, primary, conn)
    found: list[tuple] = []  # (date, kind, primary, other, detail)
    others = [n for n in ordered if n != primary and _has_bars(symbol, n, conn)]
    if others:
        other = others[0]
        for m in find_mismatches(prim_close, _adjusted_close(symbol, other, conn), window):
            detail = {k: m[k] for k in ("ratio", "suggested_factor", "end", "ex_date")}
            found.append((m["date"], "mismatch", primary, other, detail))
    action_dates = [
        r["ex_date"]
        for r in conn.execute(
            "SELECT DISTINCT ex_date FROM corp_actions WHERE symbol=? AND kind IN ('split','bonus')",
            (symbol,),
        )
    ]
    for g in find_gaps(prim_close, action_dates, window):
        found.append((g["date"], "unexplained_gap", primary, None, {"change_pct": g["change_pct"]}))
    spec = sources.spec(primary, "bars")
    if spec is not None and spec.adjusted is False:
        factors = adjust.adjustment_factors(symbol, conn)
        adj = adjust.apply_factors(adjust.load_raw(symbol, primary, conn), factors)
        for j in find_adjustment_jumps(adj, factors, window):
            keys = ("applied_factor", "open_move_pct", "close_move_pct", "suggested_factor")
            found.append((j["date"], "adjustment_jump", primary, None, {k: j[k] for k in keys}))
    return _insert(conn, symbol, found, window, prim_close)


def _close_resolved(conn: sqlite3.Connection, symbol: str, prim_close: pd.Series,
                    found: set[tuple[str, str]], window: int | None = WINDOW) -> int:  # fmt: skip
    """Mark open checks 'fixed' when a fresh check over the same window no longer finds them.

    Only dates inside the window both checks just covered are touched, so older checks stay put.
    `window=None` covers the whole series, so open checks at any date can close.
    """
    s = prim_close.dropna()
    if s.empty:
        return 0
    since = s.index[0 if window is None else -min(len(s), window + 1)].date().isoformat()
    rows = conn.execute(
        "SELECT id, date, kind FROM price_checks WHERE symbol=? AND status='open' AND date>=?",
        (symbol, since),
    ).fetchall()
    stale = [r["id"] for r in rows if (r["date"], r["kind"]) not in found]
    conn.executemany("UPDATE price_checks SET status='fixed' WHERE id=?", [(i,) for i in stale])
    return len(stale)


def run_checks(ctx: JobContext, window: int | None) -> str | None:
    with db.tx() as c:
        symbols = frames.universe(c)
    ctx.set_total(len(symbols))
    total_new = 0
    for sym in symbols:
        ctx.check_stop()
        try:
            with db.tx() as c:
                n = check_symbol(sym, c, window)
        except Exception as e:  # one symbol failing never fails the run
            log.warning("price check failed for %s: %s", sym, e)
            ctx.item(sym, "failed", f"{type(e).__name__}: {e}")
            continue
        total_new += n
        ctx.item(sym, "ok", f"{n} new checks" if n else "clean")
    return f"{len(symbols)} symbols checked, {total_new} new issues"


def run(ctx: JobContext) -> str | None:
    return run_checks(ctx, WINDOW)


register(
    JobDef(
        name="price_checks",
        title="Price checks",
        description="Compares prices between two sources and flags missed splits, bonuses and odd jumps.",
        fn=run,
        default_schedule={"kind": "daily", "at_time": "21:00", "weekdays_only": 1},
        stage=4,
    )
)
