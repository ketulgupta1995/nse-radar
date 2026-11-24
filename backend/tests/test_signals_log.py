import json
from datetime import date

import pandas as pd
import pytest

from app import db, timeutil
from app.analytics import frames
from app.signals import log as siglog
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec, IndexBar
from app.sources.store import save_bars, save_index

DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=300)]
SYMS = [f"S{i:02d}" for i in range(12)]


@pytest.fixture
def world(client, monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    monkeypatch.setattr(siglog, "_app_version", lambda: "abc123")
    registry.clear()
    caps = (CapabilitySpec("bars", "by_symbol", (), adjusted=True), CapabilitySpec("index", "whole", ()))
    registry.register(type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d",
                                                 "homepage": "h", "capabilities": caps})())  # fmt: skip
    with db.tx() as c:
        for sym in SYMS:
            c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES (?,?,1)", (sym, sym))
            save_bars("px", [Bar(sym, d, p := 100 + i * 0.5, p + 1, p - 1, p, 1000.0)
                             for i, d in enumerate(DAYS)], c)  # fmt: skip
        save_index("px", [IndexBar(frames.INDEX_NAME, d, 1000.0) for d in DAYS], c)
        sid = c.execute("SELECT id FROM screens LIMIT 1").fetchone()["id"]
        c.execute("DELETE FROM screen_results")
    frames.invalidate()
    yield sid
    registry.clear()
    frames.invalidate()


def add_result(sid, sym, first_seen):
    with db.tx() as c:
        c.execute("INSERT INTO screen_results(screen_id, symbol, as_of, values_json, first_seen) "
                  "VALUES (?,?,?,?,?)", (sid, sym, DAYS[-1], "{}", first_seen))  # fmt: skip


def ranked(syms):
    return [{"symbol": s, "score": 90.0 - i, "components": {"rs": 50.0}, "reasons": [f"r{i}"]}
            for i, s in enumerate(syms)]  # fmt: skip


def rows(where="1=1"):
    with db.tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM signals WHERE " + where + " ORDER BY id")]


def test_new_screen_member_logged_once(world):
    add_result(world, "S00", "2026-11-09")
    add_result(world, "S01", "2026-11-02")  # older: not logged
    assert siglog.log_signals([]) == {"as_of": DAYS[-1], "screen": 1, "shortlist": 0}
    assert siglog.log_signals([])["screen"] == 0
    got = rows()
    assert [r["symbol"] for r in got] == ["S00"] and got[0]["app_version"] == "abc123"
    assert got[0]["rule_hash"] and got[0]["as_of"] == DAYS[-1] and got[0]["bars_as_of"] == DAYS[-1]


def test_shortlist_first_run_stores_then_logs_new_entry(world):
    for s in SYMS:
        add_result(world, s, "2026-11-02")
    assert siglog.log_signals(ranked(SYMS[:10]))["shortlist"] == 0
    assert db.get_setting("signal_last_top10") == SYMS[:10]
    second = ranked(["S10"] + SYMS[:9])  # S10 enters at rank 1, S09 drops out
    assert siglog.log_signals(second)["shortlist"] == 1
    got = rows("source='shortlist'")
    assert len(got) == 1 and got[0]["symbol"] == "S10" and got[0]["rank"] == 1
    assert got[0]["screen_id"] == 0 and got[0]["screen_name"] is None and got[0]["rule_hash"] is None


def test_levels_exit_config_and_days(world):
    add_result(world, "S00", "2026-11-09")
    siglog.log_signals([])
    r = rows()[0]
    k_stop, k_tgt = db.get_setting("atr_stop_multiple"), db.get_setting("signal_target_atr_multiple")
    assert r["planned_stop"] == pytest.approx(r["planned_entry"] - k_stop * r["atr14"])
    assert r["planned_target"] == pytest.approx(r["planned_entry"] + k_tgt * r["atr14"])
    weeks = db.get_setting("default_time_stop_weeks")
    assert json.loads(r["exit_config"]) == {
        "exits": [{"type": "stop_atr", "params": {"k": k_stop}},
                  {"type": "target_atr", "params": {"k": k_tgt}},
                  {"type": "time_stop", "params": {"days": weeks * 5}}],
        "notional_inr": 100000}  # fmt: skip
    with db.tx() as c:
        days = [dict(d) for d in c.execute("SELECT * FROM signal_days")]
    assert len(days) == 1 and days[0]["as_of"] == DAYS[-1] and days[0]["logged"] == 1


def test_score_carried_only_when_in_shortlist(world):
    add_result(world, "S00", "2026-11-09")
    add_result(world, "S01", "2026-11-09")
    siglog.log_signals(ranked(["S00"]))
    by = {r["symbol"]: r for r in rows()}
    assert by["S00"]["score"] == 90.0 and json.loads(by["S00"]["components"]) == {"rs": 50.0}
    assert json.loads(by["S00"]["reasons"]) == ["r0"]
    assert by["S01"]["score"] is None and by["S01"]["components"] is None and by["S01"]["reasons"] == "[]"


def test_row_survives_screen_deletion(world):
    add_result(world, "S00", "2026-11-09")
    siglog.log_signals([])
    with db.tx() as c:
        c.execute("DELETE FROM screen_results")
        c.execute("DELETE FROM screens WHERE id=?", (world,))
    got = rows()
    assert len(got) == 1 and got[0]["screen_name"] and got[0]["screen_id"] == world
