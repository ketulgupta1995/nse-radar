"""Raw (unadjusted) bars kept on disk, so a cold start doesn't re-read every bar (SPEC §7.4).

The file holds each requested ticker's raw frame plus the completed months of the liquidity
aggregate. One checksum query per validation tells which entries are still right: unchanged ones
are kept, newer bars are appended, anything else is dropped and re-read. The store is an
optimisation only: every failure falls back to plain SQL, and nothing here may fail a backtest.
No source names here: the registry decides the order.
"""

from __future__ import annotations

import logging
import math
import os
import pickle
import sqlite3
import threading

import pandas as pd

from app import bardb, config
from app.sources import registry

log = logging.getLogger(__name__)

VERSION = 3  # 2: dates are bardb days (int YYYYMMDD); 3: prices stored as paise (migration 012)
ENABLED = True  # tests flip this to compare against plain SQL
COLUMNS = ["open", "high", "low", "close", "volume"]
REL_TOL = 1e-9
_IN_CHUNK = 500

Key = tuple[str, str]  # (source, symbol)

_lock = threading.RLock()
# What survives `frames.invalidate()`: the entries and the month sums, tied to one database file.
_store: dict = {"path": None, "order": None, "raw": {}, "months": {}, "seen": {}, "dirty": False}
# What `frames.invalidate()` clears (registered by frames.py): the validated view, under "ctx".
holder: dict = {}


def enabled() -> bool:
    """Off in vercel mode (SPEC §17.2): validating reads every bar, which no request may do."""
    return ENABLED and config.RUNTIME != "vercel"


def current() -> dict | None:
    """The validated view (freshness table, reference data), or None if not validated / disabled."""
    return holder.get("ctx") if enabled() else None


def rows_to_frame(rows) -> pd.DataFrame:
    """Bars as `adjust.load_raw` has always built them: date index, float OHLCV columns."""
    df = pd.DataFrame([tuple(r) for r in rows], columns=["date", *COLUMNS])
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("date").astype(str), format="%Y%m%d"))
    return df.astype(float)


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=1e-6)


def _path():
    return config.DATA_DIR / "cache" / "price_store.pkl"


def _fresh_empty() -> dict:
    return {"path": str(config.DB_PATH), "order": None, "raw": {}, "months": {}, "seen": {}, "dirty": False}


def _load_file(order: list[str]) -> dict:
    """The saved store if it is usable, else an empty one. Never raises."""
    empty = _fresh_empty()
    empty["order"] = order
    try:
        with open(_path(), "rb") as f:
            data = pickle.load(f)
        if data.get("version") != VERSION or data.get("bars_order") != order:
            log.info("price store: version or source order changed, starting empty")
            return empty
        return {
            "path": empty["path"], "order": order, "raw": data["raw"], "months": data["months"],
            "seen": data["seen"], "dirty": False,
        }  # fmt: skip
    except FileNotFoundError:
        return empty
    except Exception as e:
        log.info("price store: unreadable (%s), starting empty", e)
        return empty


def save_if_dirty() -> None:
    """Write the store atomically if anything changed since it was loaded or last saved."""
    with _lock:
        if not enabled() or not _store["dirty"] or _store["path"] != str(config.DB_PATH):
            return
        data = {
            "version": VERSION, "bars_order": _store["order"], "raw": _store["raw"],
            "months": _store["months"], "seen": _store["seen"],
        }  # fmt: skip
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with open(tmp, "wb") as f:
            pickle.dump(data, f, protocol=5)
        os.replace(tmp, path)
        _store["dirty"] = False


def _freshness(conn: sqlite3.Connection) -> dict[Key, tuple[int, str, float]]:
    rows = conn.execute(
        "SELECT s.name, y.symbol, n, mx, chk FROM (SELECT source_id, sym_id, COUNT(*) n, MAX(day) mx, "
        "TOTAL((open_p+high_p+low_p+close_p)/100.0+COALESCE(volume,0)*1e-6) chk "
        "FROM bars GROUP BY source_id, sym_id) b "
        "JOIN bar_sources s ON s.id = b.source_id JOIN bar_symbols y ON y.id = b.sym_id"
    ).fetchall()
    return {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}


def _row_sum(r) -> float:
    """The checksum term of one (source, symbol, date, open, high, low, close, volume) row."""
    if None in r[3:7]:
        return 0.0  # SQL's TOTAL skips a NULL expression
    return r[3] + r[4] + r[5] + r[6] + (r[7] or 0.0) * 1e-6


