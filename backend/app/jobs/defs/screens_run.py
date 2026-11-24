"""Run saved screens over the universe (SPEC §10)."""

from app import db
from app.analytics import score, screens
from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register


def _selected(params: dict) -> list[tuple[int, str]]:
    with db.tx() as c:
        rows = c.execute("SELECT id, name FROM screens ORDER BY id").fetchall()
    if params.get("screen_ids"):
        ids = {int(i) for i in params["screen_ids"]}
        return [(r["id"], r["name"]) for r in rows if r["id"] in ids]
    if params.get("keys"):  # retry: failed item keys are screen names
        names = set(params["keys"])
        return [(r["id"], r["name"]) for r in rows if r["name"] in names]
    return [(r["id"], r["name"]) for r in rows]


def run(ctx: JobContext) -> str | None:
    chosen = _selected(ctx.params)
    ctx.set_total(len(chosen))
    total = 0
    for screen_id, name in chosen:
        ctx.check_stop()
        try:
            n = len(screens.run_screen(screen_id, ctx))
        except Exception as e:  # one bad screen never fails the run
            ctx.item(name, "failed", f"{type(e).__name__}: {e}")
            continue
        total += n
        ctx.item(name, "ok", f"{n} matches")
    ctx.check_stop()
    score.save_prices()  # the shortlist on Vercel reads these (SPEC §17.5)
    return f"{len(chosen)} screens, {total} matches"


register(
    JobDef(
        name="screens_run",
        title="Run screens",
        description="Runs every saved screen over the whole universe on the latest prices.",
        fn=run,
        default_schedule={"kind": "daily", "at_time": "21:30", "weekdays_only": 1},
        stage=7,
        followups=("signals_track",),
    )
)
