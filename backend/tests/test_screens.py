import json
from datetime import date

import pandas as pd
import pytest

from app import db, timeutil
from app.analytics import frames, rules, screens
from app.jobs import runner
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec, IndexBar
from app.sources.store import save_bars, save_index

DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=300)]


def source():
    caps = (CapabilitySpec("bars", "by_symbol", (), adjusted=True), CapabilitySpec("index", "whole", ()))
    return type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d", "homepage": "h",
                                      "capabilities": caps})()  # fmt: skip


def bars(symbol, closer):
    out = []
    for i, d in enumerate(DAYS):
        c = closer(i)
        out.append(Bar(symbol, d, c, c + 1, c - 1, c, 1000.0))
    return out


@pytest.fixture
def world(client, monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    registry.clear()
    registry.register(source())
    with db.tx() as c:
        for sym in ("UP", "DOWN", "FLAT"):
            c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES (?,?,1)", (sym, sym.title()))
        save_bars("px", bars("UP", lambda i: 100 + i * 0.5), c)
        save_bars("px", bars("DOWN", lambda i: 300 - i * 0.5), c)
        save_bars("px", bars("FLAT", lambda i: 100.0), c)
        save_index("px", [IndexBar(frames.INDEX_NAME, d, 1000.0) for d in DAYS], c)
        good = {"roce_pct": 20.0, "debt_to_equity": 0.2, "profit_growth_3y_pct": 15.0}
        for sym in ("UP", "DOWN", "FLAT"):
            c.execute(
                "INSERT INTO fundamentals(symbol, updated_at, data, sources) VALUES (?,?,?,?)",
                (sym, "2026-11-09T00:00:00+05:30", json.dumps(good), "{}"),
            )
    frames.invalidate()
    yield
    registry.clear()
    frames.invalidate()


def preset(name):
    with db.tx() as c:
        return dict(c.execute("SELECT * FROM screens WHERE name=?", (name,)).fetchone())


LEADERS_RULE = {"all": [
    {"left": {"ind": "close"}, "op": ">", "right": {"ind": "sma", "params": {"n": 50}}},
    {"left": {"ind": "sma", "params": {"n": 50}}, "op": ">", "right": {"ind": "sma", "params": {"n": 200}}},
    {"left": {"ind": "rel_strength", "params": {"n": 126}}, "op": ">", "right": {"value": 10}},
    {"left": {"ind": "pct_from_high", "params": {"n": 252}}, "op": ">", "right": {"value": -15}},
]}  # fmt: skip


def leaders():
    """A user screen with the retired "Uptrend leaders" rule; in the test world it picks only UP."""
    now = timeutil.now_iso()
    with db.tx() as c:
        c.execute("INSERT INTO screens(name, rule, created_at, updated_at) VALUES ('Leaders', ?, ?, ?)",
                  (json.dumps(LEADERS_RULE), now, now))  # fmt: skip
    return preset("Leaders")


def test_presets_seeded_and_valid(client):
    with db.tx() as c:
        rows = c.execute("SELECT * FROM screens WHERE is_preset=1").fetchall()
    assert len(rows) == 11 and {r["created_by"] for r in rows} == {"preset"}
    for r in rows:
        rules.validate_rule(json.loads(r["rule"]))


def test_phase13_presets_structure(client):
    sizes = {"52-week high breakout": 3, "Promoters buying, in uptrend": 3, "Breadth trend riders": 5,
             "Results winners": 4, "Leaders in leading industries": 4,
             "Short dip in uptrend": 3}
    for name, n in sizes.items():
        assert len(json.loads(preset(name)["rule"])["all"]) == n
    ind = json.loads(preset("Leaders in leading industries")["rule"])["all"][2]
    assert ind["left"]["rank"] is True and ind["right"] == {"value": 80}
    promo = json.loads(preset("Promoters buying, in uptrend")["rule"])["all"][0]
    assert promo["left"] == {"fund": "promoter_change_1y_pp"}


def test_retired_presets_removed_from_old_db(client):
    now = timeutil.now_iso()
    with db.tx() as c:
        c.execute("INSERT INTO screens(name, rule, is_preset, created_by, created_at, updated_at) "
                  "VALUES ('Trend riders', '{\"all\": []}', 1, 'preset', ?, ?)", (now, now))  # fmt: skip
        c.execute("INSERT INTO screens(name, rule, created_at, updated_at) "
                  "VALUES ('Uptrend leaders', '{\"all\": []}', ?, ?)", (now, now))  # a user screen: kept
    db.init_db()
    with db.tx() as c:
        names = {r[0]: r[1] for r in c.execute("SELECT name, is_preset FROM screens")}
    assert "Trend riders" not in names and names["Uptrend leaders"] == 0


def test_presets_seed_is_idempotent(client):
    db.init_db()
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM screens").fetchone()[0] == 11


def test_preset_selects_expected_symbol(world):
    s = leaders()
    found = screens.run_screen(s["id"])
    assert [r["symbol"] for r in found] == ["UP"]
    assert found[0]["as_of"] == "2026-11-06" and found[0]["values"]["Close"] == 249.5
    q = preset("Quality in uptrend")
    assert [r["symbol"] for r in screens.run_screen(q["id"])] == ["UP"]  # DOWN/FLAT fail the trend leg


def test_first_seen_kept_on_rerun(world, monkeypatch):
    s = leaders()
    screens.run_screen(s["id"])
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 20))
    again = screens.run_screen(s["id"])
    assert again[0]["first_seen"] == "2026-11-09"
    with db.tx() as c:
        row = c.execute("SELECT first_seen FROM screen_results WHERE screen_id=?", (s["id"],)).fetchone()
    assert row["first_seen"] == "2026-11-09"


