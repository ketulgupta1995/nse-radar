import json
import logging
import sqlite3
import threading
import time
import traceback
from datetime import datetime

from app import db, timeutil
from app.jobs import registry
from app.jobs.context import MAX_MSG, JobContext, StopRequested

log = logging.getLogger(__name__)

LANES = ("background", "interactive")
_threads: dict[str, threading.Thread] = {}
_threads_lock = threading.Lock()


def _params_json(params: dict | None) -> str:
    return json.dumps(params or {}, sort_keys=True)


def enqueue(
    job: str, *, params: dict | None = None, trigger: str = "manual", retry_of: int | None = None
) -> int:
    pj = _params_json(params)
    with db.tx() as c:
        row = c.execute(
            "SELECT id FROM job_runs WHERE job=? AND params=? AND status IN ('queued','running') "
            "ORDER BY id LIMIT 1",
            (job, pj),
        ).fetchone()
        if row:
            return row["id"]
        cur = c.execute(
            "INSERT INTO job_runs(job, params, trigger, status, queued_at, retry_of) "
            "VALUES (?,?,?,'queued',?,?)",
            (job, pj, trigger, timeutil.now_iso(), retry_of),
        )
        return int(cur.lastrowid)


def request_stop(run_id: int) -> None:
    with db.tx() as c:
        cur = c.execute(
            "UPDATE job_runs SET status='cancelled', finished_at=?, message='cancelled before start' "
            "WHERE id=? AND status='queued'",
            (timeutil.now_iso(), run_id),
        )
        if cur.rowcount == 0:
            c.execute("UPDATE job_runs SET stop_requested=1 WHERE id=? AND status='running'", (run_id,))


def _job_info(name: str) -> tuple[str, int]:
    """(lane, stage) for a job name; unknown jobs count as background/5."""
    try:
        j = registry.get(name)
    except KeyError:
        return "background", 5
    return j.lane, j.stage


def _pick(lane: str) -> sqlite3.Row | None:
    with db.tx() as c:
        rows = c.execute("SELECT * FROM job_runs WHERE status='queued' ORDER BY id").fetchall()
        best = None
        for r in rows:
            ln, stage = _job_info(r["job"])
            if ln != lane:
                continue
            if best is None or stage < best[0]:
                best = (stage, r)
        if best is None:
            return None
        run = best[1]
        cur = c.execute(
            "UPDATE job_runs SET status='running', started_at=? WHERE id=? AND status='queued'",
            (timeutil.now_iso(), run["id"]),
        )
        return run if cur.rowcount == 1 else None


def _finish(run_id: int, status: str, message: str | None) -> None:
    with db.tx() as c:
        c.execute(
            "UPDATE job_runs SET status=?, finished_at=?, message=? WHERE id=?",
            (status, timeutil.now_iso(), (message or "")[:MAX_MSG] or None, run_id),
        )


def run_one(lane: str = "background") -> int | None:
    run = _pick(lane)
    if run is None:
        return None
    run_id = run["id"]
    ctx = JobContext(run_id, json.loads(run["params"]), run["job"])
    status, message = "done", None
    try:
        job = registry.get(run["job"])
        message = job.fn(ctx)
    except StopRequested:
        status, message = "cancelled", "stopped"
    except Exception as e:
        status, message = "failed", f"{type(e).__name__}: {e}"
        ctx.log(traceback.format_exc(), "error")
    _finish(run_id, status, message)
    if status == "done":
        _enqueue_followups(run_id, run["job"])
    return run_id


def _enqueue_followups(run_id: int, job_name: str) -> None:
    try:
        followups = registry.get(job_name).followups
    except KeyError:
        return
    with db.tx() as c:
        ok = c.execute("SELECT ok FROM job_runs WHERE id=?", (run_id,)).fetchone()["ok"]
    if ok <= 0:
        return
    for name in followups:
        try:
            registry.get(name)
        except KeyError:
            log.warning("unknown follow-up job %r after %s", name, job_name)
            continue
        enqueue(name, trigger="system")


def _loop(lane: str) -> None:
    while True:
        try:
            if run_one(lane) is None:
                time.sleep(1)
        except Exception:
            log.exception("worker loop error (%s)", lane)
            time.sleep(1)


def start_worker() -> None:
    with _threads_lock:
        for lane in LANES:
            t = _threads.get(lane)
            if t is not None and t.is_alive():
                continue
            t = threading.Thread(target=_loop, args=(lane,), name=f"job-worker-{lane}", daemon=True)
            _threads[lane] = t
            t.start()


def summary(row: sqlite3.Row) -> dict:
    dur = None
    if row["started_at"] and row["finished_at"]:
        dur = (
            datetime.fromisoformat(row["finished_at"]) - datetime.fromisoformat(row["started_at"])
        ).total_seconds()
    keys = (
        "id job trigger status queued_at started_at finished_at total done ok skipped failed "
        "message retry_of"
    ).split()
    d = {k: row[k] for k in keys}
    d["duration_s"] = dur
    return d


def status() -> dict:
    out: dict = {"updating": False}
    with db.tx() as c:
        rows = c.execute(
            "SELECT * FROM job_runs WHERE status IN ('queued','running') ORDER BY id"
        ).fetchall()
    for lane in LANES:
        out[lane] = {"running": None, "queued": 0}
    for r in rows:
        lane, stage = _job_info(r["job"])
        if r["status"] == "running":
            out[lane]["running"] = summary(r)
        else:
            out[lane]["queued"] += 1
        if lane == "background" and stage <= 3:
            out["updating"] = True
    return out


def recover_on_startup() -> None:
    with db.tx() as c:
        c.execute(
            "UPDATE job_runs SET status='interrupted', finished_at=?, message='app restarted' "
            "WHERE status='running'",
            (timeutil.now_iso(),),
        )
