"""Held stocks that dropped out of the screen they were bought from (SPEC §13.2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app.alerts.base import AlertDraft, AlertScanner, register


def scan(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    rows = conn.execute(
        "SELECT p.id, p.symbol, p.entry_date, s.id AS screen_id, s.name FROM positions p "
        "JOIN screens s ON s.id = p.source_screen_id WHERE p.status='open' ORDER BY p.id"
    ).fetchall()
    out = []
    for r in rows:
        last = conn.execute(
            "SELECT MAX(as_of) FROM screen_results WHERE screen_id=?", (r["screen_id"],)
        ).fetchone()[0]
        if last is None or last <= r["entry_date"]:
            continue
        found = conn.execute(
            "SELECT 1 FROM screen_results WHERE screen_id=? AND symbol=?", (r["screen_id"], r["symbol"])
        ).fetchone()
        if found:
            continue
        out.append(AlertDraft(
            "screen_left",
            f"{r['symbol']} no longer matches '{r['name']}', the screen you bought it from. "
            "Check whether your reason for holding still stands.",
            f"screen_left:{r['id']}:{r['screen_id']}", r["symbol"], f"/stock/{r['symbol']}", "info",
        ))  # fmt: skip
    return out


register(AlertScanner("screen_left", "Held stock left its screen", scan))
