import json
from datetime import date

import pandas as pd
import pytest

from app import db, timeutil
from app.analytics import frames
from app.backtest import metrics
from app.jobs import runner
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec, IndexBar
from app.sources.store import save_bars, save_index


def curve(values, start="2020-01-01", bench=None):
    dates = pd.date_range(start, periods=len(values), freq="D")
    return [
        {"t": d.strftime("%Y-%m-%d"), "v": v, **({"bench": bench[i]} if bench else {})}
        for i, (d, v) in enumerate(zip(dates, values, strict=True))
    ]


def trade(pnl, entry="2020-01-02", exit_="2020-01-05", pct=None):
    return {"symbol": "A", "entry_date": entry, "exit_date": exit_, "entry": 100, "exit": 100, "qty": 1,
            "pnl": pnl, "pnl_pct": pct if pct is not None else pnl, "reason": "x", "days": 3}  # fmt: skip


def test_cagr_and_drawdown():
    # exactly 366 days (2020 is a leap year): 100 -> 200 over 366 days
    eq = curve([100, 150, 90, 200], start="2020-01-01")
    eq[-1]["t"] = "2021-01-01"
    m = metrics.compute_metrics(eq, [], "2020-01-01", "2021-01-01")
    assert m["cagr"] == pytest.approx(((2.0) ** (365.25 / 366) - 1) * 100, abs=0.01)
    assert m["max_drawdown"] == pytest.approx(-40.0)  # 150 -> 90


def test_trade_stats_and_excess():
    eq = curve([100, 110, 121, 121, 121, 121], bench=[100] * 6)
    trades = [trade(10, pct=10), trade(-5, pct=-5), trade(20, pct=20)]
    m = metrics.compute_metrics(eq, trades, eq[0]["t"], eq[-1]["t"])
    assert m["trades"] == 3 and m["win_rate"] == pytest.approx(66.67)
    assert m["profit_factor"] == pytest.approx(6.0)  # 30 / 5
    assert m["avg_win"] == 15 and m["avg_loss"] == -5
    assert m["best"]["pnl_pct"] == 20 and m["worst"]["pnl_pct"] == -5
    assert m["bench_cagr"] == 0 and m["excess"] == m["cagr"]
    assert metrics.compute_metrics(eq, [trade(5)], eq[0]["t"], eq[-1]["t"])["profit_factor"] is None


def test_exposure():
    eq = curve([100] * 10)  # 2020-01-01 .. 01-10
    m = metrics.compute_metrics(eq, [trade(1, "2020-01-03", "2020-01-07")], "2020-01-01", "2020-01-10")
    assert m["exposure"] == 40.0  # held on the 3rd..6th = 4 of 10 days


def test_split_boundaries():
    eq = curve([100 + i for i in range(10)])
    res = {
        "equity": eq,
        "trades": [trade(1, "2020-01-02", "2020-01-03"), trade(1, "2020-01-08", "2020-01-09")],
    }
    s = metrics.split_metrics(res, "2020-01-06")
    assert s["all"]["trades"] == 2 and s["is"]["trades"] == 1 and s["oos"]["trades"] == 1


def test_warnings():
    res = {"equity": [], "trades": [trade(1)] * 3, "warnings": ["fund warning"],
           "metrics": {"all": {"trades": 3}, "is": {"excess": 20}, "oos": {"excess": 5}}}  # fmt: skip
    w = metrics.warnings_for(res)
    assert w[:3] == [metrics.SURVIVORSHIP, metrics.PRICE_ONLY, metrics.PAST]
    assert "fund warning" in w and metrics.FEW_TRADES in w and metrics.OVERFIT in w
    res["metrics"] = {"all": {"trades": 40}, "is": {"excess": 20}, "oos": {"excess": 12}}
    w = metrics.warnings_for(res)
    assert metrics.FEW_TRADES not in w and metrics.OVERFIT not in w


# ---- API flow ------------------------------------------------------------------------------

DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=300)]


