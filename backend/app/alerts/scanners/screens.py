"""Stocks that newly entered a saved screen (SPEC §13.2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app.alerts.base import AlertDraft, AlertScanner, register

SHOWN = 5


def scan(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    today = now.date().isoformat()
    out = []
    screens = conn.execute("SELECT id, name FROM screens ORDER BY id").fetchall()
    for s in screens:
        syms = [
            r["symbol"]
            for r in conn.execute(
                "SELECT symbol FROM screen_results WHERE screen_id=? AND first_seen=? ORDER BY symbol",
                (s["id"], today),
            )
        ]
        if not syms:
            continue
        names = ", ".join(syms[:SHOWN]) + (f" and {len(syms) - SHOWN} more" if len(syms) > SHOWN else "")
        noun = "stock" if len(syms) == 1 else "stocks"
        out.append(AlertDraft(
            "screen_new",
            f"{len(syms)} new {noun} in '{s['name']}': {names}",
            f"screen_new:{s['id']}:{today}", None, f"/screener?screen={s['id']}", "info",
        ))  # fmt: skip
    return out


register(AlertScanner("screen_new", "New stocks in a screen", scan))
