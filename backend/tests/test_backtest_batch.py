from datetime import date

import numpy as np
import pandas as pd
import pytest

from app import db, timeutil
from app.analytics import frames, indicators, rules
from app.backtest import batch, engine
from app.backtest import metrics as metrics_mod
from app.backtest.engine import BacktestConfig, run_backtest
from app.jobs import runner
from app.jobs.context import JobContext
from app.jobs.defs import backtest_batch
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
IDX = pd.bdate_range("2023-01-02", periods=300)


def fake_frames(n_symbols=4) -> dict:
    out = {}
    for k in range(n_symbols):
        rng = np.random.default_rng(k)
        c = 100 * np.cumprod(1 + rng.normal(0.001, 0.02, len(IDX)))
        o = c * (1 + rng.normal(0, 0.003, len(IDX)))
        f = pd.DataFrame(
            {"open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c,
             "volume": rng.integers(1, 10, len(IDX)).astype(float)},
            index=IDX,
        )  # fmt: skip
        f.attrs["symbol"] = f"S{k}"
        out[f"S{k}"] = f
    return out


def rule(rsi_below=60, vol=3):
    return {
        "all": [
            {"left": {"ind": "volume"}, "op": ">", "right": {"value": vol}},
            {"left": {"ind": "rsi", "params": {"n": 14}}, "op": "<", "right": {"value": rsi_below}},
        ]
    }


def cfg(entry=None, stop=2, **kw):
    return BacktestConfig(
        entry_rule=entry or rule(),
        exits=[{"type": "stop_atr", "params": {"k": stop}}, {"type": "time_stop", "params": {"days": 20}}],
        start=kw.pop("start", "2023-01-02"),
        universe="current",
        **kw,
    )


@pytest.fixture(autouse=True)
def _db():
    db.init_db()
    db.set_setting("cost_model", ZERO)


@pytest.fixture
def fake_shared(monkeypatch):
    """`load_shared` builds a Shared from fake frames (and counts the loads)."""
    loads: list[int] = []

    def load(cfgs):
        loads.append(len(cfgs))
        return batch.Shared(fake_frames(), pd.Series(dtype=float), {}, None, 0)

    monkeypatch.setattr(batch, "load_shared", load)
    return loads


def alone(c: BacktestConfig) -> dict:
    out = run_backtest(c, frames=fake_frames(), bench=None, fund={})
    out["metrics"] = metrics_mod.split_metrics(out, "2023-09-01")
    return out


def five_configs() -> list[BacktestConfig]:
    return [
        cfg(stop=2),
        cfg(stop=3),
        cfg(max_positions=3),
        cfg(entry=rule(rsi_below=50)),
        cfg(rank_by={"ind": "rsi", "params": {"n": 14}}),
        cfg(start="2023-03-01"),
    ]


def test_batch_equals_single_runs(fake_shared):
    cfgs = five_configs()
    got: dict[int, dict] = {}
    batch.run_batch(cfgs, None, lambda i, r: got.__setitem__(i, r))
    assert fake_shared == [5, 1]  # two groups: start differs
    assert sorted(got) == list(range(6))
    for i, c in enumerate(cfgs):
        r = got[i]
        assert not isinstance(r, Exception)
        r["metrics"] = metrics_mod.split_metrics(r, "2023-09-01")
        want = alone(c)
        assert r["trades"] == want["trades"] and r["equity"] == want["equity"]
        assert r["metrics"] == want["metrics"] and r["warnings"] == want["warnings"]
    assert got[0]["trades"], "the rule should trade, or the test proves nothing"


def test_price_arrays_built_once_per_group(monkeypatch):
    calls = []
    real = engine._Prices
    monkeypatch.setattr(engine, "_Prices", lambda *a: calls.append(1) or real(*a))
    shared = batch.Shared(fake_frames(), pd.Series(dtype=float), {}, None, 0)
    for c in (cfg(stop=2), cfg(stop=3), cfg(entry=rule(rsi_below=50))):
        run_backtest(c, shared=shared)
    assert len(calls) == 1
    run_backtest(cfg(rank_by={"ind": "rsi", "params": {"n": 14}}), shared=shared)
    assert len(calls) == 2  # a new rank_by needs new arrays


