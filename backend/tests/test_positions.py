import pandas as pd

from app import db
from app.analytics import frames
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec
from app.sources.store import save_bars


def seed():
    registry.clear()
    registry.register(type(
        "raw", (BaseSource,),
        {"name": "raw", "label": "raw", "description": "d", "homepage": "h",
         "capabilities": (CapabilitySpec("bars", "by_symbol", (), adjusted=True),)},
    )())  # fmt: skip
    db.set_setting("source_priority", {"bars": ["raw"]})
    frames.invalidate()
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-10-01", periods=20)]
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','Aaa Ltd',1)")
        save_bars("raw", [Bar("AAA", d, 100, 102, 98, 100, 1000) for d in days], c)  # ATR14 = 4, close 100


def answers(**over):
    a = {"thesis": "growth", "wrong_if": "below 90", "entry_price": 100, "stop": 95, "target": 110,
         "time_stop_weeks": 8, "risk_pct": 1, "read_announcements": True, "checked_results": True,
         "emotion": "calm"}  # fmt: skip
    return {**a, **over}


def exit_answers(price=110, reason="target", thesis="yes"):
    return {"exit_price": price, "exit_reason": reason, "thesis_right": thesis, "lesson": "ok"}


def test_questions(client):
    q = client.get("/api/positions/checklist/questions").json()
    assert [x["id"] for x in q["entry"]][:2] == ["thesis", "wrong_if"] and len(q["exit"]) == 4


def test_suggest_sizing(client):
    seed()
    r = client.get("/api/positions/suggest", params={"symbol": "AAA", "entry": 100, "stop": 95}).json()
    assert r["qty"] == 1000 and r["risk_per_share"] == 5 and r["suggested_target"] == 110 and r["rr"] == 2
    flat = client.get("/api/positions/suggest", params={"symbol": "AAA", "entry": 100, "stop": 100})
    assert flat.json()["qty"] == 0
    d = client.get("/api/positions/suggest", params={"symbol": "AAA"}).json()
    assert d["last_close"] == 100 and d["atr14"] == 4 and d["suggested_stop"] == 92  # 100 - 2*4
    assert d["qty"] == 625 and d["capital"] == 500000  # 5000 / 8
    assert client.get("/api/positions/suggest", params={"symbol": "NOPE"}).status_code == 400


def test_create_validation(client):
    seed()
    body = {"symbol": "AAA", "qty": 10, "entry_date": "2026-10-20"}
    bad = answers()
    del bad["thesis"]
    r = client.post("/api/positions", json={**body, "answers": bad})
    assert r.status_code == 400 and "thesis" in r.json()["detail"]
    r = client.post("/api/positions", json={**body, "answers": answers(read_announcements=False)})
    assert r.status_code == 400 and "read_announcements" in r.json()["detail"]
    r = client.post("/api/positions", json={**body, "answers": answers(emotion="happy")})
    assert r.status_code == 400 and "emotion" in r.json()["detail"]
    assert client.get("/api/positions").json() == []  # nothing half-saved
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM checklists").fetchone()[0] == 0


def test_full_flow(client):
    seed()
    r = client.post("/api/positions", json={"symbol": "aaa", "qty": 10, "entry_date": "2026-10-20",
                                            "answers": answers(), "ai_review": {"x": 1}})  # fmt: skip
    assert r.status_code == 200
    p = r.json()
    assert p["symbol"] == "AAA" and p["stop"] == 95 and p["target"] == 110
    assert p["time_stop_date"] == "2026-12-15"  # +8 weeks
    assert p["r_multiple"] == 0 and p["to_stop_pct"] == round((100 / 95 - 1) * 100, 2)
    assert p["pnl_inr"] == 0 and p["to_target_pct"] == 10.0
    assert client.get("/api/symbols/AAA").json()["open_position_id"] == p["id"]
    listed = client.get("/api/positions", params={"status": "open"}).json()
    assert [x["id"] for x in listed] == [p["id"]] and listed[0]["days_to_time_stop"] is not None

    moved = client.put(f"/api/positions/{p['id']}", json={"stop": 98}).json()
    assert moved["stop"] == 98 and moved["r_multiple"] == 0

    cl = client.get(f"/api/positions/{p['id']}/checklists").json()
    assert [x["kind"] for x in cl] == ["entry"] and cl[0]["answers"]["thesis"] == "growth"

    assert client.post(f"/api/positions/{p['id']}/close", json={"exit_date": "2026-11-02",
                       "answers": {"exit_price": 110}}).status_code == 400  # fmt: skip
    closed = client.post(f"/api/positions/{p['id']}/close",
                         json={"exit_date": "2026-11-02", "answers": exit_answers()}).json()  # fmt: skip
    assert closed["status"] == "closed" and closed["exit_price"] == 110
    assert closed["r_multiple"] == 2.0  # (110-100)/(100-95): the stop chosen at entry, not the trailed one
    assert client.get("/api/positions").json() == []
    assert len(client.get("/api/positions", params={"status": "closed"}).json()) == 1
    again = client.post(f"/api/positions/{p['id']}/close",
                        json={"exit_date": "2026-11-03", "answers": exit_answers()})  # fmt: skip
    assert again.status_code == 400
    assert client.get("/api/symbols/AAA").json()["open_position_id"] is None


def test_journal_stats(client):
    seed()
    assert client.get("/api/journal/stats").json()["closed"] == 0
    for emotion, price, reason, thesis in [("calm", 110, "target", "yes"), ("FOMO", 90, "stop", "no")]:
        p = client.post("/api/positions", json={"symbol": "AAA", "qty": 10, "entry_date": "2026-10-20",
                                                "answers": answers(emotion=emotion)}).json()  # fmt: skip
        client.post(f"/api/positions/{p['id']}/close", json={
            "exit_date": "2026-11-02", "answers": exit_answers(price, reason, thesis)})  # fmt: skip
    s = client.get("/api/journal/stats").json()
    assert s["closed"] == 2 and s["win_rate"] == 50.0
    assert s["avg_r"] == 0.0  # +2R and -2R
    assert s["avg_win_pct"] == 10.0 and s["avg_loss_pct"] == -10.0 and s["thesis_right_pct"] == 50.0
    assert s["by_exit_reason"]["stop"] == {"n": 1, "win_rate": 0.0, "avg_r": -2.0}
    assert s["by_emotion"]["calm"]["win_rate"] == 100.0