def test_results_replaced_when_symbol_drops_out(world):
    sid = leaders()["id"]
    with db.tx() as c:
        row = (sid, "FLAT", "2026-11-01", "{}", "2026-11-01")
        c.execute("INSERT INTO screen_results VALUES (?,?,?,?,?)", row)
    screens.run_screen(sid)
    with db.tx() as c:
        syms = [r[0] for r in c.execute("SELECT symbol FROM screen_results")]
    assert syms == ["UP"]


def test_run_with_no_matches_still_counts_as_run(world, client):
    rule = {"all": [{"left": {"ind": "close"}, "op": ">", "right": {"value": 99999}}]}
    made = client.post("/api/screens", json={"name": "Nothing", "rule": rule}).json()
    assert made["last_run_as_of"] is None
    assert screens.run_screen(made["id"]) == []
    listed = {s["name"]: s for s in client.get("/api/screens").json()}
    assert listed["Nothing"]["count"] == 0 and listed["Nothing"]["last_run_as_of"] == "2026-11-06"
    upd = client.put(f"/api/screens/{made['id']}", json={"name": "Nothing", "rule": rule}).json()
    assert upd["last_run_as_of"] == "2026-11-06"
    assert "screen_last_runs" not in client.get("/api/settings").json()


def test_preview_matches_run(world):
    s = leaders()
    pv = screens.preview(json.loads(s["rule"]))
    run = screens.run_screen(s["id"])
    assert pv["count"] == len(run) == 1
    assert pv["rows"] == [{"symbol": r["symbol"], "values": r["values"]} for r in run]


def test_stale_symbol_is_skipped(world):
    with db.tx() as c:
        c.execute(
            "DELETE FROM bars WHERE sym_id=(SELECT id FROM bar_symbols WHERE symbol='UP') AND day > 20261001"
        )
    frames.invalidate()
    rule = {"all": [{"left": {"ind": "close"}, "op": ">", "right": {"value": 0}}]}
    assert [r["symbol"] for r in screens.scan(rule)] == ["DOWN", "FLAT"]


def test_preview_too_slow(world, monkeypatch):
    monkeypatch.setattr(screens, "PREVIEW_LIMIT_S", -1.0)
    rule = {"all": [{"left": {"ind": "close"}, "op": ">", "right": {"value": 0}}]}
    with pytest.raises(screens.TooSlow):
        screens.preview(rule)


