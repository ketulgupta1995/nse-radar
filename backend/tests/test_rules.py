import numpy as np
import pandas as pd
import pytest

from app.analytics import rules
from app.analytics.rules import OPS, OpDef, RuleError, describe, evaluate, evaluate_latest, validate_rule


def I(name, **params):  # noqa: E743
    return {"ind": name, "params": params}


def cond(left, op, right):
    return {"left": left, "op": op, "right": right}


def V(x):
    return {"value": x}


def F(name):
    return {"fund": name}


PRESETS = {
    "Uptrend leaders": {"all": [
        cond(I("close"), ">", I("sma", n=50)), cond(I("sma", n=50), ">", I("sma", n=200)),
        cond(I("rel_strength", n=126), ">", V(10)), cond(I("pct_from_high", n=252), ">", V(-15))]},
    "Breakout on volume": {"all": [
        cond(I("close"), "crosses_above", I("highest", n=63)),
        cond(I("volume_ratio", n=20), ">=", V(2)), cond(I("close"), ">", I("sma", n=200))]},
    "Quality in uptrend": {"all": [
        cond(F("roce_pct"), ">=", V(15)), cond(F("debt_to_equity"), "<=", V(0.5)),
        cond(F("profit_growth_3y_pct"), ">=", V(10)), cond(I("close"), ">", I("sma", n=200)),
        cond(I("rel_strength", n=63), ">", V(0))]},
    "Pullback in strong trend": {"all": [
        cond(I("close"), ">", I("sma", n=200)), cond(I("sma_slope", n=50, k=20), ">", V(0)),
        cond(I("rsi", n=14), "<", V(45)), cond(I("pct_from_high", n=252), ">", V(-20))]},
    "Tight base near highs": {"all": [
        cond(I("range_pct", n=40), "<", V(15)), cond(I("pct_from_high", n=252), ">", V(-10)),
        cond(I("volume_ratio", n=20), "<", V(1))]},
}


@pytest.fixture
def frame():
    idx = pd.bdate_range("2026-01-01", periods=30)
    close = pd.Series(np.arange(100.0, 130.0), index=idx)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0}, index=idx
    )


@pytest.mark.parametrize("name", PRESETS)
def test_presets_validate(name):
    validate_rule(PRESETS[name])


def deep(n):
    node = cond(V(1), ">", V(0))
    for _ in range(n):
        node = {"all": [node]}
    return node


@pytest.mark.parametrize(
    "rule,fragment",
    [
        ({"all": [cond(I("smaa"), ">", V(1))]}, "all[0].left.ind"),
        ({"all": [cond(I("sma", n=1), ">", V(1))]}, "all[0].left.params"),
        ({"all": [cond(V(1), ">", F("nope"))]}, "all[0].right.fund"),
        ({"all": [cond(V(1), ">", F("sector"))]}, "all[0].right.fund"),
        ({"all": [cond(I("close", ), ">", {"ind": "close", "offset": -1})]}, "all[0].right.offset"),
        ({"all": [cond(I("close"), ">", {"ind": "close", "times": 0})]}, "all[0].right.times"),
        ({"all": [cond(I("close"), ">", {"ind": "close", "times": -2})]}, "all[0].right.times"),
        (deep(5), "deeply"),
        ({"all": []}, "all: group is empty"),
        ({"all": [{"any": []}]}, "all[0].any"),
        ({"all": [cond(V(1), ">", V(0))] * 21}, "too many"),
        ({"all": [cond(V(1), "~", V(0))]}, "all[0].op"),
    ],
)
def test_validation_errors_have_paths(rule, fragment):
    with pytest.raises(RuleError) as e:
        validate_rule(rule)
    assert fragment in str(e.value)


def test_depth_limit_boundary():
    validate_rule(deep(4))  # 4 nested groups is allowed
    with pytest.raises(RuleError, match="deeply"):
        validate_rule(deep(5))


def test_crosses_above_triggers_once():
    idx = pd.bdate_range("2026-01-01", periods=8)
    close = pd.Series([5, 5, 5, 10, 11, 12, 11, 10.0], index=idx)
    f = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0})
    r = {"all": [cond(I("close"), "crosses_above", V(8))]}
    out = evaluate(r, f)
    assert out.sum() == 1 and out.iloc[3]
    below = evaluate({"all": [cond(I("close"), "crosses_below", V(11))]}, f)
    assert below.sum() == 1 and below.iloc[7]


def test_offset_and_times(frame):
    r = {"all": [cond(I("close"), ">", {"ind": "close", "offset": 5, "times": 1.0})]}
    assert evaluate(r, frame).iloc[5:].all() and not evaluate(r, frame).iloc[:5].any()
    r2 = {"all": [cond(I("close"), ">", {"ind": "close", "times": 2})]}
    assert not evaluate(r2, frame).any()


def test_missing_fund_is_false_and_reported(frame):
    r = {"all": [cond(F("roce_pct"), ">=", V(15))]}
    ok, details = evaluate_latest(r, frame, None, {})
    assert ok is False and "missing: roce_pct" in details
    ok, details = evaluate_latest(r, frame, None, {"roce_pct": 20.0})
    assert ok is True and details["ROCE %"] == 20.0
    assert rules.uses_fundamentals(r) and not rules.uses_fundamentals(PRESETS["Uptrend leaders"])


def test_not_does_not_flip_missing(frame):
    r = {"not": cond(F("roce_pct"), ">=", V(15))}
    assert not evaluate(r, frame, None, {}).any()
    assert evaluate(r, frame, None, {"roce_pct": 5.0}).all()


