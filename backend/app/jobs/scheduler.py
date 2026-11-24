import logging
import os
import threading
import time
from datetime import datetime, timedelta

from app import db, timeutil
from app.jobs import registry, runner

log = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_lock = threading.Lock()


def _at(day: datetime, at_time: str) -> datetime:
    h, m = (int(x) for x in at_time.split(":")[:2])
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def compute_next_run(sched: dict, after: datetime) -> datetime | None:
    kind = sched.get("kind")
    if kind == "interval":
        return after + timedelta(minutes=int(sched["interval_min"]))
    if kind == "daily":
        cand = _at(after, sched["at_time"])
        if cand <= after:
            cand += timedelta(days=1)
        if sched.get("weekdays_only"):
            while cand.weekday() >= 5:
                cand += timedelta(days=1)
        return cand
    if kind == "weekly":
        cand = _at(after, sched["at_time"])
        cand += timedelta(days=(int(sched["weekday"]) - cand.weekday()) % 7)
        if cand <= after:
            cand += timedelta(days=7)
        return cand
    return None  # manual (or unknown): never runs on its own


def _sched_dict(row) -> dict:
    return {k: row[k] for k in ("kind", "interval_min", "at_time", "weekday", "weekdays_only")}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def tick(now: datetime) -> list[int]:
    """One pass: enqueue every enabled schedule that is due. Missed runs are not replayed."""
    if db.get_setting("jobs_paused"):
        return []
    with db.tx() as c:
        due = c.execute(
            "SELECT * FROM job_schedules WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at <= ?",
            (_iso(now),),
        ).fetchall()
    ids: list[int] = []
    for row in due:
        run_id = runner.enqueue(row["job"], trigger="schedule")
        ids.append(run_id)
        with db.tx() as c:
            c.execute(
                "UPDATE job_schedules SET next_run_at=?, last_run_id=? WHERE job=?",
                (_iso(compute_next_run(_sched_dict(row), now)), run_id, row["job"]),
            )
    return ids


def ensure_schedules() -> None:
    now = timeutil.now()
    with db.tx() as c:
        for job in registry.all_jobs():
            d = {"kind": "manual", "interval_min": None, "at_time": None, "weekday": None,
                 "weekdays_only": 0, **job.default_schedule}
            c.execute(
                "INSERT OR IGNORE INTO job_schedules"
                "(job, kind, interval_min, at_time, weekday, weekdays_only, enabled) VALUES (?,?,?,?,?,?,1)",
                (job.name, d["kind"], d["interval_min"], d["at_time"], d["weekday"], int(d["weekdays_only"])),
            )
        for row in c.execute("SELECT * FROM job_schedules WHERE next_run_at IS NULL").fetchall():
            nxt = compute_next_run(_sched_dict(row), now)
            if nxt:
                c.execute("UPDATE job_schedules SET next_run_at=? WHERE job=?", (_iso(nxt), row["job"]))


def _loop() -> None:
    while True:
        time.sleep(30)
        try:
            tick(timeutil.now())
        except Exception:
            log.exception("scheduler tick failed")


def start_scheduler() -> None:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, name="scheduler", daemon=True)
        _thread.start()


def startup() -> None:
    """Called by the app lifespan: create rows, catch up overdue jobs, start the thread."""
    ensure_schedules()
    tick(timeutil.now())
    if os.environ.get("STOCK_NO_THREADS") != "1":
        start_scheduler()
