"""How the `bars` table is stored (SPEC §4): small integer ids, integer days, prices in paise.

`bars(source_id, sym_id, day, open_p, high_p, low_p, close_p, volume, value, trades)`:
- `source_id` -> `bar_sources(id, name)`, `sym_id` -> `bar_symbols(id, symbol)`;
- `day` is YYYYMMDD as an INTEGER (2026-11-13 -> 20261113);
- prices are paise (46.55 -> 4655): an INTEGER when whole (every NSE price), else the exact float x100
  (adjusted sources), `volume` an INTEGER, `value` INTEGER rupees.
There is no secondary index: every lookup is a primary-key seek (see LAST_DAY_SQL for "newest day").
Together this keeps the database ~70% smaller (migrations 011/012). The rest of the app keeps using
source names, symbols, "YYYY-MM-DD" strings and float prices: convert at the SQL boundary with these helpers.
Never compare `day` with a text date: SQLite orders every INTEGER before every TEXT, silently.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

# Use inside SQL wherever a source name is bound: "... WHERE source_id=" + SRC_ID, then pass the name.
SRC_ID = "(SELECT id FROM bar_sources WHERE name=?)"
# Same for a symbol: "... AND sym_id=" + SYM_ID, then pass the symbol.
SYM_ID = "(SELECT id FROM bar_symbols WHERE symbol=?)"
# 'YYYY-MM' of `day` in SQL (monthly grouping).
MONTH_SQL = "printf('%04d-%02d', day / 10000, day / 100 % 100)"
# The columns `price_store.rows_to_frame` expects, as floats in rupees. n/100.0 is correctly rounded,
# so a price stored from 46.55 reads back as exactly the float 46.55.
OHLCV_SQL = (
    "day, open_p / 100.0, high_p / 100.0, low_p / 100.0, close_p / 100.0, CAST(volume AS REAL)"
)
# Traded value in rupees: the stored value, else close x volume.
TRADED_SQL = "COALESCE(value, close_p * volume / 100.0)"
# Newest day over every source and symbol: one primary-key seek per (source, symbol), no index needed.
LAST_DAY_SQL = (
    "SELECT MAX((SELECT MAX(b.day) FROM bars b WHERE b.source_id = s.id AND b.sym_id = y.id)) "
    "FROM bar_sources s, bar_symbols y"
)


def day(iso: str) -> int:
    """'2026-11-13' -> 20261113."""
    return int(iso[0:4] + iso[5:7] + iso[8:10])


def iso(d: int | None) -> str | None:
    """20261113 -> '2026-11-13' (None stays None)."""
    if d is None:
        return None
    s = str(int(d))
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def paise(price: float | None) -> int | float | None:
    """46.55 -> 4655 (None stays None). A price that isn't whole paise (an adjusted source's 317.6253)
    stays exact as the float 31762.53: the INTEGER column keeps it as REAL, so nothing is rounded away."""
    if price is None:
        return None
    r = round(price * 100)
    return r if r / 100 == price else price * 100  # whole only when it reads back as the very same float


def whole(x: float | None) -> int | None:
    """Volume / rupee value as an integer (None stays None)."""
    return None if x is None else round(x)


def ensure_source(name: str, conn: sqlite3.Connection) -> None:
    """Give `name` a source id if it has none yet (call before inserting its bars)."""
    conn.execute("INSERT OR IGNORE INTO bar_sources(name) VALUES (?)", (name,))


def symbol_ids(symbols: Iterable[str], conn: sqlite3.Connection) -> dict[str, int]:
    """{symbol: sym_id}, giving new symbols an id (call before inserting their bars)."""
    syms = sorted(set(symbols))
    conn.executemany("INSERT OR IGNORE INTO bar_symbols(symbol) VALUES (?)", [(s,) for s in syms])
    out: dict[str, int] = {}
    for i in range(0, len(syms), 500):
        part = syms[i : i + 500]
        q = f"SELECT symbol, id FROM bar_symbols WHERE symbol IN ({','.join('?' * len(part))})"
        out.update({r[0]: r[1] for r in conn.execute(q, part)})
    return out
