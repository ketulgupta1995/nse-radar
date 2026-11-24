"""Alerts about open positions: stop near, stop hit, target hit, time stop (SPEC §13.2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pandas as pd

from app.alerts.base import AlertDraft, AlertScanner, day_name, inr, register
from app.analytics import frames

NEAR_PCT = 3.0


def _open_positions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM positions WHERE status='open' ORDER BY id").fetchall()


def _bars_since_entry(pos: sqlite3.Row):
    """Adjusted bars after the entry day (the entry day's own low may predate the fill)."""
    frame = frames.load_frame(pos["symbol"], pos["entry_date"])
    return frame[frame.index > pd.Timestamp(pos["entry_date"])]


def stop_near(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    out = []
    for p in _open_positions(conn):
        if p["stop"] is None:
            continue
        frame = frames.load_frame(p["symbol"], p["entry_date"])
        if frame.empty:
            continue
        close, stop = float(frame["close"].iloc[-1]), float(p["stop"])
        above = (close / stop - 1) * 100
        if 0 < above <= NEAR_PCT:
            day = frame.index[-1].date().isoformat()
            out.append(AlertDraft(
                "stop_near",
                f"{p['symbol']} closed at {inr(close)}, {above:.1f}% above your stop {inr(stop)}",
                f"stop_near:{p['id']}:{day}", p["symbol"], "/positions", "warn",
            ))  # fmt: skip
    return out


def stop_hit(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    out = []
    for p in _open_positions(conn):
        if p["stop"] is None:
            continue
        bars = _bars_since_entry(p)
        hit = bars[bars["low"] <= p["stop"]]
        if hit.empty:
            continue
        day = hit.index[0].date().isoformat()
        out.append(AlertDraft(
            "stop_hit",
            f"{p['symbol']}: stop hit on {day_name(day)}, low {inr(float(hit['low'].iloc[0]))} "
            f"(your stop was {inr(float(p['stop']))})",
            f"stop_hit:{p['id']}", p["symbol"], "/positions", "critical",
        ))  # fmt: skip
    return out


def target_hit(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    out = []
    for p in _open_positions(conn):
        if p["target"] is None:
            continue
        bars = _bars_since_entry(p)
        hit = bars[bars["high"] >= p["target"]]
        if hit.empty:
            continue
        day = hit.index[0].date().isoformat()
        out.append(AlertDraft(
            "target_hit",
            f"{p['symbol']} hit your target {inr(float(p['target']))} on {day_name(day)} "
            f"(high {inr(float(hit['high'].iloc[0]))})",
            f"target_hit:{p['id']}", p["symbol"], "/positions", "info",
        ))  # fmt: skip
    return out


def time_stop(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    today = now.date().isoformat()
    return [
        AlertDraft(
            "time_stop",
            f"{p['symbol']}: your time stop ({day_name(p['time_stop_date'])}) has passed and the "
            "position is still open. Decide whether to hold or exit.",
            f"time_stop:{p['id']}", p["symbol"], "/positions", "warn",
        )
        for p in _open_positions(conn)
        if p["time_stop_date"] and today >= p["time_stop_date"]
    ]


register(AlertScanner("stop_near", "Price close to your stop", stop_near))
register(AlertScanner("stop_hit", "Stop price reached", stop_hit))
register(AlertScanner("target_hit", "Target price reached", target_hit))
register(AlertScanner("time_stop", "Time stop reached", time_stop))