def test_signals_built_once_per_rule_set(monkeypatch):
    calls = []
    real = engine._Signals
    monkeypatch.setattr(engine, "_Signals", lambda *a: calls.append(1) or real(*a))
    monkeypatch.setattr(engine, "SIGNAL_CACHE", 2)
    shared = batch.Shared(fake_frames(), pd.Series(dtype=float), {}, None, 0)
    exit_rule = {"type": "rule_exit", "params": {"rule": rule(rsi_below=30)}}
    runs = [
        cfg(stop=2), cfg(stop=3), cfg(stop=3, max_positions=2),  # same signals: built once
        cfg(entry=rule(rsi_below=50)),  # new entry rule
        cfg(stop=2).model_copy(update={"exits": [*cfg().exits, exit_rule]}),  # new exit rule
        cfg(stop=4),  # evicted (cache holds 2): built again
    ]
    for c in runs:
        r = run_backtest(c, shared=shared)
        alone = run_backtest(c, frames=fake_frames(), bench=pd.Series(dtype=float), fund={})
        assert r["trades"] == alone["trades"]
    assert len(calls) == 4 + len(runs)  # 4 shared builds, plus one per unshared check run
    assert sum(k[0] == "signals" for k in shared.arrays) == 2


def test_condition_memo(monkeypatch):
    f = fake_frames(1)["S0"]
    seen = []
    real = indicators.compute
    monkeypatch.setattr(indicators, "compute", lambda name, *a, **k: seen.append(name) or real(name, *a, **k))
    memo: dict = {}
    a = rules.evaluate(rule(60), f, None, None, None, memo)
    assert sorted(seen) == ["rsi", "volume"]
    b = rules.evaluate(rule(60), f, None, None, None, memo)
    assert len(seen) == 2 and a.equals(b)
    c = rules.evaluate(rule(40), f, None, None, None, memo)  # new threshold: volume cond reused, RSI redone
    assert len(seen) == 3 and not c.equals(a)
    n = len(seen)
    assert c.equals(rules.evaluate(rule(40), f))  # no memo: computed afresh, same answer
    assert len(seen) == n + 2 and len(memo) == 3


def test_failing_config_does_not_stop_others(fake_shared, monkeypatch):
    c1 = cfg(stop=3)
    orig = engine.run_backtest

    def flaky(c, ctx=None, **kw):
        if c is c1:
            raise ValueError("boom")
        return orig(c, ctx, **kw)

    monkeypatch.setattr(engine, "run_backtest", flaky)
    got: dict[int, object] = {}
    batch.run_batch([cfg(), c1, cfg(max_positions=2)], None, lambda i, r: got.__setitem__(i, r))
    assert isinstance(got[1], ValueError) and isinstance(got[0], dict) and isinstance(got[2], dict)


# ---- job and API ---------------------------------------------------------------------------

DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=300)]
RULE = {"all": [{"left": {"ind": "close"}, "op": ">", "right": {"value": 0}}]}


@pytest.fixture
def world(client, monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    registry.clear()
    caps = (CapabilitySpec("bars", "by_symbol", (), adjusted=True), CapabilitySpec("index", "whole", ()))
    registry.register(type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d",
                                                 "homepage": "h", "capabilities": caps})())  # fmt: skip
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('UP','Up',1)")
        bars = [Bar("UP", d, 100 + i, 101 + i, 99 + i, 100 + i, 1000.0) for i, d in enumerate(DAYS)]
        save_bars("px", bars, c)
        save_index("px", [IndexBar(frames.INDEX_NAME, d, 1000.0) for d in DAYS], c)
    frames.invalidate()
    yield
    registry.clear()
    frames.invalidate()


