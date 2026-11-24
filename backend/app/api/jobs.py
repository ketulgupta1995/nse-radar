import re
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException

from app import bardb, db, timeutil
from app.analytics import frames
from app.jobs import registry, runner, scheduler

router = APIRouter()

KINDS = ("interval", "daily", "weekly", "manual")
SCHED_KEYS = ("kind", "interval_min", "at_time", "weekday", "weekdays_only", "enabled", "next_run_at")


def _source_enabled(group: str, conn=None) -> bool | None:
    if not group.startswith("source:"):
        return None
    try:
        from app.sources import registry as src
    except ImportError:
        return None
    return src.is_enabled(group.split(":", 1)[1], conn)


def _run_summary(row) -> dict:
    d = runner.summary(row)
    if d["started_at"] and not d["finished_at"]:
        from datetime import datetime

        d["duration_s"] = (timeutil.now() - datetime.fromisoformat(d["started_at"])).total_seconds()
    return d


def _get_run(c, run_id: int):
    row = c.execute("SELECT * FROM job_runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "run not found")
    return row


def _schedule(row) -> dict | None:
    if row is None:
        return {k: None for k in SCHED_KEYS} | {"kind": "manual", "enabled": False, "weekdays_only": 0}
    d = {k: row[k] for k in SCHED_KEYS}
    d["enabled"] = bool(d["enabled"])
    return d


def _newest_runs(c, names: list[str], where: str) -> dict:
    """{job: its newest job_runs row matching `where`}: one statement, an index seek per job."""
    if not names:
        return {}
    values = ",".join("(?)" for _ in names)
    rows = c.execute(
        f"WITH n(job) AS (VALUES {values}) SELECT r.* FROM n JOIN job_runs r ON r.id = "
        f"(SELECT id FROM job_runs WHERE job = n.job AND {where} ORDER BY id DESC LIMIT 1)",
        names,
    ).fetchall()
    return {r["job"]: r for r in rows}


@router.get("/jobs")
def list_jobs() -> dict:
    all_jobs = registry.all_jobs()
    names = [j.name for j in all_jobs]
    jobs = []
    with db.tx() as c:  # a fixed handful of statements however many jobs there are (SPEC §17.5)
        scheds = {r["job"]: r for r in c.execute("SELECT * FROM job_schedules")}
        last = _newest_runs(c, names, "status NOT IN ('queued','running')")
        running = _newest_runs(c, names, "status='running'")
        enabled: dict[str, bool | None] = {}
        for j in all_jobs:
            if j.group not in enabled:
                enabled[j.group] = _source_enabled(j.group, c)
            jobs.append(
                {
                    "name": j.name,
                    "title": j.title,
                    "description": j.description,
                    "group": j.group,
                    "source_enabled": enabled[j.group],
                    "schedule": _schedule(scheds.get(j.name)),
                    "last_run": _run_summary(last[j.name]) if j.name in last else None,
                    "running": _run_summary(running[j.name]) if j.name in running else None,
                }
            )
        paused = db.get_setting("jobs_paused", c)
    return {"paused": bool(paused), "jobs": jobs}


def _validate(s: dict) -> None:
    kind = s["kind"]
    if kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(KINDS)}")
    if kind == "interval":
        v = s.get("interval_min")
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise HTTPException(400, "interval_min must be a whole number of minutes, at least 1")
    if kind in ("daily", "weekly"):
        t = s.get("at_time")
        if not isinstance(t, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            raise HTTPException(400, "at_time must look like HH:MM (24-hour)")
    if kind == "weekly":
        w = s.get("weekday")
        if not isinstance(w, int) or isinstance(w, bool) or not 0 <= w <= 6:
            raise HTTPException(400, "weekday must be 0 (Monday) to 6 (Sunday)")


@router.put("/jobs/{name}/schedule")
def put_schedule(name: str, body: Annotated[dict[str, Any], Body()]) -> dict:
    try:
        registry.get(name)
    except KeyError:
        raise HTTPException(404, "unknown job") from None
    unknown = set(body) - {"kind", "interval_min", "at_time", "weekday", "weekdays_only", "enabled"}
    if unknown:
        raise HTTPException(400, f"unknown schedule fields: {', '.join(sorted(unknown))}")
    with db.tx() as c:
        row = c.execute("SELECT * FROM job_schedules WHERE job=?", (name,)).fetchone()
    cur = {k: row[k] for k in SCHED_KEYS} if row else {"kind": "manual", "weekdays_only": 0, "enabled": 1}
    cur.update(body)
    _validate(cur)
    nxt = scheduler.compute_next_run(cur, timeutil.now())
    with db.tx() as c:
        c.execute(
            "INSERT INTO job_schedules(job, kind, interval_min, at_time, weekday, weekdays_only, enabled, "
            "next_run_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(job) DO UPDATE SET kind=excluded.kind, "
            "interval_min=excluded.interval_min, at_time=excluded.at_time, weekday=excluded.weekday, "
            "weekdays_only=excluded.weekdays_only, enabled=excluded.enabled, "
            "next_run_at=excluded.next_run_at",
            (
                name,
                cur["kind"],
                cur.get("interval_min"),
                cur.get("at_time"),
                cur.get("weekday"),
                int(bool(cur.get("weekdays_only"))),
                int(bool(cur.get("enabled", 1))),
                nxt.isoformat(timespec="seconds") if nxt else None,
            ),
        )
        return _schedule(c.execute("SELECT * FROM job_schedules WHERE job=?", (name,)).fetchone())


@router.post("/jobs/pause")
def pause(body: Annotated[dict[str, Any], Body()]) -> dict:
    paused = body.get("paused")
    if not isinstance(paused, bool):
        raise HTTPException(400, "paused must be true or false")
    db.set_setting("jobs_paused", paused)
    return {"paused": paused}


@router.post("/jobs/refresh")
def refresh() -> dict:
    jobs = [j for j in registry.all_jobs() if j.refresh]
    with db.tx() as c:  # one transaction for the on/off checks, not one per job (SPEC §17.5)
        enabled = {g: _source_enabled(g, c) for g in {j.group for j in jobs}}
    on = [j for j in jobs if enabled[j.group] is not False]
    return {"run_ids": [runner.enqueue(j.name, trigger="manual") for j in on]}


def _last_trading_date() -> str | None:
    def read() -> str | None:
        with db.read() as c:  # one key seek per (source, symbol)
            row = c.execute(bardb.LAST_DAY_SQL).fetchone()
        return bardb.iso(row[0]) if row else None

    # polled by the header: on Vercel reuse the answer for a few minutes (SPEC §17.2)
    return frames.memo("jobs.last_trading_date", read)


@router.get("/jobs/status")
def status() -> dict:
    return runner.status() | {"last_trading_date": _last_trading_date()}


@router.post("/jobs/{name}/run")
def run_now(name: str, body: Annotated[dict[str, Any] | None, Body()] = None) -> dict:
    try:
        registry.get(name)
    except KeyError:
        raise HTTPException(404, "unknown job") from None
    params = (body or {}).get("params") or {}
    if not isinstance(params, dict):
        raise HTTPException(400, "params must be an object")
    return {"run_id": runner.enqueue(name, params=params, trigger="manual")}


@router.get("/jobs/runs")
def list_runs(job: str | None = None, status: str | None = None, limit: int = 50,
              before_id: int | None = None) -> list[dict]:
    where, args = [], []
    if job:
        where.append("job=?")
        args.append(job)
    if status:
        where.append("status=?")
        args.append(status)
    if before_id is not None:
        where.append("id<?")
        args.append(before_id)
    sql = "SELECT * FROM job_runs" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY id DESC LIMIT ?"
    with db.tx() as c:
        return [_run_summary(r) for r in c.execute(sql, (*args, max(1, min(limit, 500)))).fetchall()]


@router.get("/jobs/runs/{run_id}")
def get_run(run_id: int) -> dict:
    with db.tx() as c:
        row = _get_run(c, run_id)
        failed = c.execute(
            "SELECT key, detail FROM job_items WHERE run_id=? AND status='failed' ORDER BY key", (run_id,)
        ).fetchall()
    return _run_summary(row) | {"items_failed": [dict(r) for r in failed]}


@router.get("/jobs/runs/{run_id}/items")
def run_items(run_id: int, status: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
    sql = "SELECT key, status, detail, at FROM job_items WHERE run_id=?"
    args: list = [run_id]
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY at, key LIMIT ? OFFSET ?"
    with db.tx() as c:
        _get_run(c, run_id)
        return [dict(r) for r in c.execute(sql, (*args, max(1, min(limit, 1000)), max(0, offset)))]


@router.get("/jobs/runs/{run_id}/logs")
def run_logs(run_id: int, after_id: int = 0) -> list[dict]:
    with db.tx() as c:
        _get_run(c, run_id)
        rows = c.execute(
            "SELECT id, at, level, msg FROM job_logs WHERE run_id=? AND id>? ORDER BY id", (run_id, after_id)
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/jobs/runs/{run_id}/stop")
def stop_run(run_id: int) -> dict:
    with db.tx() as c:
        _get_run(c, run_id)
    runner.request_stop(run_id)
    with db.tx() as c:
        return _run_summary(_get_run(c, run_id))


@router.post("/jobs/runs/{run_id}/retry")
def retry_run(run_id: int) -> dict:
    with db.tx() as c:
        row = _get_run(c, run_id)
        keys = [
            r["key"]
            for r in c.execute(
                "SELECT key FROM job_items WHERE run_id=? AND status='failed' ORDER BY key", (run_id,)
            )
        ]
    if not keys:
        raise HTTPException(400, "no failed items")
    new_id = runner.enqueue(row["job"], params={"keys": keys}, trigger="retry", retry_of=run_id)
    return {"run_id": new_id}


