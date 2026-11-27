import json
from datetime import date, datetime

import pytest

from app import db, timeutil
from app.jobs import scheduler
from app.jobs.defs import backtests_weekly as weekly

RULE = {"all": [{"left": {"ind": "rsi", "params": {"n": 14}}, "op": "<", "right": {"value": 60}}]}


@pytest.fixture(autouse=True)
def _db():
    db.init_db()
    with db.tx() as c:
        c.execute("DELETE FROM screens")
        c.execute("DELETE FROM backtests")
        c.execute(
            "INSERT INTO screens(name, rule, created_at, updated_at) VALUES ('Dips', ?, 'x', 'x')",
            (json.dumps(RULE),),
        )


def _rows():
    with db.tx() as c:
        return c.execute("SELECT name, config, kind, status FROM backtests ORDER BY id").fetchall()


def test_two_windows_per_screen_ending_today():
    ids = weekly.make_rows(date(2026, 11, 29))
    assert len(ids) == 2
    rows = _rows()
    assert [r["name"] for r in rows] == ["Weekly 12m: Dips", "Weekly 4y: Dips"]
    starts = [json.loads(r["config"])["start"] for r in rows]
    assert starts == ["2025-11-29", "2022-11-29"]
    for r in rows:
        cfg = json.loads(r["config"])
        assert cfg["oos_start"] == "2026-11-30" and r["kind"] == "explore" and r["status"] == "queued"


def test_replaces_last_week_and_keeps_other_backtests():
    with db.tx() as c:
        mine = {"entry_rule": RULE, "max_positions": 5, "start": "2012-01-01", "oos_start": "2022-01-01"}
        c.execute(
            "INSERT INTO backtests(name, config, status, kind, created_at) "
            "VALUES ('Mine', ?, 'done', 'explore', 'x')",
            (json.dumps(mine),),
        )
    weekly.make_rows(date(2026, 11, 22))
    weekly.make_rows(date(2026, 11, 29))
    rows = _rows()
    assert [r["name"] for r in rows] == ["Mine", "Weekly 12m: Dips", "Weekly 4y: Dips"]
    assert json.loads(rows[1]["config"])["start"] == "2025-11-29"
    assert json.loads(rows[1]["config"])["max_positions"] == 5  # setup borrowed from "Mine"


def test_scheduled_sunday_noon(monkeypatch):
    friday = datetime(2026, 11, 27, 18, 0, tzinfo=timeutil.now().tzinfo)
    monkeypatch.setattr(timeutil, "now", lambda: friday)
    scheduler.ensure_schedules()
    with db.tx() as c:
        row = c.execute("SELECT * FROM job_schedules WHERE job='backtests_weekly'").fetchone()
    assert (row["kind"], row["weekday"], row["at_time"]) == ("weekly", 6, "12:00")
    assert row["next_run_at"].startswith("2026-11-29T12:00")