def _cfg(days=10, **kw):
    base = {"entry_rule": RULE, "start": DAYS[0], "oos_start": DAYS[200], "max_positions": 1,
            "universe": "current", "exits": [{"type": "time_stop", "params": {"days": days}}]}  # fmt: skip
    return {**base, **kw}


def _post(client, configs, name="b"):
    return client.post("/api/backtests/batch", json={"name": name, "configs": configs})


def test_api_validation(world, client):
    assert _post(client, []).status_code == 400
    assert _post(client, [_cfg()] * 21).status_code == 400
    r = _post(client, [_cfg(), _cfg(exits=[{"type": "zzz"}])])
    assert r.status_code == 400 and "1" in r.json()["detail"]
    assert client.get("/api/backtests").json() == []


def test_api_creates_rows_and_one_job(world, client):
    r = _post(client, [_cfg(5), _cfg(10), _cfg(20)])
    assert r.status_code == 200
    body = r.json()
    assert len(body["ids"]) == 3
    rows = [client.get(f"/api/backtests/{i}").json() for i in body["ids"]]
    assert {x["kind"] for x in rows} == {"explore"} and {x["run_id"] for x in rows} == {body["run_id"]}
    assert [x["name"] for x in rows] == ["b #1", "b #2", "b #3"]
    assert rows[2]["explore_runs"] == 3


def test_api_names(world, client):
    two = [_cfg(5), _cfg(10)]
    bad = client.post("/api/backtests/batch", json={"name": None, "configs": two, "names": ["a"]})
    assert bad.status_code == 400
    assert client.get("/api/backtests").json() == []
    ok = client.post("/api/backtests/batch", json={"name": None, "configs": two, "names": ["a", "b"]})
    assert ok.status_code == 200
    assert [client.get(f"/api/backtests/{i}").json()["name"] for i in ok.json()["ids"]] == ["a", "b"]


def test_job_runs_all_rows(world, client):
    ids = _post(client, [_cfg(5), _cfg(10), _cfg(20)]).json()
    assert runner.run_one("interactive") == ids["run_id"]
    rows = [client.get(f"/api/backtests/{i}").json() for i in ids["ids"]]
    assert [x["status"] for x in rows] == ["done"] * 3
    assert all(x["metrics"]["is"] and x["metrics"]["oos"] is None for x in rows)
    with db.tx() as c:
        items = c.execute("SELECT status FROM job_items WHERE run_id=?", (ids["run_id"],)).fetchall()
        total = c.execute("SELECT total FROM job_runs WHERE id=?", (ids["run_id"],)).fetchone()[0]
    assert [i["status"] for i in items] == ["ok"] * 3 and total == 3
    single = _post(client, [_cfg(5)]).json()
    runner.run_one("interactive")
    one = client.get(f"/api/backtests/{single['ids'][0]}").json()
    assert one["metrics"] == rows[0]["metrics"] and one["trades"] == rows[0]["trades"]


def test_job_stop_cancels_the_rest(world, client, monkeypatch):
    ids = _post(client, [_cfg(5), _cfg(10), _cfg(20)]).json()["ids"]
    done = []
    orig = backtest_batch.finish_row
    monkeypatch.setattr(backtest_batch, "finish_row", lambda *a: (orig(*a), done.append(1)))
    monkeypatch.setattr(JobContext, "stop_requested", lambda self: bool(done))
    runner.run_one("interactive")
    status = [client.get(f"/api/backtests/{i}").json()["status"] for i in ids]
    assert status == ["done", "cancelled", "cancelled"]


def test_job_skips_deleted_rows(world, client):
    ids = _post(client, [_cfg(5), _cfg(10)]).json()["ids"]
    client.delete(f"/api/backtests/{ids[0]}")
    runner.run_one("interactive")
    assert client.get(f"/api/backtests/{ids[1]}").json()["status"] == "done"
