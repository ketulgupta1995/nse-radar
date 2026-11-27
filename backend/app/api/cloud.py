import hmac
import os

from fastapi import APIRouter, HTTPException, Request

from app import config, db, timeutil
from app.cloud import dispatch
from app.jobs import scheduler

router = APIRouter()


@router.get("/cloud/status")
def cloud_status() -> dict:
    """What the cloud worker is up to (SPEC §17.4). Light: one small query plus settings."""
    with db.read() as c:
        row = c.execute(
            "SELECT SUM(status='queued') AS queued, SUM(status='running') AS running, "
            "MIN(CASE WHEN status='queued' THEN queued_at END) AS oldest "
            "FROM job_runs WHERE status IN ('queued','running')"
        ).fetchone()
    dispatch.keepalive()
    return {
        "runtime": config.RUNTIME,
        "dispatch_configured": dispatch.configured(),
        "last_dispatch_at": dispatch.last_dispatch_at(),
        "queued": int(row["queued"] or 0),
        "running": int(row["running"] or 0),
        "oldest_queued_at": row["oldest"],
    }


@router.get("/cloud/tick")
def cloud_tick(request: Request) -> dict:
    """Vercel cron (vercel.json `crons`): queue every due schedule, then dispatch one drain.

    GitHub starts daily.yml's scheduled runs hours late, so the clock lives here instead. The jobs
    go into the DB, so any drain picks them up, even if GitHub drops a pending run. Exempt from the
    password gate; Vercel sends `Authorization: Bearer $CRON_SECRET` instead.
    """
    secret = os.environ.get("CRON_SECRET", "")
    if not secret:
        raise HTTPException(503, "CRON_SECRET is not set")
    given = request.headers.get("authorization", "")
    if not hmac.compare_digest(given.encode(), f"Bearer {secret}".encode()):
        raise HTTPException(401, "bad cron secret")
    ids = scheduler.tick(timeutil.now())
    return {"enqueued": len(ids)}
