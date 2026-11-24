import json
from datetime import datetime

import pytest

from app import config, db, timeutil
from app.analytics import fundamentals as fnd
from app.jobs import runner
from app.sources import registry
from app.sources.base import BaseSource, CapabilitySpec, FundSnapshot, Quarter
from app.sources.store import save_fundamentals, save_quarters


def make(name, *caps):
    specs = tuple(CapabilitySpec(c, "by_symbol", ()) for c in caps)
    return type(
        name, (BaseSource,),
        {"name": name, "label": name, "description": "d", "homepage": "h", "capabilities": specs},
    )()  # fmt: skip


def quarters(symbol, profits, revenues=None, consolidated=True, start="2024-03-31"):
    out = []
    y, m = int(start[:4]), int(start[5:7])
    for i, p in enumerate(profits):
        mm = (m - 1 + 3 * i) % 12 + 1
        yy = y + (m - 1 + 3 * i) // 12
        day = {3: 31, 6: 30, 9: 30, 12: 31}[mm]
        rev = revenues[i] if revenues else 100.0 + i
        out.append(Quarter(symbol, f"{yy}-{mm:02d}-{day}", consolidated, revenue=rev, net_profit=p))
    return out


@pytest.fixture
def world(client, monkeypatch):
    # the sample quarters end 2025-03-31; "today" is shortly after, so they count as fresh
    monkeypatch.setattr(timeutil, "now", lambda: datetime(2025, 5, 15, 12, tzinfo=config.TZ))
    registry.clear()
    for s in (make("fa", "fundamentals"), make("fb", "fundamentals"), make("qa", "quarters")):
        registry.register(s)
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','Alpha',1)")
        db.set_setting("source_priority", {"fundamentals": ["fa", "fb"], "quarters": ["qa"]}, c)
        db.set_setting("fundamentals_field_priority", {}, c)
        save_fundamentals("fa", FundSnapshot("AAA", {"pe": 10.0, "roce_pct": None, "sector": "Tech"}), c)
        save_fundamentals("fb", FundSnapshot("AAA", {"pe": 99.0, "roce_pct": 22.0, "pb": 3.0}), c)
        save_quarters("qa", quarters("AAA", [10, 12, 14, 16, 20], [100, 110, 120, 130, 150]), c)
    yield
    registry.clear()


def merged():
    with db.tx() as c:
        return fnd.merge("AAA", c)


def test_priority_order_wins_and_null_falls_back(world):
    data, src = merged()
    assert data["pe"] == 10.0 and src["pe"] == "fa"  # fa first
    assert data["roce_pct"] == 22.0 and src["roce_pct"] == "fb"  # fa's value is null
    assert data["pb"] == 3.0 and src["sector"] == "fa"


def test_priority_setting_reorders(world):
    with db.tx() as c:
        db.set_setting("source_priority", {"fundamentals": ["fb", "fa"], "quarters": ["qa"]}, c)
    data, src = merged()
    assert data["pe"] == 99.0 and src["pe"] == "fb"


def test_per_field_override_puts_quarters_first(world):
    with db.tx() as c:
        c.execute("DELETE FROM fund_snapshots WHERE source='fb'")
        save_fundamentals("fa", FundSnapshot("AAA", {"profit_growth_yoy_pct": 1.0, "pe": 10.0}), c)
        db.set_setting("fundamentals_field_priority", {"profit_growth_yoy_pct": ["quarters", "fa"]}, c)
    data, src = merged()
    assert src["profit_growth_yoy_pct"] == "quarters:qa" and data["profit_growth_yoy_pct"] == 100.0
    assert src["pe"] == "fa"


def test_override_falls_through_when_quarters_has_nothing(world):
    with db.tx() as c:
        c.execute("DELETE FROM quarters")
        save_fundamentals("fa", FundSnapshot("AAA", {"profit_growth_yoy_pct": 7.0}), c)
        db.set_setting("fundamentals_field_priority", {"profit_growth_yoy_pct": ["quarters", "fa"]}, c)
    data, src = merged()
    assert data["profit_growth_yoy_pct"] == 7.0 and src["profit_growth_yoy_pct"] == "fa"


