"""Writes normalized records from any source into the database (SPEC §3.5)."""

from __future__ import annotations

import importlib
import json
import logging
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from app import bardb, timeutil
from app.analytics.fundamentals import FIELDS as FUNDAMENTAL_FIELDS
from app.sources import registry
from app.sources.base import (
    Action,
    Announcement,
    Bar,
    Event,
    FundSnapshot,
    IndexBar,
    NewsItem,
    Quarter,
    SymbolChange,
    SymbolRow,
)

log = logging.getLogger(__name__)

# §9.4 field names: the only legal fundamental keys.
FUND_FIELD_NAMES: frozenset[str] = frozenset(f["field"] for f in FUNDAMENTAL_FIELDS)

_CATEGORIES_PATH = Path(__file__).resolve().parents[1] / "presets" / "announcement_categories.json"


def _invalidate_frames() -> None:
    try:
        frames = importlib.import_module("app.analytics.frames")
    except ModuleNotFoundError as e:
        if e.name and "app.analytics".startswith(e.name):
            return
        raise
    frames.invalidate()


def save(capability: str, source: str, records, *, key: str, conn: sqlite3.Connection) -> int:
    """Dispatch to the writer for `capability`; returns the number of records written."""
    if capability == "fundamentals":
        return save_fundamentals(source, records, conn)
    writers = {
        "universe": save_universe,
        "bars": save_bars,
        "actions": save_actions,
        "index": save_index,
        "quarters": save_quarters,
        "announcements": save_announcements,
        "news": save_news,
        "symbol_changes": save_symbol_changes,
        "events": save_events,
    }
    if capability not in writers:
        raise ValueError(f"unknown capability: {capability}")
    return writers[capability](source, list(records), conn)


def _is_primary_universe(source: str, conn: sqlite3.Connection) -> bool:
    ordered = registry.ordered("universe", conn)
    return bool(ordered) and ordered[0].name == source


def save_universe(source: str, rows: list[SymbolRow], conn: sqlite3.Connection) -> int:
    now = timeutil.now_iso()
    primary = _is_primary_universe(source, conn)
    for r in rows:
        if primary:
            conn.execute(
                "INSERT INTO symbols(symbol, name, industry, isin, in_universe, updated_at) "
                "VALUES (?,?,?,?,1,?) ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, "
                "industry=excluded.industry, isin=excluded.isin, in_universe=1, "
                "updated_at=excluded.updated_at",
                (r.symbol, r.name, r.industry, r.isin, now),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO symbols(symbol, name, industry, isin, in_universe, updated_at) "
                "VALUES (?,?,?,?,0,?)",
                (r.symbol, r.name, r.industry, r.isin, now),
            )
    if primary and rows:
        conn.execute("UPDATE symbols SET in_universe=0")
        conn.executemany(
            "UPDATE symbols SET in_universe=1 WHERE symbol=?", [(r.symbol,) for r in rows]
        )
    return len(rows)


def save_bars(source: str, bars: list[Bar], conn: sqlite3.Connection) -> int:
    bardb.ensure_source(source, conn)
    sid = conn.execute("SELECT id FROM bar_sources WHERE name=?", (source,)).fetchone()[0]
    ids = bardb.symbol_ids((b.symbol for b in bars), conn)
    p, w = bardb.paise, bardb.whole
    conn.executemany(
        "INSERT OR REPLACE INTO bars(source_id, sym_id, day, open_p, high_p, low_p, close_p, volume, value, "
        "trades) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (sid, ids[b.symbol], bardb.day(b.date), p(b.open), p(b.high), p(b.low), p(b.close),
             w(b.volume), w(b.value), b.trades)
            for b in bars
        ],
    )
    inst = [(b.symbol, b.isin, b.series, b.date, source) for b in bars if b.isin or b.series]
    if inst:
        conn.executemany(
            "INSERT INTO instruments(symbol, isin, series, last_date, source) VALUES (?,?,?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET isin=excluded.isin, series=excluded.series, "
            "last_date=excluded.last_date, source=excluded.source "
            "WHERE excluded.last_date >= instruments.last_date",
            inst,
        )
    _invalidate_frames()
    return len(bars)


def save_actions(source: str, actions: list[Action], conn: sqlite3.Connection) -> int:
    conn.executemany(
        "INSERT OR REPLACE INTO corp_actions(source, symbol, ex_date, subject, kind, factor) "
        "VALUES (?,?,?,?,?,?)",
        [(source, a.symbol, a.ex_date, a.subject, a.kind, a.factor) for a in actions],
    )
    _invalidate_frames()
    return len(actions)


def save_index(source: str, bars: list[IndexBar], conn: sqlite3.Connection) -> int:
    conn.executemany(
        "INSERT OR REPLACE INTO index_bars(source, index_name, date, close) VALUES (?,?,?,?)",
        [(source, b.index_name, b.date, b.close) for b in bars],
    )
    _invalidate_frames()
    return len(bars)


def save_symbol_changes(source: str, items: list[SymbolChange], conn: sqlite3.Connection) -> int:
    conn.executemany(
        "INSERT OR REPLACE INTO symbol_changes(source, old_symbol, new_symbol, effective_date, name, note) "
        "VALUES (?,?,?,?,?,NULL)",
        [(source, c.old_symbol, c.new_symbol, c.effective_date, c.name) for c in items],
    )
    _invalidate_frames()
    return len(items)


def save_events(source: str, items: list[Event], conn: sqlite3.Connection) -> int:
    """The calendar lists every upcoming meeting and NSE reschedules some: replace this source's future rows."""  # noqa: E501
    conn.execute("DELETE FROM events WHERE source=? AND date>=?", (source, timeutil.today().isoformat()))
    fetched = timeutil.now().isoformat()
    conn.executemany(
        "INSERT OR REPLACE INTO events(source, symbol, date, purpose, description, fetched_at) "
        "VALUES (?,?,?,?,?,?)",
        [(source, e.symbol, e.date, e.purpose, e.description, fetched) for e in items],
    )
    return len(items)


