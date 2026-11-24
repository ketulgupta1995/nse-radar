from pathlib import Path


def test_get_all(client):
    s = client.get("/api/settings").json()
    assert s["risk_per_trade_pct"] == 1.0 and "cost_model" in s and "source_priority" in s


def test_valid_partial_update(client):
    r = client.put("/api/settings", json={"risk_per_trade_pct": 2, "score_weights": {"rs": 50, "trend": 50}})
    assert r.status_code == 200
    body = r.json()
    assert body["risk_per_trade_pct"] == 2 and body["score_weights"] == {"rs": 50, "trend": 50}
    assert client.get("/api/settings").json()["capital_inr"] == 500000  # untouched


def test_invalid_values_name_the_key(client):
    for body, key in [
        ({"risk_per_trade_pct": 9}, "risk_per_trade_pct"),
        ({"score_weights": {"rs": 500}}, "score_weights"),
        ({"rss_feeds": [{"name": "x", "url": "ftp://a"}]}, "rss_feeds"),
        ({"ai_model": ""}, "ai_model"),
        ({"source_priority": {"bars": ["nope"]}}, "source_priority"),
        ({"fundamentals_field_priority": {"f": ["nope"]}}, "fundamentals_field_priority"),
        ({"cost_model": {"brokerage_pct": 1}}, "cost_model"),
    ]:
        r = client.put("/api/settings", json=body)
        assert r.status_code == 400 and r.json()["detail"].startswith(key), body


def test_unknown_key(client):
    r = client.put("/api/settings", json={"bogus": 1})
    assert r.status_code == 400 and "bogus" in r.json()["detail"]


def _fake(name, *caps):
    from app.sources.base import BaseSource, CapabilitySpec

    return type(
        name, (BaseSource,),
        {"name": name, "label": name, "description": "d", "homepage": "h",
         "capabilities": tuple(CapabilitySpec(c, "by_symbol", ()) for c in caps)},
    )()  # fmt: skip


def test_valid_registry_settings(client):
    from app.sources import registry

    registry.clear()
    registry.register(_fake("aa", "bars", "fundamentals"))
    registry.register(_fake("bb", "bars"))
    r = client.put("/api/settings", json={
        "source_priority": {"bars": ["bb", "aa"]},
        "fundamentals_field_priority": {"profit_positive_4q": ["quarters", "aa"]},
    })  # fmt: skip
    assert r.status_code == 200 and r.json()["source_priority"] == {"bars": ["bb", "aa"]}
    r = client.put("/api/settings", json={"source_priority": {"bars": ["zz"]}})
    assert r.status_code == 400


def test_trend_exit_settings(client):
    s = client.get("/api/settings").json()
    assert s["position_exit_sma"] == 100 and s["trail_atr_multiple"] == 5.0
    r = client.put("/api/settings", json={"position_exit_sma": 0, "trail_atr_multiple": 0})
    assert r.status_code == 200
    assert r.json()["position_exit_sma"] == 0 and r.json()["trail_atr_multiple"] == 0
    ok = {"position_exit_sma": 50, "trail_atr_multiple": 3.5}
    assert client.put("/api/settings", json=ok).status_code == 200
    for body, key in [
        ({"position_exit_sma": 10}, "position_exit_sma"),
        ({"position_exit_sma": 301}, "position_exit_sma"),
        ({"trail_atr_multiple": 0.5}, "trail_atr_multiple"),
        ({"trail_atr_multiple": 16}, "trail_atr_multiple"),
    ]:
        r = client.put("/api/settings", json=body)
        assert r.status_code == 400 and r.json()["detail"].startswith(key), body


def test_backup_creates_file(client):
    r = client.post("/api/backup").json()
    p = Path(r["path"])
    assert p.exists() and p.parent.name == "backups" and r["size_bytes"] == p.stat().st_size > 0
