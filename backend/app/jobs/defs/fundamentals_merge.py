"""Merge every source's fundamentals into one record per company (SPEC §9.4)."""

import json

from app import db, timeutil
from app.analytics import fundamentals
from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register


def _symbols() -> list[str]:
    with db.tx() as c:
        rows = c.execute(
            "SELECT symbol FROM fund_snapshots UNION SELECT symbol FROM quarters ORDER BY symbol"
        ).fetchall()
    return [r["symbol"] for r in rows]


def run(ctx: JobContext) -> str | None:
    keys = ctx.params.get("keys") or _symbols()
    ctx.set_total(len(keys))
    merged = 0
    for sym in keys:
        ctx.check_stop()
        try:
            with db.tx() as c:
                data, origin = fundamentals.merge(sym, c)
                if not data:
                    ctx.item(sym, "skipped", "no fundamentals")
                    continue
                c.execute(
                    "INSERT INTO fundamentals(symbol, updated_at, data, sources) VALUES (?,?,?,?) "
                    "ON CONFLICT(symbol) DO UPDATE SET updated_at=excluded.updated_at, "
                    "data=excluded.data, sources=excluded.sources",
                    (sym.upper(), timeutil.now_iso(), json.dumps(data), json.dumps(origin)),
                )
            merged += 1
            ctx.item(sym, "ok", f"{len(data)} fields")
        except Exception as e:  # one symbol never fails the run
            ctx.item(sym, "failed", f"{type(e).__name__}: {e}")
    return f"merged {merged} of {len(keys)} companies"


register(
    JobDef(
        name="fundamentals_merge",
        title="Merge fundamentals",
        description="Combines every source's ratios into one record per company, noting each field's source.",
        fn=run,
        default_schedule={"kind": "daily", "at_time": "23:30"},
        stage=6,
        followups=("screens_run",),
    )
)
