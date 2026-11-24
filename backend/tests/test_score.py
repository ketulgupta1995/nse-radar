import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app import db, timeutil
from app.analytics import frames, score
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec, IndexBar
from app.sources.store import save_bars, save_index

W = {"rs": 30, "trend": 25, "fundamentals": 30, "backtest": 15}


def frame(rows: dict[str, dict]) -> pd.DataFrame:
    base = {"close": 100, "sma50": 90, "sma200": 80, "sma_slope": 5, "pct_from_high": -7,
            "rs63": 5, "rs126": 5,
            "roce_pct": 20, "debt_to_equity": 0.3, "profit_growth_3y_pct": 15, "profit_growth_yoy_pct": 10,
            "best_screen_oos_excess": np.nan, "screens": ["S"], "name": "n"}  # fmt: skip
    df = pd.DataFrame([{**base, **r, "symbol": s} for s, r in rows.items()])
    return df.set_index("symbol", drop=False)


def test_ordering_with_crafted_columns():
    df = frame(
        {
            "STRONG": {"rs63": 30, "rs126": 40},
            "MID": {"rs63": 10, "rs126": 10},
            "WEAK": {"rs63": -5, "rs126": -5},
        }
    )
    ranked = score.score_frame(df, W)
    assert [r["symbol"] for r in ranked] == ["STRONG", "MID", "WEAK"]
    assert ranked[0]["components"]["rs"] > ranked[2]["components"]["rs"]


def test_weights_change_the_order():
    # A: great momentum, poor business; B: the opposite
    df = frame({"A": {"rs63": 40, "rs126": 40, "roce_pct": 1, "debt_to_equity": 2, "profit_growth_3y_pct": -5,
                      "profit_growth_yoy_pct": -5},
                "B": {"rs63": 1, "rs126": 1}})  # fmt: skip
    assert score.score_frame(df, {"rs": 100})[0]["symbol"] == "A"
    assert score.score_frame(df, {"fundamentals": 100})[0]["symbol"] == "B"


def test_zero_weight_component_is_ignored():
    df = frame({"A": {}, "B": {"rs63": 50}})
    r = score.score_frame(df, {"rs": 50, "trend": 0, "fundamentals": 0})[0]
    assert set(r["components"]) == {"rs"}
    assert not any("200-day" in t for t in r["reasons"])


def test_missing_fundamentals_is_50_with_reason():
    nan = float("nan")
    gone = {k: nan for k in score.FUND_FIELDS}
    df = frame({"A": gone,
                "B": {}})  # fmt: skip
    ranked = {r["symbol"]: r for r in score.score_frame(df, {"fundamentals": 1})}
    assert ranked["A"]["components"]["fundamentals"] == 50.0
    assert "fundamentals missing" in ranked["A"]["reasons"]
    assert "fundamentals missing" not in ranked["B"]["reasons"]


def test_unbacktested_screen_is_50_with_reason():
    r = score.score_frame(frame({"A": {}}), {"backtest": 1})[0]
    assert r["components"]["backtest"] == 50.0 and "screen not backtested" in r["reasons"]
    df = frame({"A": {"best_screen_oos_excess": 6.0}, "B": {"best_screen_oos_excess": 1.0}})
    top = score.score_frame(df, {"backtest": 1})[0]
    assert top["symbol"] == "A" and "Its screen beat the index by 6%/yr out-of-sample" in top["reasons"]


def test_reasons_keep_top_four():
    r = score.score_frame(frame({"A": {"rs63": 30, "rs126": 30}}), W)[0]
    assert len(r["reasons"]) == 4


def test_extra_component_changes_total(monkeypatch):
    df = frame({"A": {}, "B": {}})
    before = score.score_frame(df, {"rs": 1})[0]["score"]
    extra = score.ScoreComponent(
        "flat", "Flat", "x", lambda d: pd.Series(100.0, index=d.index), lambda r: [(1.0, "x")]
    )
    monkeypatch.setitem(score.COMPONENTS, "flat", extra)
    after = score.score_frame(df, {"rs": 1, "flat": 1})[0]["score"]
    assert after == pytest.approx((before + 100) / 2)


def test_backtest_matches_screen_by_rule_equality(client):
    r1 = {"all": [{"left": {"ind": "close"}, "op": ">", "right": {"value": 1}}]}
    r2 = {"all": [{"left": {"ind": "close"}, "op": ">", "right": {"value": 2}}]}
    reordered = {
        "all": [{"right": {"value": 1}, "op": ">", "left": {"ind": "close"}}]
    }  # same rule, key order
    with db.tx() as c:
        ids = []
        for n, r in (("one", r1), ("two", r2)):
            ids.append(c.execute(
                "INSERT INTO screens(name, rule, is_preset, created_by, created_at, updated_at) "
                "VALUES (?,?,0,'user','x','x')", (n, json.dumps(r))).lastrowid)  # fmt: skip

        def bt(rule, excess, status="done", kind="legacy"):
            oos = {"excess": excess} if excess is not None else None
            c.execute("INSERT INTO backtests(config, status, metrics, kind, created_at) VALUES (?,?,?,?,'x')",
                      (json.dumps({"entry_rule": rule}), status, json.dumps({"oos": oos}), kind),
            )  # fmt: skip

        bt(r1, 3.0)
        bt(reordered, 7.0, kind="final")  # newer backtest of the same rule wins
        bt(r2, 99.0, status="failed")  # ignored
        bt(r1, None, kind="explore")  # newer explore rows must not erase the older result
        bt(r1, 55.0, kind="explore")
        got = score._screen_excess(c)
    assert got == {ids[0]: 7.0}


# ---- API -----------------------------------------------------------------------------------

DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=300)]


@pytest.fixture
def world(client, monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    registry.clear()
    caps = (CapabilitySpec("bars", "by_symbol", (), adjusted=True), CapabilitySpec("index", "whole", ()))
    registry.register(type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d",
                                                 "homepage": "h", "capabilities": caps})())  # fmt: skip
    with db.tx() as c:
        for sym, slope in (("UP", 0.5), ("FLAT", 0.0)):
            c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES (?,?,1)", (sym, sym.title()))
            save_bars("px", [Bar(sym, d, p := 100 + i * slope, p + 1, p - 1, p, 1000.0)
                             for i, d in enumerate(DAYS)], c)  # fmt: skip
        save_index("px", [IndexBar(frames.INDEX_NAME, d, 1000.0) for d in DAYS], c)
        sid = c.execute("SELECT id FROM screens LIMIT 1").fetchone()["id"]
        for sym in ("UP", "FLAT"):
            c.execute("INSERT INTO screen_results(screen_id, symbol, as_of, values_json, first_seen) "
                      "VALUES (?,?,?,?,?)", (sid, sym, DAYS[-1], "{}", DAYS[-1]))  # fmt: skip
    frames.invalidate()
    yield sid
    registry.clear()
    frames.invalidate()


def test_shortlist_and_results_api(world, client):
    short = client.get("/api/shortlist?limit=1").json()
    assert len(short) == 1 and short[0]["symbol"] == "UP"
    assert set(short[0]) >= {"symbol", "name", "score", "components", "reasons", "screens", "last_close"}
    res = client.get(f"/api/screens/{world}/results").json()
    by = {r["symbol"]: r for r in res}
    assert by["UP"]["score"] > by["FLAT"]["score"] and by["UP"]["reasons"]
    comps = client.get("/api/score/components").json()
    assert [c["name"] for c in comps] == ["rs", "trend", "fundamentals", "backtest"]
    assert comps[0]["weight"] == 30
