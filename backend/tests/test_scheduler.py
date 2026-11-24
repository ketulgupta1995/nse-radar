from datetime import datetime, timedelta

import pytest

from app import config, db
from app.jobs import registry, runner, scheduler
from app.jobs.registry import JobDef

IST = config.TZ


def dt(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=IST)


# 2026-11-06 is a Friday, 2026-11-09 a Monday
def test_daily_weekdays_only():
    s = {"kind": "daily", "at_time": "19:30", "weekdays_only": 1}
    assert scheduler.compute_next_run(s, dt(2026, 11, 6, 20)) == dt(2026, 11, 9, 19, 30)
    assert scheduler.compute_next_run(s, dt(2026, 11, 9, 10)) == dt(2026, 11, 9, 19, 30)


def test_weekly_interval_manual():
    assert scheduler.compute_next_run(
        {"kind": "weekly", "weekday": 0, "at_time": "08:00"}, dt(2026, 11, 9, 9)
    ) == dt(2026, 11, 16, 8)
    assert scheduler.compute_next_run({"kind": "interval", "interval_min": 90}, dt(2026, 11, 9, 10)) == dt(
        2026, 11, 9, 11, 30
    )
    assert scheduler.compute_next_run({"kind": "manual"}, dt(2026, 11, 9, 10)) is None


@pytest.fixture
def jobs():
    db.init_db()
    registry._JOBS.pop("sched_t", None)
    registry.register(JobDef("sched_t", "t", "", lambda ctx: None, {"kind": "interval", "interval_min": 60}))
    import app.jobs.defs.housekeeping  # noqa: F401
    yield
    registry._JOBS.pop("sched_t", None)


def row(job="sched_t"):
    with db.tx() as c:
        return c.execute("SELECT * FROM job_schedules WHERE job=?", (job,)).fetchone()


def queued(job="sched_t"):
    with db.tx() as c:
        return c.execute("SELECT COUNT(*) FROM job_runs WHERE job=?", (job,)).fetchone()[0]


def test_ensure_creates_and_keeps_edits(jobs):
    scheduler.ensure_schedules()
    assert row()["kind"] == "interval" and row()["next_run_at"]
    assert row("noop") is None or row("noop")["next_run_at"] is None
    with db.tx() as c:
        c.execute("UPDATE job_schedules SET interval_min=5 WHERE job='sched_t'")
    scheduler.ensure_schedules()
    assert row()["interval_min"] == 5


def test_tick_enqueues_once_and_reschedules_from_now(jobs):
    scheduler.ensure_schedules()
    past = dt(2026, 11, 6, 10).isoformat()
    with db.tx() as c:
        c.execute("UPDATE job_schedules SET next_run_at=? WHERE job='sched_t'", (past,))
    now = dt(2026, 11, 9, 10)  # 3 days after the missed time
    assert len(scheduler.tick(now)) == 1
    assert len(scheduler.tick(now)) == 0
    assert queued() == 1
    assert row()["next_run_at"] == (now + timedelta(minutes=60)).isoformat(timespec="seconds")


def test_disabled_and_paused(jobs):
    scheduler.ensure_schedules()
    past = dt(2026, 11, 6, 10).isoformat()
    now = dt(2026, 11, 9, 10)
    with db.tx() as c:
        c.execute("UPDATE job_schedules SET next_run_at=?, enabled=0 WHERE job='sched_t'", (past,))
    assert scheduler.tick(now) == []
    with db.tx() as c:
        c.execute("UPDATE job_schedules SET enabled=1 WHERE job='sched_t'")
    db.set_setting("jobs_paused", True)
    assert scheduler.tick(now) == []
    assert queued() == 0


def test_housekeeping_deletes_old(jobs):
    from app import timeutil

    old = (timeutil.now() - timedelta(days=100)).isoformat(timespec="seconds")
    new = timeutil.now_iso()
    with db.tx() as c:
        for ts in (old, new):
            c.execute(
                "INSERT INTO job_runs(job, trigger, status, queued_at, finished_at) VALUES "
                "('noop','manual','done',?,?)",
                (ts, ts),
            )
        c.execute("INSERT INTO job_items(run_id, key, status, at) SELECT id,'k','ok',? FROM job_runs "
                  "WHERE finished_at=?", (old, old))
        ins = "INSERT INTO alerts(kind,message,dedupe_key,created_at,seen_at) VALUES ('k','m',?,?,?)"
        c.execute(ins, ("a", old, old))
        c.execute(ins, ("b", old, None))
    rid = runner.enqueue("housekeeping")
    runner.run_one()
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM job_runs WHERE job='noop'").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM job_items WHERE key='k'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1
        msg = c.execute("SELECT message FROM job_runs WHERE id=?", (rid,)).fetchone()[0]
        assert "1 runs, 1 alerts" in msg
