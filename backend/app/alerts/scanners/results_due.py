"""Results day coming up for watched and held stocks (SPEC §13.2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app.alerts.base import AlertDraft, AlertScanner, day_name, register
from app.analytics import calendar

RESULTS_DUE_DAYS = 7


def _followed(conn: sqlite3.Connection) -> tuple[set[str], set[str]]:
    """(held symbols, watched-or-held symbols)."""
    held = {r["symbol"] for r in conn.execute("SELECT symbol FROM positions WHERE status='open'")}
    watched = {r["symbol"] for r in conn.execute("SELECT symbol FROM watchlist")}
    return held, held | watched


def _when(days: int) -> str:
    return "today" if days == 0 else "tomorrow" if days == 1 else f"{days} days"


def scan(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    held, followed = _followed(conn)
    if not followed:
        return []
    out = []
    for sym, info in sorted(calendar.next_results(conn, sorted(followed)).items()):
        if info["days"] > RESULTS_DUE_DAYS:
            continue
        text = f"{sym} reports results on {day_name(info['date'])} ({_when(info['days'])})."
        if sym in held:
            text += " Decide before then whether to hold through it."
        out.append(AlertDraft(
            "results_due", text, f"results_due:{sym}:{info['date']}", sym, f"/stock/{sym}",
            "warn" if sym in held else "info",
        ))  # fmt: skip
    return out


register(AlertScanner("results_due", "Results coming up", scan))
