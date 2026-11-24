"""Trailing exits for open positions: close below the trend average, trailing ATR stop (SPEC §13.2)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd

from app import db
from app.alerts.base import AlertDraft, AlertScanner, day_name, inr, register
from app.analytics import frames
from app.analytics.indicators import _atr

HISTORY_DAYS = 400
ATR_DAYS = 14


def _open_positions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM positions WHERE status='open' ORDER BY id").fetchall()


def _frame(pos: sqlite3.Row) -> pd.DataFrame:
    start = (date.fromisoformat(pos["entry_date"]) - timedelta(days=HISTORY_DAYS)).isoformat()
    return frames.load_frame(pos["symbol"], start)


def _latest_break(frame: pd.DataFrame, avg: pd.Series, entry: pd.Timestamp) -> pd.Timestamp | None:
    close = frame["close"]
    crossed = (close.shift(1) >= avg.shift(1)) & (close < avg) & (frame.index > entry)
    days = crossed[crossed].index
    return days[-1] if len(days) else None


def trend_break(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    n = int(db.get_setting("position_exit_sma", conn))
    if n <= 0:
        return []
    out = []
    for p in _open_positions(conn):
        frame = _frame(p)
        if len(frame) < n:
            continue
        avg = frame["close"].rolling(n).mean()
        if pd.isna(avg.iloc[-1]) or frame["close"].iloc[-1] >= avg.iloc[-1]:
            continue
        day = _latest_break(frame, avg, pd.Timestamp(p["entry_date"]))
        if day is None:
            continue
        iso = day.date().isoformat()
        out.append(AlertDraft(
            "trend_break",
            f"{p['symbol']} closed at {inr(float(frame.loc[day, 'close']))} on {day_name(iso)}, "
            f"below its {n}-day average ({inr(float(avg.loc[day]))}). "
            "In the Position exit tests this is where the trade was sold.",
            f"trend_break:{p['id']}:{iso}", p["symbol"], "/positions", "warn",
        ))  # fmt: skip
    return out


def _trail_hit(p: sqlite3.Row, frame: pd.DataFrame, k: float) -> AlertDraft | None:
    entry = pd.Timestamp(p["entry_date"])
    upto = frame[frame.index <= entry]
    if upto.empty:
        return None
    atr = float(_atr(frame, None, ATR_DAYS).loc[upto.index[-1]])
    high = float(p["entry_price"])
    for day, row in frame[frame.index > entry].iterrows():
        level = high - k * atr
        if float(row["low"]) <= level:
            iso = day.date().isoformat()
            return AlertDraft(
                "trail_hit",
                f"{p['symbol']}: trailing stop hit on {day_name(iso)} (low {inr(float(row['low']))}, "
                f"stop {inr(level)}, {k:g} ATRs under the high of {inr(high)}).",
                f"trail_hit:{p['id']}", p["symbol"], "/positions", "critical",
            )  # fmt: skip
        high = max(high, float(row["close"]))
    return None


def trail_hit(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    k = float(db.get_setting("trail_atr_multiple", conn))
    if k <= 0:
        return []
    out = []
    for p in _open_positions(conn):
        frame = _frame(p)
        if frame.empty:
            continue
        draft = _trail_hit(p, frame, k)
        if draft is not None:
            out.append(draft)
    return out


register(AlertScanner("trend_break", "Price below your trend average", trend_break))
register(AlertScanner("trail_hit", "Trailing stop reached", trail_hit))
