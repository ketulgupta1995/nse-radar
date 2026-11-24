import pytest

from app import db
from app.jobs import registry, runner
from app.jobs.registry import JobDef


@pytest.fixture(autouse=True)
def _db():
    db.init_db()
    import app.jobs.defs.noop  # noqa: F401  (registers noop)


def run_row(rid):
    with db.tx() as c:
        return c.execute("SELECT * FROM job_runs WHERE id=?", (rid,)).fetchone()


def reg(name, fn=lambda ctx: None, **kw):
    registry._JOBS.pop(name, None)
    return registry.register(JobDef(name, name, "", fn, {"kind": "manual"}, **kw))


@pytest.fixture(autouse=True)
def _cleanup():
    before = set(registry._JOBS)
    yield
    for k in set(registry._JOBS) - before:
        registry._JOBS.pop(k)


def test_run_lifecycle_and_counts():
    rid = runner.enqueue("noop", params={"n": 4, "fail_keys": ["k1"]})
    assert run_row(rid)["status"] == "queued"
    assert runner.run_one() == rid
    r = run_row(rid)
    assert r["status"] == "done" and r["started_at"] and r["finished_at"]
    assert (r["total"], r["done"], r["ok"], r["failed"]) == (4, 4, 3, 1)
    assert r["ok"] + r["failed"] + r["skipped"] == r["done"]


def test_exception_fails_with_traceback():
    def boom(ctx):
        raise RuntimeError("kaboom")

    reg("boom", boom)
    rid = runner.enqueue("boom")
    runner.run_one()
    assert run_row(rid)["status"] == "failed"
    with db.tx() as c:
        logs = [r["msg"] for r in c.execute("SELECT msg FROM job_logs WHERE run_id=?", (rid,))]
    assert any("Traceback" in m and "kaboom" in m for m in logs)


def test_stop_queued_and_running():
    rid = runner.enqueue("noop")
    runner.request_stop(rid)
    assert run_row(rid)["status"] == "cancelled"
    assert runner.run_one() is None

    def stopper(ctx):
        runner.request_stop(ctx.run_id)
        ctx.check_stop()
        return "unreachable"

    reg("stopper", stopper)
    rid = runner.enqueue("stopper")
    runner.run_one()
    assert run_row(rid)["status"] == "cancelled"


def test_recover_on_startup():
    rid = runner.enqueue("noop")
    with db.tx() as c:
        c.execute("UPDATE job_runs SET status='running' WHERE id=?", (rid,))
    runner.recover_on_startup()
    assert run_row(rid)["status"] == "interrupted"


def test_enqueue_dedupe():
    a = runner.enqueue("noop", params={"n": 1, "x": 2})
    b = runner.enqueue("noop", params={"x": 2, "n": 1})
    c = runner.enqueue("noop", params={"n": 2})
    assert a == b and c != a
    runner.run_one()
    assert runner.enqueue("noop", params={"n": 1, "x": 2}) != a


def test_stage_order():
    reg("s7", stage=7)
    reg("s1", stage=1)
    first = runner.enqueue("s7")
    second = runner.enqueue("s1")
    assert runner.run_one() == second
    assert runner.run_one() == first


def test_lanes():
    reg("inter", lane="interactive")
    bg = runner.enqueue("noop")
    it = runner.enqueue("inter")
    assert runner.run_one("background") == bg
    assert runner.run_one("background") is None
    assert runner.run_one("interactive") == it


def test_followups():
    reg("child")
    reg("parent_ok", lambda ctx: ctx.item("a", "ok"), followups=("child", "ghost"))
    reg("parent_zero", lambda ctx: None, followups=("child",))

    def bad(ctx):
        ctx.item("a", "ok")
        raise RuntimeError("x")

    reg("parent_fail", bad, followups=("child",))
    for p in ("parent_zero", "parent_fail"):
        runner.enqueue(p)
        runner.run_one()
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM job_runs WHERE job='child'").fetchone()[0] == 0
    runner.enqueue("parent_ok")
    runner.run_one()
    with db.tx() as c:
        rows = c.execute("SELECT trigger FROM job_runs WHERE job='child'").fetchall()
    assert [r["trigger"] for r in rows] == ["system"]


def test_status_updating():
    reg("early", stage=2)
    reg("late", stage=7)
    runner.enqueue("late")
    assert runner.status()["updating"] is False
    rid = runner.enqueue("early")
    s = runner.status()
    assert s["updating"] is True and s["background"]["queued"] == 2
    runner.run_one()
    assert run_row(rid)["status"] == "done"
    assert runner.status()["updating"] is False


def test_duplicate_registration_and_log_truncation():
    with pytest.raises(ValueError):
        registry.register(registry.get("noop"))

    def chatty(ctx):
        ctx.log("x" * 10000)

    reg("chatty", chatty)
    rid = runner.enqueue("chatty")
    runner.run_one()
    with db.tx() as c:
        assert len(c.execute("SELECT msg FROM job_logs WHERE run_id=?", (rid,)).fetchone()[0]) == 4000
