"""Weekly check: backtest every saved screen over the last 12 months and the last 4 years.

Each row is an explore row whose "training" window ends today (oos_start = tomorrow), so the metrics
cover the whole recent window. Last week's weekly rows are deleted first, so the list holds one
12-month and one 4-year result per screen. These windows overlap the test period, so they are a
health check on current behaviour, not a fresh out-of-sample test.
"""

import json
from datetime import date, timedelta

from app import db, timeutil
from app.backtest.engine import BacktestConfig
from app.jobs.context import JobContext
from app.jobs.defs.backtest_batch import run_ids
from app.jobs.registry import JobDef, register

WINDOWS = (("12m", 365), ("4y", 4 * 365 + 1))
PREFIX = "Weekly "


def window_starts(today: date) -> list[tuple[str, str]]:
    return [(label, (today - timedelta(days=days)).isoformat()) for label, days in WINDOWS]


def _same_rule(a: dict, b: dict) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _setup_for(rule: dict, history: list[dict]) -> dict:
    """The latest non-weekly backtest of this exact rule lends its exits, sizing and ranking."""
    for cfg in history:  # newest first
        if _same_rule(cfg.get("entry_rule") or {}, rule):
            return {k: v for k, v in cfg.items() if k not in ("start", "end", "oos_start")}
    return {}


def make_rows(today: date) -> list[int]:
    """Delete last week's weekly rows and insert this week's; returns the new backtest ids."""
    oos = (today + timedelta(days=1)).isoformat()
    now = timeutil.now_iso()
    ids: list[int] = []
    with db.tx() as c:
        c.execute(
            "DELETE FROM backtests WHERE kind='explore' AND status <> 'running' AND name LIKE ?",
            (PREFIX + "%",),
        )
        screens = c.execute("SELECT name, rule FROM screens ORDER BY id").fetchall()
        history = [
            json.loads(r["config"])
            for r in c.execute(
                "SELECT config FROM backtests WHERE name IS NULL OR name NOT LIKE ? ORDER BY id DESC",
                (PREFIX + "%",),
            ).fetchall()
        ]
        for s in screens:
            rule = json.loads(s["rule"])
            base = _setup_for(rule, history)
            for label, start in window_starts(today):
                cfg = BacktestConfig(**{**base, "entry_rule": rule, "start": start, "end": None,
                                        "oos_start": oos})  # fmt: skip
                cur = c.execute(
                    "INSERT INTO backtests(name, config, status, kind, created_at) "
                    "VALUES (?,?,'queued','explore',?)",
                    (f"{PREFIX}{label}: {s['name']}", cfg.model_dump_json(), now),
                )
                ids.append(int(cur.lastrowid))
    return ids


def run(ctx: JobContext) -> str | None:
    ids = make_rows(timeutil.today())
    if not ids:
        return "no saved screens"
    return run_ids(ctx, ids)


register(
    JobDef(
        name="backtests_weekly",
        title="Weekly backtests",
        description="Backtests every saved screen over the last 12 months and the last 4 years. "
        "Replaces last week's results.",
        fn=run,
        default_schedule={"kind": "weekly", "at_time": "08:00", "weekday": 5},  # Saturday
        stage=7,
    )
)
