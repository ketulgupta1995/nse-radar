import logging
import time
from datetime import datetime, timedelta

import pytest

from app import config, db, timeutil
from app.jobs import drain, registry, runner
from app.jobs.registry import JobDef

FROZEN = datetime(2026, 11, 9, 19, 0, tzinfo=config.TZ)


@pytest.fixture(autouse=True)
def _db():
    db.init_db()
    before = set(registry._JOBS)
    yield
    for k in set(registry._JOBS) - before:
        registry._JOBS.pop(k)


def reg(name, fn, **kw):
    registry._JOBS.pop(name, None)
    return registry.register(JobDef(name, name, "", fn, {"kind": "manual"}, **kw))


def runs(job):
    with db.tx() as c:
        return c.execute("SELECT * FROM job_runs WHERE job=? ORDER BY id", (job,)).fetchall()


def test_interactive_runs_before_background():
    order = []
    reg("dr_bg", lambda ctx: order.append("bg"))
    reg("dr_ia", lambda ctx: order.append("ia"), lane="interactive")
    runner.enqueue("dr_bg")
    runner.enqueue("dr_ia")
    assert drain.main([]) == 0
    assert order == ["ia", "bg"]
    assert runs("dr_bg")[0]["status"] == "done" and runs("dr_ia")[0]["status"] == "done"


def test_lane_filter_leaves_other_lane_queued():
    reg("dr_bg", lambda ctx: None)
    reg("dr_ia", lambda ctx: None, lane="interactive")
    runner.enqueue("dr_bg")
    runner.enqueue("dr_ia")
    assert drain.main(["--lane", "interactive"]) == 0
    assert runs("dr_ia")[0]["status"] == "done"
    assert runs("dr_bg")[0]["status"] == "queued"


def test_tick_enqueues_due_schedules(monkeypatch):
    monkeypatch.setattr(timeutil, "now", lambda: FROZEN)
    reg("dr_sched", lambda ctx: "ran")
    with db.tx() as c:
        c.execute(
            "INSERT INTO job_schedules(job, kind, interval_min, enabled, next_run_at) "
            "VALUES ('dr_sched','interval',60,1,?)",
            ((FROZEN - timedelta(days=2)).isoformat(timespec="seconds"),),
        )
    assert drain.main(["--tick"]) == 0
    r = runs("dr_sched")
    assert len(r) == 1 and r[0]["trigger"] == "schedule" and r[0]["status"] == "done"


def test_without_tick_due_schedules_wait(monkeypatch):
    monkeypatch.setattr(timeutil, "now", lambda: FROZEN)
    reg("dr_sched", lambda ctx: None)
    with db.tx() as c:
        c.execute(
            "INSERT INTO job_schedules(job, kind, interval_min, enabled, next_run_at) "
            "VALUES ('dr_sched','interval',60,1,?)",
            ((FROZEN - timedelta(days=2)).isoformat(timespec="seconds"),),
        )
    assert drain.main([]) == 0
    assert runs("dr_sched") == []


def test_empty_queue_exits_zero():
    assert drain.main([]) == 0
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0] == 0


def test_budget_stops_and_resumes(monkeypatch):
    monkeypatch.setattr(drain, "DEFAULT_BUDGET_MIN", 0.2 / 60)  # 0.2 s
    monkeypatch.setattr(drain, "STOP_REPEAT_S", 0.05)

    def forever(ctx):
        deadline = time.monotonic() + 10  # safety net: never hang the suite
        while time.monotonic() < deadline:
            ctx.check_stop()
            time.sleep(0.02)
        return "never stopped"

    reg("dr_loop", forever)
    reg("dr_after", lambda ctx: None)
    runner.enqueue("dr_loop", params={"from": "2020-01-01"})
    runner.enqueue("dr_after")
    assert drain.main([]) == 0
    r = runs("dr_loop")
    assert [x["status"] for x in r] == ["cancelled", "queued"]
    assert r[1]["trigger"] == "system" and r[1]["params"] == r[0]["params"]
    assert runs("dr_after")[0]["status"] == "queued"  # still waiting for the next drain


def test_summary_is_counts_only(caplog):
    def secretive(ctx):
        ctx.item("k1", "ok")
        ctx.log("PRIVATE-LOG-LINE")
        return "PRIVATE-MESSAGE"

    reg("dr_secret", secretive)
    runner.enqueue("dr_secret", params={"note": "PRIVATE-PARAM"})
    with caplog.at_level(logging.INFO, logger="app.jobs.drain"):
        assert drain.main([]) == 0
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "app.jobs.drain"]
    assert len(lines) == 1
    line = lines[0]
    assert "jobs=1" in line and "done=1" in line and "items_ok=1" in line
    for private in ("PRIVATE-PARAM", "PRIVATE-MESSAGE", "PRIVATE-LOG-LINE", "dr_secret"):
        assert private not in line


def test_seeded_db_gets_bar_counts_once(monkeypatch):
    """N021: a seeded cloud DB has no bars_coverage; the drain runs housekeeping once to make it."""
    import importlib

    from app import bardb
    from app.jobs.defs import housekeeping

    if "housekeeping" not in registry._JOBS:  # an earlier test's cleanup may have dropped it
        importlib.reload(housekeeping)
    monkeypatch.setattr(drain, "_setup_logging", lambda: None)  # keep the test's log levels
    assert drain.main([]) == 0  # local mode: nothing extra
    assert runs("housekeeping") == []
    monkeypatch.setattr(config, "RUNTIME", "actions")
    assert drain.main([]) == 0
    r = runs("housekeeping")
    assert len(r) == 1 and r[0]["status"] == "done" and r[0]["trigger"] == "system"
    assert "rows" in db.get_setting(bardb.COVERAGE_KEY)
    assert drain.main([]) == 0
    assert len(runs("housekeeping")) == 1  # the snapshot exists now: not queued again
