"""Run one queued AI request (SPEC §11 flow)."""

import json
import time

from app import db
from app.ai import base
from app.jobs.context import JobContext, StopRequested
from app.jobs.registry import JobDef, register


def _update(request_id: int, **cols) -> None:
    sets = ", ".join(k + "=?" for k in cols)
    with db.tx() as c:
        c.execute("UPDATE ai_requests SET " + sets + " WHERE id=?", (*cols.values(), request_id))


def run(ctx: JobContext) -> str | None:
    rid = int(ctx.params["request_id"])
    with db.tx() as c:
        row = c.execute("SELECT * FROM ai_requests WHERE id=?", (rid,)).fetchone()
    if row is None:
        raise ValueError(f"no ai_requests row {rid}")
    _update(rid, status="running")
    started = time.monotonic()
    ctx.set_total(1)
    try:
        prov = base.provider(row["provider"])
        response = prov.ask(
            row["prompt"], model=row["model"], timeout_s=int(db.get_setting("ai_timeout_s")),
            stop_check=ctx.stop_requested,
        )  # fmt: skip
        payload = json.loads(row["payload"] or "{}")
        post = base.task(row["kind"]).postprocess
        result = post(response, payload) if post else None
    except StopRequested:
        _update(rid, status="cancelled", duration_s=time.monotonic() - started)
        raise
    except (base.AIError, KeyError) as e:
        _update(rid, status="failed", error=str(e), duration_s=time.monotonic() - started)
        ctx.item(f"request {rid}", "failed", str(e))
        return f"failed: {e}"
    _update(
        rid, status="done", response=response, duration_s=time.monotonic() - started,
        result=json.dumps(result) if result is not None else None,
    )  # fmt: skip
    ctx.item(f"request {rid}", "ok")
    return "done"


register(
    JobDef(
        name="ai_request",
        title="Ask Claude",
        description="Sends one prompt to the chosen AI back-end and stores the answer.",
        fn=run,
        default_schedule={"kind": "manual"},
        retryable=False,
        stage=0,
        lane="interactive",
    )
)
