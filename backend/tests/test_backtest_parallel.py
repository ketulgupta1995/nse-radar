import concurrent.futures as cf
from datetime import date

import pandas as pd
import pytest

from app import db, timeutil
from app.analytics import frames
from app.backtest import batch, parallel
from app.backtest.engine import BacktestConfig
from app.jobs import runner
from app.jobs.context import StopRequested
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec, IndexBar
from app.sources.store import save_bars, save_index

ZERO = {
    k: 0
    for k in (
        "brokerage_pct", "brokerage_cap_inr", "stt_pct", "exchange_pct", "sebi_pct",
        "stamp_buy_pct", "gst_pct", "dp_charge_inr", "slippage_pct",
    )
}  # fmt: skip


def rule(thr: float) -> dict:
    return {"all": [{"left": {"ind": "close"}, "op": ">", "right": {"value": thr}}]}


def cfg(thr: float = 1, days: int = 10, start: str = "2023-01-02", **kw) -> BacktestConfig:
    return BacktestConfig(
        entry_rule=rule(thr),
        exits=[{"type": "time_stop", "params": {"days": days}}],
        start=start,
        universe="current",
        max_positions=2,
        **kw,
    )


@pytest.fixture(autouse=True)
def _db():
    db.init_db()
    db.set_setting("cost_model", ZERO)


# ---- pure functions --------------------------------------------------------------------------


def test_signal_key():
    base = batch.signal_key(cfg())
    assert batch.signal_key(cfg(days=30)) == base  # exit params don't matter
    assert batch.signal_key(cfg(thr=2)) != base
    assert batch.signal_key(cfg(start="2023-02-01")) != base


def test_schedule_never_splits_bundles_or_leaves_workers_idle():
    cfgs = [cfg(1), cfg(1, days=20), cfg(1, days=30), cfg(2), cfg(3), cfg(4), cfg(5)]  # sizes 3,1,1,1,1
    shares = parallel.schedule(cfgs, 3)
    assert len(shares) == 3 and all(shares)
    assert sorted(i for s in shares for i in s) == list(range(7))
    assert any(set(s) >= {0, 1, 2} for s in shares)  # the 3-bundle stays whole


def test_schedule_covers_every_index_once():
    cfgs = [cfg(1), cfg(2), cfg(3, start="2023-02-01"), cfg(4)]
    shares = parallel.schedule(cfgs, 2)
    assert sorted(i for s in shares for i in s) == [0, 1, 2, 3]


def test_worker_count(monkeypatch):
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 8)
    cfgs = [cfg(1), cfg(2), cfg(3), cfg(4)]
    assert parallel.worker_count(cfgs) == 3  # default setting
    assert parallel.worker_count(cfgs[:2]) == 2  # fewer signal groups
    db.set_setting("backtest_workers", 1)
    assert parallel.worker_count(cfgs) == 1
    db.set_setting("backtest_workers", 50)
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 2)
    assert parallel.worker_count(cfgs) == 1  # one core kept free


# ---- fake in-process pool --------------------------------------------------------------------


class FakePool:
    def __init__(self, max_workers=None, mp_context=None):
        self._processes: dict = {}

    def submit(self, fn, *a):
        f: cf.Future = cf.Future()
        try:
            f.set_result(fn(*a))
        except BaseException as e:
            f.set_exception(e)
        return f

    def shutdown(self, wait=True, cancel_futures=False):
        pass


class Ctx:
    def __init__(self, stop_on_call=None):
        self.calls, self.stop_on_call = 0, stop_on_call

    def check_stop(self):
        self.calls += 1
        if self.calls == self.stop_on_call:
            raise StopRequested


def fake_worker(share):
    out = []
    for i, js in share:
        if i == 0:
            raise RuntimeError("worker down")
        out.append((i, {"echo": js}) if i != 3 else (i, "bad config"))
    return out