@pytest.fixture
def world(client, monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    registry.clear()
    caps = (CapabilitySpec("bars", "by_symbol", (), adjusted=True), CapabilitySpec("index", "whole", ()))
    registry.register(type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d",
                                                 "homepage": "h", "capabilities": caps})())  # fmt: skip
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('UP','Up',1)")
        out = []
        for i, d in enumerate(DAYS):
            p = 100 + i
            out.append(Bar("UP", d, p, p + 1, p - 1, p, 1000.0))
        save_bars("px", out, c)
        save_index("px", [IndexBar(frames.INDEX_NAME, d, 1000.0) for d in DAYS], c)
    frames.invalidate()
    yield
    registry.clear()
    frames.invalidate()


RULE = {"all": [{"left": {"ind": "close"}, "op": ">", "right": {"value": 0}}]}


def _cfg(**kw):
    base = {"entry_rule": RULE, "start": DAYS[0], "oos_start": DAYS[200], "max_positions": 1,
            "universe": "current", "exits": [{"type": "time_stop", "params": {"days": 10}}]}  # fmt: skip
    return {**base, **kw}


def _run(client, config, name="t"):
    made = client.post("/api/backtests", json={"name": name, "config": config}).json()
    assert runner.run_one("interactive") == made["run_id"]
    return made["id"], client.get(f"/api/backtests/{made['id']}").json()


def _final(client, parent):
    r = client.post(f"/api/backtests/{parent}/final")
    assert r.status_code == 200, r.text
    assert runner.run_one("interactive") == r.json()["run_id"]
    return r.json()["id"], client.get(f"/api/backtests/{r.json()['id']}").json()


def _joined(got):
    return " ".join(got["warnings"])


def test_api_flow(world, client):
    assert {e["type"] for e in client.get("/api/backtests/exits").json()} >= {"stop_atr", "rule_exit"}
    bad = client.post("/api/backtests", json={"config": _cfg(exits=[{"type": "zzz"}])})
    assert bad.status_code == 400
    made = client.post("/api/backtests", json={"name": "t", "config": _cfg()}).json()
    assert client.get("/api/backtests").json()[0]["status"] == "queued"
    assert runner.run_one("interactive") == made["run_id"]
    got = client.get(f"/api/backtests/{made['id']}").json()
    assert got["status"] == "done" and got["trades"] and got["equity"] and got["kind"] == "explore"
    assert metrics.SURVIVORSHIP in got["warnings"]
    assert set(got["metrics"]) >= {"all", "is", "oos", "oos_start"}
    assert client.get("/api/backtests").json()[0]["metrics"]["is"].keys() == {"cagr", "excess"}
    assert client.delete(f"/api/backtests/{made['id']}").status_code == 200
    assert client.get(f"/api/backtests/{made['id']}").status_code == 404


def test_oos_start_resolved_from_setting_and_stored(world, client):
    client.put("/api/settings", json={"holdout_start": DAYS[200]})
    cfg = _cfg()
    del cfg["oos_start"]
    bid, got = _run(client, cfg)
    assert got["config"]["oos_start"] == DAYS[200]
    client.put("/api/settings", json={"holdout_start": DAYS[100]})
    assert client.get(f"/api/backtests/{bid}").json()["config"]["oos_start"] == DAYS[200]
    assert client.put("/api/settings", json={"holdout_start": "soon"}).status_code == 400


def test_period_validation(world, client):
    r = client.post("/api/backtests", json={"config": _cfg(start=DAYS[200])})
    assert r.status_code == 400 and "training period" in r.json()["detail"]
    assert client.post("/api/backtests", json={"config": _cfg(end=DAYS[200])}).status_code == 400
    assert client.post("/api/backtests", json={"config": _cfg(end=DAYS[250])}).status_code == 200


def test_explore_never_simulates_test_period(world, client):
    _, got = _run(client, _cfg())
    assert got["equity"][-1]["t"] < DAYS[200]
    assert all(t["exit_date"] < DAYS[200] for t in got["trades"])
    assert got["metrics"]["oos"] is None and got["metrics"]["all"] is None and got["metrics"]["is"]
    assert metrics.OVERFIT not in got["warnings"]


