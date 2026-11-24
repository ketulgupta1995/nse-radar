"""Weekly price checks over the whole history, not just the last 400 days (SPEC §7.3)."""

from __future__ import annotations

from app.jobs.context import JobContext
from app.jobs.defs.price_checks import run_checks
from app.jobs.registry import JobDef, register


def run(ctx: JobContext) -> str | None:
    return run_checks(ctx, None)


register(
    JobDef(
        name="price_checks_full",
        title="Price checks (full history)",
        description="Re-runs the price checks over all history to catch old missed splits and bonuses.",
        fn=run,
        default_schedule={"kind": "weekly", "weekday": 6, "at_time": "11:00"},
        stage=4,
    )
)
