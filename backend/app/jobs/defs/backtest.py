"""Run one saved backtest (SPEC §12)."""

import json
import logging
from datetime import date, timedelta

import pandas as pd

from app import db, timeutil
from app.analytics import price_store
from app.backtest import metrics
from app.backtest.engine import BacktestConfig, run_backtest
from app.jobs.context import JobContext, StopRequested
from app.jobs.registry import JobDef, register

MAX_POINTS = 2000
log = logging.getLogger(__name__)


def save_price_store() -> None:
    """Persist the raw price store after a run; a failure here must never fail the backtest."""
    try:
        price_store.save_if_dirty()
    except Exception:
        log.exception("could not save the price store")


def _weekly(equity: list[dict]) -> list[dict]:
    """Keep the last point of each calendar week."""
    last: dict[str, dict] = {}
    for e in equity:
        last[pd.Timestamp(e["t"]).strftime("%G-%V")] = e
    return list(last.values())


def _update(bid: int, **cols) -> None:
    sets = ", ".join(k + "=?" for k in cols)
    with db.tx() as c:
        c.execute("UPDATE backtests SET " + sets + " WHERE id=?", (*cols.values(), bid))


def oos_of(cfg: BacktestConfig) -> str:
    return cfg.oos_start or db.get_setting("holdout_start")


def train_cfg(cfg: BacktestConfig) -> BacktestConfig:
    """An explore row simulates the training period only: it ends the day before the test period."""
    train_end = (date.fromisoformat(oos_of(cfg)) - timedelta(days=1)).isoformat()
    return cfg.model_copy(update={"end": train_end})


def finish_row(bid: int, row, cfg: BacktestConfig, result: dict) -> None:
    """Turn an engine result into metrics, warnings and thinned equity, and save the row as done.

    `result` comes from `run_backtest(train_cfg(cfg))` for an explore row, else from `run_backtest(cfg)`.
    """
    oos = oos_of(cfg)
    extra: list[str] = []
    if row["kind"] == "explore":  # training period only: no test-period bar is simulated
        eq = result["equity"]
        first, last = (eq[0]["t"], eq[-1]["t"]) if eq else ("", "")
        result["metrics"] = {
            "is": metrics.compute_metrics(eq, result["trades"], first, last),
            "all": None, "oos": None, "oos_start": oos,
        }  # fmt: skip
    else:  # final and legacy rows: the whole period, split at oos_start
        result["metrics"] = metrics.split_metrics(result, oos)
        result["metrics"]["oos_start"] = oos
        if row["kind"] == "final":
            pending = json.loads(row["metrics"] or "{}")
            result["metrics"]["attempt"] = pending.get("attempt")
            extra = pending.get("final_warnings", [])
    warnings = [*metrics.warnings_for(result, cfg), *extra]
    equity = result["equity"]
    if len(equity) > MAX_POINTS:
        equity = _weekly(equity)
    _update(
        bid, status="done", metrics=json.dumps(result["metrics"]), equity=json.dumps(equity),
        trades=json.dumps(result["trades"]), warnings=json.dumps(warnings),
        finished_at=timeutil.now_iso(),
    )  # fmt: skip


def run(ctx: JobContext) -> str | None:
    try:
        return _run(ctx)
    finally:
        save_price_store()


def _run(ctx: JobContext) -> str | None:
    bid = int(ctx.params["backtest_id"])
    with db.tx() as c:
        row = c.execute("SELECT * FROM backtests WHERE id=?", (bid,)).fetchone()
    if row is None:
        return "backtest was deleted"
    _update(bid, status="running")
    try:
        cfg = BacktestConfig(**json.loads(row["config"]))
        run_cfg = train_cfg(cfg) if row["kind"] == "explore" else cfg
        finish_row(bid, row, cfg, run_backtest(run_cfg, ctx))
    except StopRequested:
        _update(bid, status="cancelled", finished_at=timeutil.now_iso())
        raise
    except Exception as e:
        _update(bid, status="failed", warnings=json.dumps([f"Failed: {e}"]), finished_at=timeutil.now_iso())
        ctx.item(f"backtest {bid}", "failed", str(e))
        return f"failed: {e}"
    ctx.item(f"backtest {bid}", "ok")
    return "done"


register(
    JobDef(
        name="backtest",
        title="Backtest",
        description="Replays a rule on past prices with realistic costs and saves the results.",
        fn=run,
        default_schedule={"kind": "manual"},
        retryable=False,
        stage=1,
        lane="interactive",
    )
)
