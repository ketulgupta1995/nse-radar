"""Nightly forward test: log new signals, then follow every logged signal's outcome (SPEC §16.4)."""

import logging

from app.analytics import score
from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register
from app.signals import log as signal_log
from app.signals import outcome

log = logging.getLogger(__name__)


def run(ctx: JobContext) -> str | None:
    ctx.set_total(2)
    logged = {"screen": 0, "shortlist": 0}
    try:
        shortlist = score.score_candidates()
        logged = signal_log.log_signals(shortlist)
        ctx.item("log", "ok", f"{logged['screen']} screen, {logged['shortlist']} shortlist")
    except Exception as e:  # logging failing must not stop outcomes from advancing
        log.exception("signal logging failed")
        ctx.item("log", "failed", f"{type(e).__name__}: {e}")
    counts = {"open": 0, "closed": 0}
    try:
        counts = outcome.update_outcomes(ctx)
        ctx.item("outcomes", "ok", f"open {counts['open']}, closed {counts['closed']}")
    except Exception as e:
        log.exception("signal outcomes failed")
        ctx.item("outcomes", "failed", f"{type(e).__name__}: {e}")
    new = logged["screen"] + logged["shortlist"]
    return (
        f"logged {new} new ({logged['screen']} screen, {logged['shortlist']} shortlist); "
        f"open {counts['open']}, closed {counts['closed']}"
    )


register(
    JobDef(
        name="signals_track",
        title="Track signals",
        description="Records the new ideas found tonight and follows how every earlier idea has done since.",
        fn=run,
        default_schedule={"kind": "manual"},
        stage=7,
        followups=("alerts_scan",),
    )
)
