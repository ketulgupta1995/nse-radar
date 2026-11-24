import time

from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register


def run(ctx: JobContext) -> str | None:
    n = int(ctx.params.get("n", 5))
    pause = float(ctx.params.get("sleep", 0))
    fail_keys = set(ctx.params.get("fail_keys", []))
    keys = ctx.params.get("keys") or [f"k{i}" for i in range(n)]
    ctx.set_total(len(keys))
    for k in keys:
        ctx.check_stop()
        if pause:
            time.sleep(pause)
        if k in fail_keys:
            ctx.item(k, "failed", "simulated failure")
        else:
            ctx.item(k, "ok")
    ctx.log(f"noop processed {len(keys)} items")
    return f"noop: {len(keys)} items"


register(
    JobDef(
        name="noop",
        title="No-op (test job)",
        description="Does nothing useful. For tests and checking the Jobs page.",
        fn=run,
        default_schedule={"kind": "manual"},
    )
)
