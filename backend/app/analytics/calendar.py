"""Upcoming company events (SPEC §3.2 events): when is the next quarterly results day."""

import sqlite3
from datetime import date

from app import timeutil

RESULTS_WORD = "financial results"
_CHUNK = 500


def next_results(conn: sqlite3.Connection, symbols: list[str] | None = None) -> dict[str, dict]:
    """{symbol: {"date", "days"}}: earliest results meeting on or after today, from any source."""
    today = timeutil.today()
    sql = "SELECT symbol, MIN(date) FROM events WHERE date >= ? AND lower(purpose) LIKE ?"
    args: list = [today.isoformat(), f"%{RESULTS_WORD}%"]
    rows: list = []
    if symbols is None:
        rows = conn.execute(sql + " GROUP BY symbol", args).fetchall()
    else:
        for i in range(0, len(symbols), _CHUNK):
            part = symbols[i : i + _CHUNK]
            marks = ",".join("?" * len(part))
            rows += conn.execute(f"{sql} AND symbol IN ({marks}) GROUP BY symbol", args + part).fetchall()
    return {sym: {"date": d, "days": (date.fromisoformat(d) - today).days} for sym, d in rows}
