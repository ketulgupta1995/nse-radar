"""Run every alert scanner and store new alerts (SPEC §13.2)."""

import logging

from app import db, timeutil
from app.alerts.base import all_scanners
from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register

log = logging.getLogger(__name__)


def run(ctx: JobContext) -> str | None:
    scanners = all_scanners()
    ctx.set_total(len(scanners))
    total = 0
    for s in scanners:
        ctx.check_stop()
        try:
            # Scanners read on their own connection, outside any write transaction.
            conn = db.connect()
            try:
                drafts = s.fn(conn, timeutil.now())
            finally:
                conn.close()
            with db.tx() as c:
                new = sum(
                    db.insert_alert(
                        d.kind, d.message, dedupe_key=d.dedupe_key, symbol=d.symbol,
                        link=d.link, severity=d.severity, conn=c,
                    )
                    for d in drafts
                )  # fmt: skip
        except Exception as e:  # one failing scanner never stops the others
            ctx.log(f"{s.kind}: {type(e).__name__}: {e}", "error")
            ctx.item(s.kind, "failed", f"{type(e).__name__}: {e}")
            continue
        total += new
        ctx.item(s.kind, "ok", f"{new} new")
    return f"{total} new alerts from {len(scanners)} scanners"


register(
    JobDef(
        name="alerts_scan",
        title="Check for alerts",
        description="Looks for stops and targets hit, new announcements, new screen matches and stale data.",
        fn=run,
        default_schedule={"kind": "interval", "interval_min": 60},
        stage=8,
    )
)
