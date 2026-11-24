"""Run several explore backtests that share one setup (SPEC §6.3, §12.2)."""

import json
import logging

from app import db, timeutil
from app.backtest import parallel
from app.backtest.batch import run_batch
from app.backtest.engine import BacktestConfig
from app.jobs.context import JobContext, StopRequested
from app.jobs.defs.backtest import _update, finish_row, save_price_store, train_cfg
from app.jobs.registry import JobDef, register

log = logging.getLogger(__name__)


class _BatchCtx:
    """Progress is per config, so the engine's per-day `set_total` is ignored; stop checks pass through."""

    def __init__(self, ctx: JobContext) -> None:
        self._ctx = ctx

    def set_total(self, n: int) -> None:
        pass

    def check_stop(self) -> None:
        self._ctx.check_stop()


def _fail(ctx: JobContext, bid: int, msg: str) -> None:
    _update(bid, status="failed", warnings=json.dumps([f"Failed: {msg}"]), finished_at=timeutil.now_iso())
    ctx.item(f"backtest {bid}", "failed", msg)


def run(ctx: JobContext) -> str | None:
    try:
        return _run(ctx)
    finally:
        save_price_store()


def _run(ctx: JobContext) -> str | None:
    wanted = [int(i) for i in ctx.params["backtest_ids"]]
    with db.tx() as c:
        found = {r["id"]: r for r in c.execute("SELECT * FROM backtests").fetchall() if r["id"] in wanted}
    ids = [i for i in wanted if i in found]
    for bid in ids:
        _update(bid, status="running")
    ctx.set_total(len(ids))
    runnable: list[int] = []
    cfgs: list[BacktestConfig] = []
    for bid in ids:
        row = found[bid]
        try:
            if row["kind"] != "explore":
                raise ValueError("only training-period backtests can run in a batch")
            cfgs.append(train_cfg(BacktestConfig(**json.loads(row["config"]))))
            runnable.append(bid)
        except Exception as e:
            _fail(ctx, bid, str(e))
    finished: set[int] = set()

    def on_result(i: int, out) -> None:
        bid = runnable[i]
        finished.add(bid)
        if isinstance(out, Exception):
            _fail(ctx, bid, str(out))
            return
        try:
            cfg = BacktestConfig(**json.loads(found[bid]["config"]))
            finish_row(bid, found[bid], cfg, out)
        except Exception as e:
            _fail(ctx, bid, str(e))
            return
        ctx.item(f"backtest {bid}", "ok")

    try:
        workers = parallel.worker_count(cfgs) if cfgs else 1
        if workers > 1:
            parallel.run_parallel(cfgs, workers, ctx, on_result)
        else:
            run_batch(cfgs, _BatchCtx(ctx), on_result)
    except StopRequested:
        for bid in runnable:
            if bid not in finished:
                _update(bid, status="cancelled", finished_at=timeutil.now_iso())
        raise
    except Exception as e:  # the shared load itself failed
        log.exception("backtest batch failed")
        for bid in runnable:
            if bid not in finished:
                _fail(ctx, bid, str(e))
        return f"failed: {e}"
    return f"{len(finished)} backtests finished"


register(
    JobDef(
        name="backtest_batch",
        title="Backtest batch",
        description="Runs several training-period backtests that share one data load, and saves each result.",
        fn=run,
        default_schedule={"kind": "manual"},
        retryable=False,
        stage=1,
        lane="interactive",
    )
)
