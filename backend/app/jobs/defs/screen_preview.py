"""Preview an unsaved screen rule over the whole universe (SPEC §10, §17.5).

`POST /api/screens/preview` enqueues this job instead of scanning on the request (a scan loads a
frame per universe stock). Each matching stock becomes one `ok` item: key = symbol, detail = the JSON
of its indicator values, so the Screener reads the result from `GET /api/jobs/runs/{id}/items`.
Nothing is saved to `screen_results`.
"""

import json

from app import db, timeutil
from app.analytics import screens
from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register


def _save_matches(run_id: int, rows: list[dict]) -> None:
    """All items in one batched write (a per-row loop is slow against remote Turso, §17.11)."""
    now = timeutil.now_iso()
    with db.tx() as c:
        c.executemany(
            "INSERT OR REPLACE INTO job_items(run_id, key, status, detail, at) VALUES (?,?,'ok',?,?)",
            [(run_id, r["symbol"], json.dumps(r["values"]), now) for r in rows],
        )
        n = len(rows)
        c.execute("UPDATE job_runs SET total=?, done=?, ok=? WHERE id=?", (n, n, n, run_id))


def run(ctx: JobContext) -> str | None:
    rows = screens.scan(ctx.params.get("rule") or {}, ctx)  # a bad rule fails the run with its message
    ctx.check_stop()
    _save_matches(ctx.run_id, rows)
    return f"{len(rows)} {'stock matches' if len(rows) == 1 else 'stocks match'}"


register(
    JobDef(
        name="screen_preview",
        title="Preview a screen",
        description="Checks a rule against every stock in the universe without saving it "
        "(the Preview button).",
        fn=run,
        default_schedule={"kind": "manual"},
        retryable=False,
        stage=1,
        lane="interactive",
    )
)