def test_any_and_not(frame):
    r = {"any": [cond(V(1), ">", V(2)), {"not": cond(V(1), ">", V(2))}]}
    assert evaluate(r, frame).all()


def test_indicator_cached_once(frame, monkeypatch):
    calls = []
    real = rules.indicators.compute
    monkeypatch.setattr(rules.indicators, "compute", lambda *a, **k: calls.append(a[0]) or real(*a, **k))
    r = {"all": [cond(I("sma", n=5), ">", V(1)), cond(I("sma", n=5), ">", V(2)),
                 cond(I("sma", n=6), ">", V(2))]}
    evaluate(r, frame)
    assert calls == ["sma", "sma"]


def test_describe_snapshots():
    r1 = {"all": [
        cond(I("close"), ">", I("sma", n=200)),
        {"any": [cond(I("rsi", n=14), "<", V(45)),
                 cond({"ind": "volume", "times": 2}, ">", I("volume_ratio", n=20))]},
    ]}
    assert describe(validate_rule(r1)) == (
        "Close is above the 200-day average AND "
        "(RSI (14) is below 45 OR Volume ×2 is above Volume ratio (20))"
    )
    r2 = {"not": cond(F("roce_pct"), ">=", V(15))}
    assert describe(validate_rule(r2)) == "NOT (ROCE % is at least 15)"
    r3 = {"all": [cond(I("close"), "crosses_above", I("highest", n=63)),
                  cond(I("rsi", n=14), "<=", V(70))]}
    assert describe(validate_rule(r3)) == "Close crosses above Highest high (63) AND RSI (14) is at most 70"


def test_new_op_needs_no_other_change(frame, monkeypatch):
    monkeypatch.setitem(OPS, "!=", OpDef("!=", "differs from", lambda a, b: a != b))
    r = {"all": [cond(I("close"), "!=", V(100))]}
    assert evaluate(r, frame).iloc[1:].all()
    assert describe(validate_rule(r)) == "Close differs from 100"


def test_rules_api():
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    assert {o["name"] for o in c.get("/api/rules/ops").json()} >= {">", "crosses_above"}
    ok = c.post("/api/rules/describe", json={"all": [cond(I("close"), ">", V(1))]})
    assert ok.json()["text"] == "Close is above 1"
    bad = c.post("/api/rules/describe", json={"all": []})
    assert bad.status_code == 400 and "all" in bad.json()["detail"]


def test_series_fund_value_is_per_date(frame):
    r = {"all": [cond(F("profit_growth_yoy_pct"), ">", V(10))]}
    s = pd.Series(np.where(np.arange(len(frame)) < 5, np.nan, 20.0), index=frame.index)
    res = evaluate(r, frame, None, {"profit_growth_yoy_pct": s})
    assert not res.iloc[:5].any() and res.iloc[5:].all()
    ok, details = evaluate_latest(r, frame, None, {"profit_growth_yoy_pct": s * np.nan})
    assert ok is False and "missing: profit_growth_yoy_pct" in details


def test_fund_fields_of_nested_rule():
    r = {"all": [
        cond(F("roce_pct"), ">", V(1)), {"not": cond(F("pe"), ">", F("pb"))}, cond(I("close"), ">", V(1))]}
    assert rules.fund_fields(r) == {"roce_pct", "pe", "pb"}
    assert rules.fund_fields(PRESETS["Uptrend leaders"]) == set()


def ranked(name="close", **params):
    return {**I(name, **params), "rank": True}


def test_rank_validation_and_round_trip():
    r = validate_rule({"all": [cond(ranked("rel_strength", n=126), ">=", V(90))]})
    o = r.items[0].left
    assert o.rank and o.as_dict() == {"ind": "rel_strength", "params": {"n": 126}, "rank": True}
    plain = validate_rule({"all": [cond(I("close"), ">", V(1))]}).items[0].left
    assert "rank" not in plain.as_dict()
    with pytest.raises(RuleError, match=r"rule\.all\[0\]\.left\.rank: only allowed on 'ind' operands"):
        validate_rule({"all": [cond({**F("roce_pct"), "rank": True}, ">", V(1))]})
    with pytest.raises(RuleError, match=r"\.rank"):
        validate_rule({"all": [cond({**I("close"), "rank": 1}, ">", V(1))]})


def test_cross_rank():
    cols = {f"S{i}": [float(i), float(i)] for i in range(25)}
    df = pd.DataFrame(cols, index=pd.bdate_range("2026-01-01", periods=2))
    df.loc[df.index[1], "S3"] = np.nan
    out = rules.cross_rank(df)
    assert out["S24"].iloc[0] == 100 and out["S0"].iloc[0] == 4
    assert np.isnan(out["S3"].iloc[1]) and out["S24"].iloc[1] == 100
    assert rules.cross_rank(df.iloc[:, :19]).isna().all().all()


def test_evaluate_with_and_without_ranks(frame):
    rule = {"all": [cond(ranked("close"), ">=", V(80))]}
    key = rules.rank_key(rules.rank_operands(rule)[0])
    ok_s = pd.Series(90.0, index=frame.index)
    assert evaluate(rule, frame, ranks={key: ok_s}).all()
    assert not evaluate(rule, frame).any()
    ok, vals = evaluate_latest(rule, frame)
    assert not ok and "rank: Close, rank" in vals
    assert evaluate_latest(rule, frame, ranks={key: ok_s})[0]
    assert describe(rule) == "Close, rank is at least 80"
