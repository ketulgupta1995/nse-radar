"""Approve a pending custom indicator: trial-run its code, then register it (SPEC §8.3, §17.2).

Approving executes the owner-reviewed code once (in a child process), and Vercel never executes
custom indicators, so `POST /api/custom-indicators/{id}/approve` enqueues this job. The run's message
says what happened; the indicator's own status (approved, or still pending) is the result.
"""

import json

from app import db, timeutil
from app.analytics import custom_indicators as ci
from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register


def _sample(values: list) -> str:
    return ", ".join("–" if v is None else f"{v:.2f}" for v in values)


def approve(cid: int) -> tuple[bool, str]:
    """(approved?, plain message). Never raises for a bad indicator: it just stays pending."""
    with db.tx() as c:
        row = c.execute("SELECT * FROM custom_indicators WHERE id=?", (cid,)).fetchone()
    if row is None:
        return False, f"No custom indicator {cid}."
    if row["status"] != "pending":
        return False, f"This indicator is already {row['status']}."
    if problems := ci.static_check(row["code"]):
        return False, "; ".join(problems)
    schema = json.loads(row["params_schema"])
    try:
        parsed = ci.validate_params_schema(schema)
    except ValueError as e:
        return False, str(e)
    defaults = {p.name: int(p.default) if p.kind == "int" else p.default for p in parsed}
    trial = ci.trial_run(row["code"], defaults)
    if not trial.get("ok"):
        return False, trial.get("error", "The trial run failed.")
    with db.tx() as c:
        c.execute(
            "UPDATE custom_indicators SET status='approved', approved_at=? WHERE id=?",
            (timeutil.now_iso(), cid),
        )
        fresh = dict(c.execute("SELECT * FROM custom_indicators WHERE id=?", (cid,)).fetchone())
    fresh["params_schema"] = schema
    try:
        ci.register_row(fresh)
    except ValueError as e:
        with db.tx() as c:
            c.execute("UPDATE custom_indicators SET status='pending', approved_at=NULL WHERE id=?", (cid,))
        return False, str(e)
    return True, f"Approved. Trial run on made-up prices, last 5 values: {_sample(trial['sample'])}"


def run(ctx: JobContext) -> str | None:
    cid = int(ctx.params["indicator_id"])
    ok, message = approve(cid)
    ctx.item(str(cid), "ok" if ok else "failed", message)
    return message if ok else f"Could not approve: {message}"


register(
    JobDef(
        name="indicator_approve",
        title="Approve a custom indicator",
        description="Trial-runs a custom indicator's code on made-up prices and, if it works, turns it on.",
        fn=run,
        default_schedule={"kind": "manual"},
        retryable=False,
        stage=1,
        lane="interactive",
    )
)
