"""Warn when prices are more than two weekdays old, unless the app is still catching up (SPEC §13.2)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from app.alerts.base import AlertDraft, AlertScanner, register
from app.analytics import frames
from app.jobs import runner

MAX_WEEKDAYS_BEHIND = 2


def weekdays_behind(last: date, today: date) -> int:
    """Mon-Fri days strictly after `last`, up to and including `today`."""
    n, d = 0, last + timedelta(days=1)
    while d <= today:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


def scan(conn: sqlite3.Connection, now: datetime) -> list[AlertDraft]:
    last = frames.last_trading_date(conn)
    if last is None:
        return []
    behind = weekdays_behind(date.fromisoformat(last), now.date())
    if behind <= MAX_WEEKDAYS_BEHIND or runner.status()["updating"]:
        return []
    return [AlertDraft(
        "data_stale",
        f"Prices are out of date: the latest are from {last} ({behind} weekdays ago). "
        "Check the Jobs and Sources pages.",
        f"stale:{last}", None, "/jobs", "warn",
    )]  # fmt: skip


register(AlertScanner("data_stale", "Prices are out of date", scan))
