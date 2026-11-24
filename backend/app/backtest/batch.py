"""Run several backtests that share one setup (SPEC §12.2).

Configs with the same universe and start date load frames, fundamentals, industries and breadth once;
condition results and price arrays are cached in `Shared` while the group runs.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from app.analytics import frames as frames_mod
from app.backtest import engine
from app.jobs.context import StopRequested

log = logging.getLogger(__name__)


@dataclass
class Shared:
    """One load, reused by every config in a group."""

    frames: dict
    bench: pd.Series
    fund: dict
    eligible: dict | None
    dropped: int
    industries: dict | None = None
    breadth: pd.Series | None = None
    memo: dict = field(default_factory=dict)  # rules condition memo
    arrays: dict = field(default_factory=dict)  # engine price-array cache, keyed by dates span + rank_by


def group_key(cfg: engine.BacktestConfig) -> tuple:
    return (cfg.universe, cfg.start)


def signal_key(cfg: engine.BacktestConfig) -> tuple:
    """Configs with equal keys share signals, so a parallel run keeps them in one worker (SPEC §12.2)."""
    exit_rules = [e["params"]["rule"] for e in cfg.exits if "rule" in e["params"]]
    canon = json.dumps([cfg.entry_rule, exit_rules, cfg.rank_by], sort_keys=True)
    return (cfg.universe, cfg.start, cfg.end, canon)


def load_shared(cfgs: list[engine.BacktestConfig]) -> Shared:
    """Load like the real path of `run_backtest`, with the union of what the configs need."""
    frames, bench, _, eligible, dropped = engine._load_real(cfgs[0], None, None, {})
    wanted = set().union(*(engine._used_fund_fields(c) for c in cfgs))
    fund = engine.overlay_fields(wanted, frames, engine.load_fund_snapshot())
    industries = None
    if any(c.max_per_industry for c in cfgs):
        industries = engine._industry_map(sorted(frames), None, True)
    breadth = frames_mod.load_breadth(200) if any(c.regime_scale for c in cfgs) else None
    return Shared(frames, bench, fund, eligible, dropped, industries, breadth)


def run_batch(
    cfgs: list[engine.BacktestConfig],
    ctx=None,
    on_result: Callable[[int, dict | Exception], None] | None = None,
) -> None:
    """Run every config, one shared load per group. `on_result(i, result_or_exception)` per config."""
    groups: dict[tuple, list[int]] = {}
    for i, cfg in enumerate(cfgs):
        groups.setdefault(group_key(cfg), []).append(i)
    for members in groups.values():
        shared = load_shared([cfgs[i] for i in members])
        try:
            for i in members:
                try:
                    out: dict | Exception = engine.run_backtest(cfgs[i], ctx, shared=shared)
                except StopRequested:
                    raise
                except Exception as e:
                    log.exception("batch config %d failed", i)
                    out = e
                if on_result:
                    on_result(i, out)
        finally:
            del shared  # drop the group's frames, memo and arrays before the next group
