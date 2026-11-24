from datetime import timedelta

from app import db, timeutil
from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register

KEEP_DAYS = 90


def run(ctx: JobContext) -> str | None:
    cutoff = (timeutil.now() - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    with db.tx() as c:
        runs = c.execute(
            "DELETE FROM job_runs WHERE finished_at IS NOT NULL AND finished_at < ?", (cutoff,)
        ).rowcount
        fetch = c.execute(
            "DELETE FROM source_fetch WHERE status='failed' AND fetched_at < ?", (cutoff,)
        ).rowcount
        alerts = c.execute(
            "DELETE FROM alerts WHERE seen_at IS NOT NULL AND seen_at < ?", (cutoff,)
        ).rowcount
    ctx.item("cleanup", "ok", f"{runs} runs, {fetch} failed fetches, {alerts} alerts")
    return f"deleted {runs} runs, {alerts} alerts, {fetch} failed fetch records"


register(
    JobDef(
        name="housekeeping",
        title="Housekeeping",
        description="Deletes job history, old failed-fetch records and seen alerts older than 90 days.",
        fn=run,
        default_schedule={"kind": "daily", "at_time": "03:00"},
        stage=9,
    )
)
