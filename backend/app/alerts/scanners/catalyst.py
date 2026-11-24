"""Announcements followed by a big price move on heavy volume (SPEC §13.2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pandas as pd

from app.alerts.base import AlertDraft, AlertScanner, day_name, register
from app.analytics import frames
from app.config import TZ

CATALYST_CATEGORIES = ("order_win", "credit_rating", "block_deal", "results", "other_important")
CATALYST_DAYS = 5
CATALYST_MOVE_PCT = 3.0
CATALYST_VOLUME_X = 2.0
HISTORY_DAYS = 90
VOLUME_WINDOW = 20
MARKET_CLOSE = (15, 30)


def _reaction_date(ts: str) -> str:
    """Date of the first bar that can react: the next day if posted after the close."""
    t = datetime.fromisoformat(ts)
    t = t.replace(tzinfo=TZ) if t.tzinfo is None else t.astimezone(TZ)
    d = t.date()
    if (t.hour, t.minute) > MARKET_CLOSE:
        d += timedelta(days=1)
    return d.isoformat()


def _reaction(frame: pd.DataFrame, day: str) -> tuple[pd.Timestamp, float, float] | None:
    """(bar day, % move, volume multiple) for the first bar on or after `day`, if it qualifies."""
    pos = int(frame.index.searchsorted(pd.Timestamp(day)))
    if pos >= len(frame) or pos < 1:
        return None
    prev = float(frame["close"].iloc[pos - 1])
    avg = float(frame["volume"].iloc[max(0, pos - VOLUME_WINDOW) : pos].mean())
    if prev <= 0 or not avg > 0:
        return None
    move = (float(frame["close"].iloc[pos]) / prev - 1) * 100
    mult = float(frame["volume"].iloc[pos]) / avg
    if move < CATALYST_MOVE_PCT or mult < CATALYST_VOLUME_X:
        return None
    return frame.index[pos], move, mult


def _headline(text: str) -> str:
    return text if len(text) <= 120 else text[:119].rstrip() + "…"


def scan(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    since = (now - timedelta(days=CATALYST_DAYS)).isoformat()
    cats = ",".join("?" * len(CATALYST_CATEGORIES))
    rows = conn.execute(
        f"SELECT id, symbol, ts, headline FROM announcements "
        f"WHERE category IN ({cats}) AND ts >= ? ORDER BY ts, id",
        (*CATALYST_CATEGORIES, since),
    ).fetchall()
    universe = set(frames.universe(conn))
    cache: dict[str, pd.DataFrame] = {}
    start = (now.date() - timedelta(days=CATALYST_DAYS + HISTORY_DAYS)).isoformat()
    out = []
    for r in rows:
        sym = r["symbol"]
        if sym not in universe:
            continue
        if sym not in cache:
            cache[sym] = frames.load_frame(sym, start)
        frame = cache[sym]
        if frame.empty:
            continue
        hit = _reaction(frame, _reaction_date(r["ts"]))
        if hit is None:
            continue
        day, move, mult = hit
        out.append(AlertDraft(
            "catalyst",
            f"{sym} rose {move:.1f}% on {mult:.1f}× normal volume on {day_name(day.date().isoformat())} "
            f"after: {_headline(r['headline'])}",
            f"catalyst:{r['id']}", sym, f"/stock/{sym}", "info",
        ))  # fmt: skip
    return out


register(AlertScanner("catalyst", "News with a price move", scan))