def test_failed_worker_fails_only_its_rows(monkeypatch):
    monkeypatch.setattr(parallel.cf, "ProcessPoolExecutor", FakePool)
    monkeypatch.setattr(parallel, "_worker", fake_worker)
    cfgs = [cfg(1), cfg(2), cfg(3), cfg(4)]
    got: dict = {}
    parallel.run_parallel(cfgs, 4, Ctx(), lambda i, r: got.__setitem__(i, r))
    assert sorted(got) == [0, 1, 2, 3]
    assert isinstance(got[0], RuntimeError) and "worker down" in str(got[0])
    assert isinstance(got[3], RuntimeError) and "bad config" in str(got[3])
    assert isinstance(got[1], dict) and isinstance(got[2], dict)


def test_stop_midway_terminates_and_raises(monkeypatch):
    killed = []

    class P:
        def terminate(self):
            killed.append(1)

    class Pool(FakePool):
        def __init__(self, *a, **k):
            super().__init__()
            self._processes = {1: P(), 2: P()}

    monkeypatch.setattr(parallel.cf, "ProcessPoolExecutor", Pool)
    monkeypatch.setattr(parallel, "_worker", lambda share: [(i, {"ok": 1}) for i, _ in share])
    got: dict = {}
    ctx = Ctx(stop_on_call=1)
    with pytest.raises(StopRequested):
        parallel.run_parallel([cfg(1), cfg(2), cfg(3), cfg(4)], 2, ctx, lambda i, r: got.__setitem__(i, r))
    assert got == {} and len(killed) == 2  # workers ended; the job marks the unfinished rows cancelled


# ---- world: a tiny DB the spawned workers can read -------------------------------------------

DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=300)]


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    registry.clear()
    # a spawned worker only knows the real adapters, so store the data under real source names
    for name, cap in (
        ("nse_bhav", CapabilitySpec("bars", "by_symbol", (), adjusted=True)),
        ("nse_archives", CapabilitySpec("index", "whole", ())),
    ):
        registry.register(type("px", (BaseSource,), {"name": name, "label": "px", "description": "d",
                                                     "homepage": "h", "capabilities": (cap,)})())  # fmt: skip
    with db.tx() as c:
        for n, sym in enumerate(["UP", "UP2"]):
            c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES (?,?,1)", (sym, sym))
            bars = [Bar(sym, d, 100 + i * (n + 1), 101 + i * (n + 1), 99 + i, 100 + i * (n + 1), 1000.0)
                    for i, d in enumerate(DAYS)]  # fmt: skip
            save_bars("nse_bhav", bars, c)
        save_index("nse_archives", [IndexBar(frames.INDEX_NAME, d, 1000.0) for d in DAYS], c)
    frames.invalidate()
    yield
    registry.clear()
    frames.invalidate()


def test_one_worker_never_builds_a_pool(client, world, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("pool created")

    monkeypatch.setattr(parallel.cf, "ProcessPoolExecutor", boom)
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 8)
    db.set_setting("backtest_workers", 1)
    configs = [
        {"entry_rule": rule(t), "start": DAYS[0], "oos_start": DAYS[200], "universe": "current",
         "max_positions": 1, "exits": [{"type": "time_stop", "params": {"days": 10}}]}
        for t in (1, 2)
    ]  # fmt: skip
    body = client.post("/api/backtests/batch", json={"name": "b", "configs": configs}).json()
    runner.run_one("interactive")
    assert [client.get(f"/api/backtests/{i}").json()["status"] for i in body["ids"]] == ["done", "done"]


def test_spawned_workers_equal_in_process(world, monkeypatch):
    s = DAYS[0]
    cfgs = [cfg(1, start=s), cfg(1, days=20, start=s), cfg(50, start=s), cfg(120, start=s)]
    want: dict = {}
    batch.run_batch(cfgs, None, lambda i, r: want.__setitem__(i, r))
    got: dict = {}
    parallel.run_parallel(cfgs, 2, Ctx(), lambda i, r: got.__setitem__(i, r))
    assert sorted(got) == [0, 1, 2, 3]
    for i in range(4):
        assert isinstance(want[i], dict), want[i]
        assert isinstance(got[i], dict), got[i]
        assert got[i]["trades"] == want[i]["trades"] and got[i]["equity"] == want[i]["equity"]
    assert want[0]["trades"], "the rule should trade, or the test proves nothing"