def save_fundamentals(source: str, snap, conn: sqlite3.Connection) -> int:
    snaps = snap if isinstance(snap, list) else [snap]
    for s in snaps:
        assert isinstance(s, FundSnapshot)
        unknown = sorted(set(s.fields) - FUND_FIELD_NAMES)
        if unknown:
            log.warning("%s: dropping unknown fundamentals fields for %s: %s", source, s.symbol, unknown)
        fields = {k: v for k, v in s.fields.items() if k in FUND_FIELD_NAMES}
        conn.execute(
            "INSERT OR REPLACE INTO fund_snapshots(source, symbol, fetched_at, fields, detail) "
            "VALUES (?,?,?,?,?)",
            (source, s.symbol, timeutil.now_iso(), json.dumps(fields), json.dumps(s.detail)),
        )
    return len(snaps)


def save_quarters(source: str, quarters: list[Quarter], conn: sqlite3.Connection) -> int:
    conn.executemany(
        "INSERT OR REPLACE INTO quarters(source, symbol, period_end, consolidated, period_start, "
        "audited, filing_date, url, revenue, other_income, total_expenses, pbt, net_profit, eps, "
        "parse_error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                source, q.symbol, q.period_end, int(q.consolidated), q.period_start,
                None if q.audited is None else int(q.audited), q.filing_date, q.url,
                q.revenue, q.other_income, q.total_expenses, q.pbt, q.net_profit, q.eps,
                q.parse_error,
            )
            for q in quarters
        ],
    )  # fmt: skip
    return len(quarters)


def save_announcements(source: str, items: list[Announcement], conn: sqlite3.Connection) -> int:
    conn.executemany(
        "INSERT OR IGNORE INTO announcements(source, symbol, ts, category, headline, body, url) "
        "VALUES (?,?,?,?,?,?,?)",
        [
            (
                source, a.symbol, a.ts,
                a.category or categorize(f"{a.headline} {a.body or ''}"),
                a.headline, a.body, a.url,
            )
            for a in items
        ],
    )  # fmt: skip
    return len(items)


def save_news(source: str, items: list[NewsItem], conn: sqlite3.Connection) -> int:
    for n in items:
        conn.execute(
            "INSERT OR IGNORE INTO news_items(source, feed, ts, title, url, summary) VALUES (?,?,?,?,?,?)",
            (source, n.feed, n.ts, n.title, n.url, n.summary),
        )
        news_id = conn.execute("SELECT id FROM news_items WHERE url=?", (n.url,)).fetchone()[0]
        for sym in match_symbols(f"{n.title} {n.summary or ''}", conn):
            conn.execute(
                "INSERT OR IGNORE INTO news_symbols(news_id, symbol) VALUES (?,?)", (news_id, sym)
            )
    return len(items)


def last_bar_date(source: str, symbol: str, conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT MAX(day) FROM bars WHERE source_id=" + bardb.SRC_ID + " AND sym_id=" + bardb.SYM_ID,
        (source, symbol),
    ).fetchone()
    return bardb.iso(row[0])


def last_index_date(source: str, conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(date) FROM index_bars WHERE source=?", (source,)).fetchone()
    return row[0]


# ---- announcement categories (§13.2) ----


@lru_cache(maxsize=1)
def _categories() -> list[dict]:
    return json.loads(_CATEGORIES_PATH.read_text())


def categorize(text: str) -> str:
    """First category whose keyword appears in `text` (case-insensitive); else 'other'."""
    low = text.lower()
    for cat in _categories():
        if any(k in low for k in cat["keywords"]):
            return cat["category"]
    return "other"


# ---- news symbol matching (§13.3) ----

_SUFFIXES = ("limited", "ltd.", "ltd", "india", "industries", "corporation", "company", "& co")
_cache: dict = {"count": None, "names": None, "name_re": None, "symbols": frozenset()}


def _short_name(name: str) -> str:
    out = name.strip()
    while True:
        low = out.lower()
        for suf in _SUFFIXES:
            if low.endswith(suf) and (len(out) == len(suf) or not out[-len(suf) - 1].isalnum()):
                out = out[: -len(suf)].strip().rstrip(",")
                break
        else:
            return out


def _build_index(conn: sqlite3.Connection) -> None:
    names: dict[str, set[str]] = {}
    symbols: set[str] = set()
    for row in conn.execute("SELECT symbol, name FROM symbols"):
        sym, name = row["symbol"], row["name"]
        if re.fullmatch(r"[A-Z]{4,}", sym):
            symbols.add(sym)
        if name:
            short = _short_name(name)
            if len(short.split()) >= 2 or len(short) >= 6:
                names.setdefault(short.lower(), set()).add(sym)
    pattern = None
    if names:
        alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        pattern = re.compile(rf"(?<![A-Za-z0-9])(?:{alts})(?![A-Za-z0-9])", re.IGNORECASE)
    _cache.update(names=names, name_re=pattern, symbols=frozenset(symbols))


def match_symbols(text: str, conn: sqlite3.Connection) -> set[str]:
    count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    if _cache["count"] != count:
        _build_index(conn)
        _cache["count"] = count
    found: set[str] = set()
    if _cache["name_re"] is not None:
        for m in _cache["name_re"].finditer(text):
            found |= _cache["names"][m.group(0).lower()]
    for word in re.findall(r"(?<![A-Za-z0-9])[A-Z]{4,}(?![A-Za-z0-9])", text):
        if word in _cache["symbols"]:
            found.add(word)
    return found
