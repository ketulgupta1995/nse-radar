import pytest

from app import db
from app.jobs import registry, runner
from app.jobs.registry import JobDef


@pytest.fixture
def c(client):
    return client


def test_list_run_detail_and_retry(c):
    jobs = c.get("/api/jobs").json()
    assert jobs["paused"] is False
    noop = next(j for j in jobs["jobs"] if j["name"] == "noop")
    assert noop["group"] == "app" and noop["source_enabled"] is None
    assert noop["schedule"]["kind"] == "manual"

    rid = c.post("/api/jobs/noop/run", json={"params": {"n": 3, "fail_keys": ["k0", "k2"]}}).json()["run_id"]
    assert runner.run_one() == rid
    d = c.get(f"/api/jobs/runs/{rid}").json()
    assert (d["status"], d["done"], d["ok"], d["failed"]) == ("done", 3, 1, 2)
    assert d["duration_s"] is not None
    assert [i["key"] for i in d["items_failed"]] == ["k0", "k2"]
    assert len(c.get(f"/api/jobs/runs/{rid}/items?status=failed").json()) == 2

    new = c.post(f"/api/jobs/runs/{rid}/retry").json()["run_id"]
    run = c.get(f"/api/jobs/runs/{new}").json()
    assert run["trigger"] == "retry" and run["retry_of"] == rid
    runner.run_one()
    assert c.get(f"/api/jobs/runs/{new}").json()["done"] == 2

    r = c.post(f"/api/jobs/runs/{new}/retry")  # the retry itself had no failures
    assert r.status_code == 400 and "no failed items" in r.json()["detail"]


def test_logs_paging_and_run_lists(c):
    a = c.post("/api/jobs/noop/run", json={"params": {"n": 1}}).json()["run_id"]
    runner.run_one()
    b = c.post("/api/jobs/noop/run", json={"params": {"n": 2}}).json()["run_id"]
    runner.run_one()
    logs = c.get(f"/api/jobs/runs/{a}/logs").json()
    assert logs and c.get(f"/api/jobs/runs/{a}/logs?after_id={logs[-1]['id']}").json() == []
    ids = [r["id"] for r in c.get("/api/jobs/runs?job=noop").json()]
    assert ids == [b, a]
    assert [r["id"] for r in c.get(f"/api/jobs/runs?before_id={b}").json()] == [a]
    assert c.get("/api/jobs/runs/9999").status_code == 404


def test_stop_queued_and_unknown_job(c):
    rid = c.post("/api/jobs/noop/run", json={}).json()["run_id"]
    assert c.post(f"/api/jobs/runs/{rid}/stop").json()["status"] == "cancelled"
    assert c.post("/api/jobs/nope/run", json={}).status_code == 404


def test_pause_and_schedule(c):
    assert c.post("/api/jobs/pause", json={"paused": True}).json() == {"paused": True}
    assert c.get("/api/jobs").json()["paused"] is True
    assert c.post("/api/jobs/pause", json={"paused": "x"}).status_code == 400

    s = c.put("/api/jobs/noop/schedule", json={"kind": "daily", "at_time": "19:30", "weekdays_only": True})
    assert s.status_code == 200 and s.json()["next_run_at"] and s.json()["weekdays_only"] == 1
    assert c.put("/api/jobs/noop/schedule", json={"at_time": "7pm"}).status_code == 400
    assert c.put("/api/jobs/noop/schedule", json={"kind": "interval"}).status_code == 400
    assert c.put("/api/jobs/noop/schedule", json={"kind": "weekly", "weekday": 9}).status_code == 400
    assert c.put("/api/jobs/noop/schedule", json={"kind": "bogus"}).status_code == 400
    assert c.put("/api/jobs/ghost/schedule", json={}).status_code == 404
    m = c.put("/api/jobs/noop/schedule", json={"kind": "manual"}).json()
    assert m["next_run_at"] is None


def test_refresh_and_status(c):
    registry._JOBS.pop("fresh", None)
    registry.register(JobDef("fresh", "f", "", lambda ctx: None, {"kind": "manual"}, refresh=True, stage=2))
    try:
        c.post("/api/jobs/pause", json={"paused": True})
        ids = c.post("/api/jobs/refresh").json()["run_ids"]
        with db.tx() as conn:
            q = "SELECT job FROM job_runs WHERE id=?"
            queued = sorted(conn.execute(q, (i,)).fetchone()[0] for i in ids)
        # every job flagged refresh (including generated source jobs) is queued once
        assert queued == sorted(j.name for j in registry.all_jobs() if j.refresh)
        assert "fresh" in queued
        s = c.get("/api/jobs/status").json()
        assert s["updating"] is True and s["background"]["queued"] == len(ids)
        assert {"interactive", "last_trading_date"} <= set(s)
    finally:
        registry._JOBS.pop("fresh", None)