def test_final_creation_rules_and_attempts(world, client):
    pid, _ = _run(client, _cfg(), name="strat")
    fid, fin = _final(client, pid)
    assert fin["kind"] == "final" and fin["parent_id"] == pid and fin["name"] == "strat (final)"
    assert fin["equity"][-1]["t"] >= DAYS[200] and fin["attempt"] == 1
    assert set(fin["metrics"]) >= {"all", "is", "oos"} and fin["metrics"]["oos"]["trades"] is not None
    assert "looked at" not in _joined(fin)
    assert client.post(f"/api/backtests/{fid}/final").status_code == 400  # a final
    assert client.post("/api/backtests/9999/final").status_code == 404
    queued = client.post("/api/backtests", json={"config": _cfg()}).json()["id"]
    r = client.post(f"/api/backtests/{queued}/final")  # not finished yet
    assert r.status_code == 400 and "finished training-period" in r.json()["detail"]
    with db.tx() as c:
        c.execute("UPDATE backtests SET kind='legacy' WHERE id=?", (queued,))
    assert client.post(f"/api/backtests/{queued}/final").status_code == 400  # legacy
    runner.run_one("interactive")
    # same strategy again: attempt 2 with both warnings; the first final keeps its number
    _, fin2 = _final(client, pid)
    assert fin2["attempt"] == 2
    assert "looked at 1 time(s) before" in _joined(fin2)
    assert f"already had a final test (#{fid})" in _joined(fin2)
    assert client.get(f"/api/backtests/{fid}").json()["attempt"] == 1
    # a different strategy on the same test window: attempt 3, no same-strategy warning
    p3, _ = _run(client, _cfg(exits=[{"type": "time_stop", "params": {"days": 5}}]))
    _, fin3 = _final(client, p3)
    assert fin3["attempt"] == 3 and "already had a final test" not in _joined(fin3)
    client.delete(f"/api/backtests/{pid}")  # deleting the parent keeps its finals
    assert client.get(f"/api/backtests/{fid}").json()["parent_id"] == pid


def test_attempt_ignores_legacy_and_non_overlapping_windows(world, client):
    with db.tx() as c:
        c.execute("INSERT INTO backtests(config,status,kind,created_at) VALUES (?, 'done','legacy','x')",
                  (json.dumps(_cfg()),))  # fmt: skip
    pid, _ = _run(client, _cfg())
    assert _final(client, pid)[1]["attempt"] == 1
    p2, _ = _run(client, _cfg(oos_start=DAYS[50], end=DAYS[100]))  # test window ends before the first starts
    assert _final(client, p2)[1]["attempt"] == 1


def test_fingerprint_ignores_dates_only():
    a = _cfg()
    b = _cfg(start="2015-01-01", oos_start="2020-01-01", end="2024-01-01")
    assert metrics.fingerprint(a) == metrics.fingerprint(b)
    c = _cfg(exits=[{"type": "time_stop", "params": {"days": 11}}])
    assert metrics.fingerprint(a) != metrics.fingerprint(c)


def test_explore_runs_counts_overlapping_explores_up_to_this_one(world, client):
    def make(**kw):
        return client.post("/api/backtests", json={"config": _cfg(**kw)}).json()["id"]

    a, b = make(), make()
    late = make(start=DAYS[150], oos_start=DAYS[190])  # window 150..189 overlaps a and b (0..199)
    early = make(start=DAYS[0], oos_start=DAYS[100])  # window 0..99 overlaps a and b, not late
    count = lambda i: client.get(f"/api/backtests/{i}").json()["explore_runs"]  # noqa: E731
    assert [count(a), count(b)] == [1, 2]
    assert count(late) == 3 and count(early) == 3  # early skips `late`; a later row never counts


def test_screen_backtest(world, client):
    with db.tx() as c:
        sid = c.execute("SELECT id FROM screens LIMIT 1").fetchone()["id"]
    r = client.post(f"/api/screens/{sid}/backtest", json={})
    assert r.status_code == 200
    assert client.post("/api/screens/9999/backtest").status_code == 404


def test_churn_warning_for_very_short_trades():
    base = {"equity": curve([100, 101, 102]), "warnings": []}
    res = {**base, "trades": [trade(1)] * 40, "metrics": {"all": {"trades": 40, "avg_days": 2.0}}}
    assert metrics.CHURN in metrics.warnings_for(res)
    res = {**base, "trades": [trade(1)] * 40, "metrics": {"all": {"trades": 40, "avg_days": 12.0}}}
    assert metrics.CHURN not in metrics.warnings_for(res)
    res = {**base, "trades": [trade(1)] * 5, "metrics": {"all": {"trades": 5, "avg_days": 2.0}}}
    assert metrics.CHURN not in metrics.warnings_for(res)  # too few trades to judge
