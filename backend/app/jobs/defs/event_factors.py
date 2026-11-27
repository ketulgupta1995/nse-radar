"""Compute demerger and rights adjustment factors (SPEC §7.2a)."""

from __future__ import annotations

from app import db
from app.analytics import events
from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register


def run(ctx: JobContext) -> str | None:
    with db.tx() as c:
        events.refresh_event_factors(c)
    with db.tx() as c:  # its own transaction: a read after the writes above would send them one by one
        rows = c.execute("SELECT method, COUNT(*) AS n FROM event_factors GROUP BY method").fetchall()
    counts = {r["method"]: r["n"] for r in rows}
    ref, opn, cls, none = (counts.get(m, 0) for m in ("reference", "open", "close", "none"))
    total = ref + opn + cls + none
    return (
        f"{total} events: {ref} adjusted (reference), {opn} adjusted (open), "
        f"{cls} adjusted (close), {none} not adjusted"
    )


register(
    JobDef(
        name="event_factors",
        title="Demerger and rights factors",
        description="Works out price adjustments for listed demergers and rights issues.",
        fn=run,
        default_schedule={"kind": "manual"},
        stage=3,
    )
)
