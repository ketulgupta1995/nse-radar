from fastapi import APIRouter

from app import config, db
from app.cloud import dispatch

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