def _append(fresh: dict, entries: dict[Key, tuple], conn: sqlite3.Connection) -> tuple[set[Key], set[Key]]:
    """Validate raw entries against `fresh`. Returns (dropped keys, changed keys)."""
    dropped: set[Key] = set()
    changed: set[Key] = set()
    todo: dict[Key, tuple] = {}
    for key, (_frame, n, mx, chk) in list(entries.items()):
        cur = fresh.get(key)
        if cur is not None and cur[0] == n and cur[1] == mx and _close(cur[2], chk):
            continue
        if cur is not None and cur[1] > mx and cur[0] > n:
            todo[key] = entries[key]
        else:
            dropped.add(key)
    if todo:
        new_rows: dict[Key, list] = {}
        q = (  # one key seek per changed (source, symbol): bars has no day index
            "SELECT ?, ?, " + bardb.OHLCV_SQL + " FROM bars WHERE source_id=" + bardb.SRC_ID
            + " AND sym_id=" + bardb.SYM_ID + " AND day > ? ORDER BY day"
        )
        for (src, sym), ent in todo.items():
            new_rows[(src, sym)] = conn.execute(q, (src, sym, src, sym, ent[2])).fetchall()
        for key, (frame, n, _mx, chk) in todo.items():
            rows = new_rows.get(key, [])
            cur = fresh[key]
            extra = sum(_row_sum(r) for r in rows)
            if n + len(rows) != cur[0] or not _close(chk + extra, cur[2]):
                dropped.add(key)
                continue
            add = rows_to_frame([(r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows])
            entries[key] = (pd.concat([frame, add]), cur[0], cur[1], cur[2])
            changed.add(key)
    for key in dropped:
        del entries[key]
    return dropped, changed


def _reference(conn: sqlite3.Connection) -> dict:
    """Corporate actions, event factors, manual adjustments and ticker changes, read once."""
    actions: dict[Key, list] = {}
    for r in conn.execute(
        "SELECT source, symbol, ex_date, factor FROM corp_actions WHERE kind IN ('split','bonus') "
        "AND factor IS NOT NULL ORDER BY source, symbol, ex_date, subject"
    ):
        actions.setdefault((r[0], r[1]), []).append((r[2], r[3]))
    events: dict[str, list] = {}
    for r in conn.execute("SELECT symbol, ex_date, factor FROM event_factors WHERE factor IS NOT NULL"):
        events.setdefault(r[0], []).append((r[1], r[2]))
    manual: dict[str, list] = {}
    for r in conn.execute("SELECT symbol, ex_date, factor FROM manual_adjustments ORDER BY symbol, ex_date"):
        manual.setdefault(r[0], []).append((r[1], r[2]))
    changes: dict[str, list] = {}
    for r in conn.execute(
        "SELECT new_symbol, effective_date, old_symbol, source FROM symbol_changes "
        "ORDER BY new_symbol, effective_date DESC"
    ):
        changes.setdefault(r[0], []).append((r[1], r[2], r[3]))
    return {"actions": actions, "events": events, "manual": manual, "changes": changes}


def _rewritten_symbols(fresh: dict, seen: dict, dropped: set[Key]) -> set[str]:
    """Symbols whose stored month sums can't be trusted: an old bar changed, or it was dropped."""
    out = {k[1] for k in dropped}
    for key, (n, mx, chk) in seen.items():
        cur = fresh.get(key)
        if cur is None:
            out.add(key[1])
        elif (cur[0], cur[1]) == (n, mx):
            if not _close(cur[2], chk):
                out.add(key[1])
        elif not (cur[0] > n and cur[1] > mx):
            out.add(key[1])
    return out


def ensure_valid(conn: sqlite3.Connection) -> dict | None:
    """Validate the store against the database (once per data version); None if disabled."""
    if not enabled():
        return None
    with _lock:
        ctx = holder.get("ctx")
        if ctx is not None:
            return ctx
        global _store
        order = [s.name for s in registry.ordered("bars", conn)]
        if _store["path"] != str(config.DB_PATH):
            _store = _load_file(order)
        elif _store["order"] != order:
            _store = _fresh_empty()
            _store["order"] = order
            _store["dirty"] = True
        fresh = _freshness(conn)
        dropped, changed = _append(fresh, _store["raw"], conn)
        rewritten = _rewritten_symbols(fresh, _store["seen"], dropped)
        if dropped or changed:
            _store["dirty"] = True
        ctx = {
            "fresh": fresh,
            "rewritten": rewritten,
            "orders": {
                "bars": order,
                "actions": [s.name for s in registry.ordered("actions", conn)],
                "symbol_changes": [s.name for s in registry.ordered("symbol_changes", conn)],
            },
            **_reference(conn),
        }
        holder["ctx"] = ctx
        return ctx


def raw_frame(source: str, ticker: str, conn: sqlite3.Connection) -> pd.DataFrame:
    """One ticker's raw bars (shared frame: callers must copy before changing it)."""
    ctx = holder.get("ctx") or {}
    cur = ctx.get("fresh", {}).get((source, ticker))
    with _lock:
        ent = _store["raw"].get((source, ticker))
        if ent is not None and cur is not None and ent[1:] == cur:
            return ent[0]
    rows = conn.execute(
        "SELECT " + bardb.OHLCV_SQL + " FROM bars WHERE source_id=" + bardb.SRC_ID
        + " AND sym_id=" + bardb.SYM_ID + " ORDER BY day",
        (source, ticker),
    ).fetchall()
    frame = rows_to_frame(rows)
    if cur is not None and len(rows) == cur[0]:  # else the table moved since validation: don't keep it
        with _lock:
            _store["raw"][(source, ticker)] = (frame, *cur)
            _store["dirty"] = True
    return frame


def _month_rows(conn: sqlite3.Connection, source: str, since: str | None, symbols: list[str]) -> list:
    # Loop over bar_symbols so each symbol is a key seek (with a day range): bars has no day index.
    base = (
        f"SELECT y.symbol, {bardb.MONTH_SQL} AS m, SUM({bardb.TRADED_SQL}), COUNT({bardb.TRADED_SQL}) "
        f"FROM bar_symbols y CROSS JOIN bars b ON b.source_id={bardb.SRC_ID} AND b.sym_id = y.id"
    )
    rows: list = []
    if since is None:
        return conn.execute(base + " GROUP BY y.symbol, m", (source,)).fetchall()
    first = bardb.day(since + "-01")
    rows += conn.execute(base + " AND b.day >= ? GROUP BY y.symbol, m", (source, first)).fetchall()
    for i in range(0, len(symbols), _IN_CHUNK):
        part = symbols[i : i + _IN_CHUNK]
        marks = ",".join("?" * len(part))
        rows += conn.execute(
            base + f" AND b.day < ? WHERE y.symbol IN ({marks}) GROUP BY y.symbol, m",
            (source, first, *part),
        ).fetchall()
    return rows


def monthly_average(conn: sqlite3.Connection, ctx: dict, sources: list) -> pd.DataFrame:
    """`DataFrame(symbol, m, v)` of every month's average traded value, first source wins per symbol.

    Completed months come from the store; the newest month (and any symbol whose old bars were
    rewritten) is recomputed. Updates the store's month sums.
    """
    fresh = ctx["fresh"]
    rewritten = sorted(ctx["rewritten"])
    parts: list[pd.DataFrame] = []
    seen_syms: set[str] = set()
    with _lock:
        for src in sources:
            mine_syms = {s for (name, s) in fresh if name == src.name} - seen_syms
            seen_syms |= mine_syms
            old = _store["months"].get(src.name)
            since = None if old is None or old.empty else str(old["m"].max())
            old_syms = set(rewritten)
            rows = _month_rows(conn, src.name, since, rewritten)
            new = pd.DataFrame([tuple(r) for r in rows], columns=["symbol", "m", "sum_v", "n"])
            if old is not None and not old.empty:
                keep = old[(old["m"] < since) & ~old["symbol"].isin(old_syms)]
                new = pd.concat([keep, new], ignore_index=True)
            newest = max((v[1] for (name, _), v in fresh.items() if name == src.name), default=None)
            done = new if newest is None else new[new["m"] < bardb.iso(newest)[:7]]
            _store["months"][src.name] = done.reset_index(drop=True)
            _store["dirty"] = True
            mine = new[new["symbol"].isin(mine_syms) & (new["n"] > 0)]
            parts.append(
                pd.DataFrame({"symbol": mine["symbol"], "m": mine["m"], "v": mine["sum_v"] / mine["n"]})
            )
        _store["seen"] = dict(fresh)
    return pd.concat(parts) if parts else pd.DataFrame(columns=["symbol", "m", "v"])