def test_yoy_from_quarters(world):
    with db.tx() as c:
        d = fnd.from_quarters("AAA", c)
    # latest 2025-03-31 vs 2024-03-31: sales 150/100, profit 20/10
    assert d == {"sales_growth_yoy_pct": 50.0, "profit_growth_yoy_pct": 100.0, "profit_positive_4q": 1.0}


def test_profit_positive_false_with_a_loss_and_no_growth_on_loss_base(world):
    with db.tx() as c:
        c.execute("DELETE FROM quarters")
        save_quarters("qa", quarters("AAA", [-5, 12, 14, -1, 20]), c)
        d = fnd.from_quarters("AAA", c)
    assert d["profit_positive_4q"] == 0.0 and "profit_growth_yoy_pct" not in d  # base profit was negative


def test_too_few_or_failed_quarters_ignored(world):
    with db.tx() as c:
        c.execute("DELETE FROM quarters")
        save_quarters("qa", quarters("AAA", [1, 2, 3, 4]), c)  # only 4
        assert fnd.from_quarters("AAA", c) == {}
        rows = quarters("AAA", [1, 2, 3, 4, 5])
        bad = Quarter("AAA", rows[-1].period_end, True, parse_error="x")
        save_quarters("qa", [*rows[:-1], bad], c)
        assert fnd.from_quarters("AAA", c) == {}  # the 5th failed to parse


def test_consolidated_preferred_standalone_fallback(world):
    with db.tx() as c:
        c.execute("DELETE FROM quarters")
        save_quarters("qa", quarters("AAA", [1, 2, 3, 4, 5], consolidated=False), c)
        save_quarters("qa", quarters("AAA", [10, 20], consolidated=True), c)  # too few consolidated
        assert fnd.from_quarters("AAA", c)["profit_growth_yoy_pct"] == 400.0


def test_job_and_api_shape(world, client):
    with db.tx() as c:
        db.set_setting("fundamentals_field_priority", {"sales_growth_yoy_pct": ["quarters", "fa"]}, c)
    rid = runner.enqueue("fundamentals_merge")
    assert runner.run_one() == rid
    with db.tx() as c:
        run = dict(c.execute("SELECT * FROM job_runs WHERE id=?", (rid,)).fetchone())
    assert run["status"] == "done" and run["ok"] == 1

    r = client.get("/api/fundamentals/aaa").json()
    assert set(r) == {"data", "sources", "updated_at", "quarters", "snapshots"}
    assert r["data"]["pe"] == 10.0 and r["sources"]["roce_pct"] == "fb"
    assert r["sources"]["sales_growth_yoy_pct"] == "quarters:qa"
    assert r["updated_at"] and len(r["quarters"]) == 5 and r["quarters"][0]["period_end"] == "2025-03-31"
    assert set(r["snapshots"]) == {"fa", "fb"} and "fetched_at" in r["snapshots"]["fa"]
    assert client.get("/api/fundamentals/ZZZ").status_code == 404
    fields = client.get("/api/fundamentals/fields").json()
    assert fields == fnd.FIELDS and json.dumps(fields)


def test_job_stage_and_followup():
    from app.jobs import registry as jobs

    assert jobs.get("fundamentals_merge").followups == ("screens_run",)
    assert jobs.get("fundamentals_merge").stage == 6


def test_stale_quarters_give_way_to_snapshots(world, monkeypatch):
    with db.tx() as c:
        db.set_setting("fundamentals_field_priority", {"sales_growth_yoy_pct": ["quarters", "fb"]}, c)
        save_fundamentals("fb", FundSnapshot("AAA", {"sales_growth_yoy_pct": 7.0}), c)
    assert merged()[1]["sales_growth_yoy_pct"] == "quarters:qa"  # 45 days after the latest quarter
    monkeypatch.setattr(timeutil, "now", lambda: datetime(2026, 11, 10, 12, tzinfo=config.TZ))
    with db.tx() as c:
        assert fnd.from_quarters("AAA", c) == {}  # latest quarter is ~19 months old
    data, origin = merged()
    assert data["sales_growth_yoy_pct"] == 7.0 and origin["sales_growth_yoy_pct"] == "fb"