def test_api_crud_and_errors(world, client):
    bad = client.post("/api/screens", json={"name": "x", "rule": {"all": [{"left": {"ind": "smaa"}}]}})
    assert bad.status_code == 400
    bad = client.post("/api/screens/preview", json={"rule": {"all": [
        {"left": {"ind": "smaa"}, "op": ">", "right": {"value": 1}}]}})  # fmt: skip
    assert bad.status_code == 400 and "all[0].left.ind" in bad.json()["detail"]

    rule = {"all": [{"left": {"ind": "close"}, "op": ">", "right": {"value": 200}}]}
    made = client.post("/api/screens", json={"name": "Over 200", "description": "d", "rule": rule}).json()
    assert made["describe"] == "Close is above 200" and made["created_by"] == "user" and not made["is_preset"]
    assert client.post("/api/screens", json={"name": "Over 200", "rule": rule}).status_code == 400
    pv = client.post("/api/screens/preview", json={"rule": rule}).json()  # a job, not a scan (§17.5)
    assert runner.run_one("interactive") == pv["run_id"]
    run = client.get(f"/api/jobs/runs/{pv['run_id']}").json()
    assert run["status"] == "done" and run["ok"] == 1 and run["message"] == "1 stock matches"
    items = client.get(f"/api/jobs/runs/{pv['run_id']}/items?status=ok").json()
    assert [i["key"] for i in items] == ["UP"]
    assert json.loads(items[0]["detail"]) == screens.preview(rule)["rows"][0]["values"]

    upd = client.put(f"/api/screens/{made['id']}", json={"name": "Over 100", "rule": rule}).json()
    assert upd["name"] == "Over 100"

    rid = client.post(f"/api/screens/{made['id']}/run").json()["run_id"]
    assert runner.run_one() == rid
    with db.tx() as c:
        run = dict(c.execute("SELECT * FROM job_runs WHERE id=?", (rid,)).fetchone())
        item = c.execute("SELECT detail FROM job_items WHERE run_id=?", (rid,)).fetchone()
    assert run["status"] == "done" and item["detail"] == "1 matches"

    res = client.get(f"/api/screens/{made['id']}/results").json()
    assert res[0]["symbol"] == "UP" and res[0]["name"] == "Up" and res[0]["score"] is not None
    assert res[0]["reasons"] and res[0]["first_seen"] == "2026-11-09"

    listed = {s["name"]: s for s in client.get("/api/screens").json()}
    assert listed["Over 100"]["count"] == 1 and listed["Over 100"]["last_run_as_of"] == "2026-11-06"
    assert listed["Breadth trend riders"]["count"] == 0 and listed["Breadth trend riders"]["is_preset"]

    assert client.delete(f"/api/screens/{made['id']}").json() == {"ok": True}
    assert client.get(f"/api/screens/{made['id']}/results").status_code == 404
    assert client.post("/api/screens/9999/run").status_code == 404


def test_presets_cannot_be_deleted(client):
    pid = preset("Breadth trend riders")["id"]
    r = client.delete(f"/api/screens/{pid}")
    assert r.status_code == 400
    assert any(s["id"] == pid for s in client.get("/api/screens").json())


def test_job_runs_all_screens_and_has_followup(world):
    rid = runner.enqueue("screens_run")
    assert runner.run_one() == rid
    with db.tx() as c:
        run = dict(c.execute("SELECT * FROM job_runs WHERE id=?", (rid,)).fetchone())
    assert run["status"] == "done" and run["ok"] == 11 and run["failed"] == 0
    from app.jobs import registry as jobs

    assert jobs.get("screens_run").stage == 7 and jobs.get("screens_run").followups == ("signals_track",)


def test_quality_presets_seeded(client):
    q = preset("Quality trend riders")
    rule = json.loads(q["rule"])
    rules.validate_rule(rule)
    assert rules.uses_fundamentals(rule) and len(rule["all"]) == 9
    assert rule["all"][0]["left"] == {"fund": "roce_pct"}
    s = preset("Steady quality leaders")
    rule = json.loads(s["rule"])
    rules.validate_rule(rule)
    assert rule["all"][4]["right"] == {"value": 20}  # rel_strength > 20
    assert rule["all"][-1]["left"]["ind"] == "breadth_above_sma"


def test_rank_operand_picks_top_of_25(client, monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    registry.clear()
    registry.register(source())
    with db.tx() as c:
        for k in range(25):
            sym = f"S{k:02d}"
            c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES (?,?,1)", (sym, sym))
            save_bars("px", bars(sym, lambda i, k=k: 100 * (1 + 0.0005 * (k + 1)) ** i), c)
        save_index("px", [IndexBar(frames.INDEX_NAME, d, 1000.0) for d in DAYS], c)
    frames.invalidate()
    rule = {"all": [{"left": {"ind": "return_pct", "params": {"n": 63}, "rank": True}, "op": ">",
                     "right": {"value": 80}}]}  # 25 stocks: the 20th is exactly 80, so ">" gives 5
    try:
        assert [r["symbol"] for r in screens.scan(rule)] == [f"S{k:02d}" for k in range(20, 25)]
    finally:
        registry.clear()
        frames.invalidate()
