"""New announcements in alerting categories for watched and held stocks (SPEC §13.2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app.alerts.base import AlertDraft, AlertScanner, register
from app.sources import store


def _followed(conn: sqlite3.Connection) -> dict[str, datetime]:
    """symbol -> when the owner started following it (watchlist add or position creation)."""
    since: dict[str, datetime] = {}
    rows = [
        *conn.execute("SELECT symbol, added_at AS t FROM watchlist"),
        *conn.execute("SELECT symbol, created_at AS t FROM positions WHERE status='open'"),
    ]
    for r in rows:
        t = datetime.fromisoformat(r["t"])
        if r["symbol"] not in since or t < since[r["symbol"]]:
            since[r["symbol"]] = t
    return since


def scan(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    cats = {c["category"]: c for c in store._categories() if c.get("alert")}
    followed = _followed(conn)
    if not cats or not followed:
        return []
    marks = ",".join("?" * len(followed))
    cmarks = ",".join("?" * len(cats))
    rows = conn.execute(
        f"SELECT id, symbol, ts, category, headline FROM announcements "
        f"WHERE symbol IN ({marks}) AND category IN ({cmarks}) ORDER BY ts",
        (*followed, *cats),
    ).fetchall()
    out = []
    for r in rows:
        if datetime.fromisoformat(r["ts"]) <= followed[r["symbol"]]:
            continue  # older than the day the owner started following it
        label = r["category"].replace("_", " ")
        severity = cats[r["category"]].get("severity", "info")
        out.append(AlertDraft(
            "announcement",
            f"{r['symbol']}: new announcement ({label}): {r['headline']}",
            f"ann:{r['id']}", r["symbol"], f"/stock/{r['symbol']}", severity,
        ))  # fmt: skip
    return out


register(AlertScanner("announcement", "New company announcement", scan))