# ---- point-in-time quarter fields (T096) -------------------------------------------------------


def _pit_world(profits, filing_lag=40):
    from dataclasses import replace
    from datetime import date, timedelta

    qs = quarters("PIT", profits, [100.0 + 10 * i for i in range(len(profits))], start="2023-03-31")
    if filing_lag is not None:
        lag = timedelta(days=filing_lag)
        qs = [replace(q, filing_date=(date.fromisoformat(q.period_end) + lag).isoformat()) for q in qs]
    with db.tx() as c:
        save_quarters("qa", qs, c)


def _pit(index):
    import pandas as pd

    with db.tx() as c:
        return fnd.pit_quarter_series("PIT", pd.DatetimeIndex(pd.to_datetime(index)), c)


def test_pit_values_nan_until_five_quarters_known(world):
    _pit_world([10, 12, 14, 16, 20, 22, 24, 26])
    # 5th quarter ends 2024-03-31, filed 2024-05-10: usable from 05-11
    s = _pit(["2024-05-10", "2024-05-11"])
    assert s["profit_positive_4q"].isna().iloc[0]
    assert s["profit_positive_4q"].iloc[1] == 1.0
    assert s["profit_growth_yoy_pct"].iloc[1] == 100.0


def test_pit_changes_day_after_filing(world):
    _pit_world([10, 12, 14, 16, 20, 30, 24, 26])
    # 6th quarter ends 2024-06-30, filed 2024-08-09 -> known 08-10
    s = _pit(["2024-08-09", "2024-08-10"])["profit_growth_yoy_pct"]
    assert s.iloc[0] == 100.0  # 20 vs 10
    assert s.iloc[1] == 150.0  # 30 vs 12


def test_pit_loss_quarter_drops_flag_then_recovers(world):
    _pit_world([10, 12, 14, 16, 20, -5, 24, 26, 28, 30])
    # loss is quarter 6 (ends 2024-06-30); it leaves the last 4 once quarter 10 is known (2025-08-09)
    flag = _pit(["2024-08-15", "2025-08-01", "2025-08-15"])["profit_positive_4q"]
    assert flag.iloc[0] == 0.0 and flag.iloc[1] == 0.0 and flag.iloc[2] == 1.0


def test_pit_stale_and_null_filing(world):
    _pit_world([10, 12, 14, 16, 20], filing_lag=None)
    # latest period_end 2024-03-31, known 2024-05-30 (period end + 60 days)
    f = _pit(["2024-05-29", "2024-05-30", "2024-10-16", "2024-10-18"])["profit_positive_4q"]
    assert f.isna().iloc[0] and f.iloc[1] == 1.0
    assert f.iloc[2] == 1.0  # 199 days old
    assert f.isna().iloc[3]  # 201 days old


def test_pit_no_quarters_all_nan(world):
    s = _pit(["2024-01-02"])
    assert set(s) == set(fnd.QUARTER_FIELDS) and all(v.isna().all() for v in s.values())


def test_known_on_dates_filing_plus_one_and_fallback(world):
    _pit_world([10, 12, 14, 16, 20])
    with db.tx() as c:
        d = fnd.known_on_dates("PIT", c)
    assert d == sorted(d) and len(d) == 5
    assert d[0].isoformat() == "2023-05-11"  # period end 2023-03-31, filed +40 days, known +1
    with db.tx() as c:
        c.execute("DELETE FROM quarters")
    _pit_world([10, 12, 14, 16, 20], filing_lag=None)
    with db.tx() as c:
        d = fnd.known_on_dates("PIT", c)
    assert d[0].isoformat() == "2023-05-30"  # period end + 60 days
