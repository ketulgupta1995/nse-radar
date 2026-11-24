"""Run batch groups in parallel worker processes (SPEC §12.2).

Configs that share signals stay together in one worker; the parent is the only DB writer.
"""

import concurrent.futures as cf
import logging
import multiprocessing
import os
from collections.abc import Callable

from app import db
from app.backtest import batch
from app.backtest.engine import BacktestConfig
from app.jobs.context import StopRequested

log = logging.getLogger(__name__)

Share = list[tuple[int, str]]  # (input index, config json)
PLUGIN_PACKAGES = (  # the packages main.py imports at startup
    "app.sources.adapters", "app.jobs.defs", "app.alerts.scanners", "app.ai.providers", "app.ai.tasks",
)  # fmt: skip


def worker_count(cfgs: list[BacktestConfig]) -> int:
    """How many processes to use; 1 means run in-process."""
    try:
        want = int(db.get_setting("backtest_workers"))
    except (KeyError, TypeError, ValueError):
        want = 3
    want = max(1, min(6, want))
    keys = len({batch.signal_key(c) for c in cfgs})
    return max(1, min(want, keys, (os.cpu_count() or 1) - 1))


def schedule(cfgs: list[BacktestConfig], workers: int) -> list[list[int]]:
    """Deal signal bundles over workers, largest first. Returns input indexes per worker (no empty ones)."""
    bundles: dict[tuple, list[int]] = {}
    for i, c in enumerate(cfgs):
        bundles.setdefault(batch.signal_key(c), []).append(i)
    ordered = sorted(bundles.values(), key=len, reverse=True)
    loads: list[list[int]] = [[] for _ in range(workers)]
    groups: list[set] = [set() for _ in range(workers)]
    for b in ordered:
        gk = batch.group_key(cfgs[b[0]])
        empty = [w for w in range(workers) if not loads[w]]
        if empty:
            w = empty[0]
        else:
            same = [w for w in range(workers) if gk in groups[w]]
            w = min(same or range(workers), key=lambda x: len(loads[x]))
        loads[w].extend(b)
        groups[w].add(gk)
    return [sorted(ix) for ix in loads if ix]


def _worker(share: Share) -> list[tuple[int, dict | str]]:
    """Worker entry point (spawned process): register plug-ins, run the share, return picklable results."""
    from app.analytics import custom_indicators, price_store
    from app.plugins import import_all

    for pkg in PLUGIN_PACKAGES:
        import_all(pkg)
    try:
        custom_indicators.load_approved()
    except Exception:
        log.exception("worker could not load custom indicators")
    cfgs = [BacktestConfig.model_validate_json(js) for _, js in share]
    out: list[tuple[int, dict | str]] = []

    def on_result(j: int, r: dict | Exception) -> None:
        out.append((share[j][0], r if isinstance(r, dict) else str(r)))

    try:
        batch.run_batch(cfgs, None, on_result)
    except Exception as e:  # e.g. the shared load failed: rows not yet answered fail
        log.exception("worker batch failed")
        done = {i for i, _ in out}
        out.extend((i, str(e)) for i, _ in share if i not in done)
    price_store.save_if_dirty()
    return out


def run_parallel(
    cfgs: list[BacktestConfig],
    workers: int,
    ctx,
    on_result: Callable[[int, dict | Exception], None],
) -> None:
    """Run the configs in `workers` spawned processes; `on_result` is called in the parent per config."""
    shares = schedule(cfgs, workers)
    pool = cf.ProcessPoolExecutor(max_workers=len(shares), mp_context=multiprocessing.get_context("spawn"))
    futures: dict[cf.Future, list[int]] = {
        pool.submit(_worker, [(i, cfgs[i].model_dump_json()) for i in ix]): ix for ix in shares
    }
    pending = set(futures)
    try:
        while pending:
            ctx.check_stop()
            done, pending = cf.wait(pending, timeout=1, return_when=cf.FIRST_COMPLETED)
            for fut in done:
                _deliver(fut, futures[fut], on_result)
    except StopRequested:
        pool.shutdown(wait=False, cancel_futures=True)
        # shutdown() cannot interrupt a running task, so end the worker processes by hand.
        for p in list((getattr(pool, "_processes", None) or {}).values()):
            p.terminate()
        raise
    pool.shutdown(wait=True)


def _deliver(fut: cf.Future, ix: list[int], on_result: Callable[[int, dict | Exception], None]) -> None:
    try:
        results = fut.result()
    except Exception as e:  # includes BrokenProcessPool
        log.exception("batch worker failed")
        for i in ix:
            on_result(i, RuntimeError(f"worker process failed: {e}"))
        return
    for i, r in results:
        on_result(i, r if isinstance(r, dict) else RuntimeError(r))
