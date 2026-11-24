import pandas as pd

from app import db
from app.analytics import frames
from app.sources import registry
from app.sources.base import Action, Bar, BaseSource, CapabilitySpec
from app.sources.store import save_actions, save_bars


def seed(n=30):
    registry.clear()
    registry.register(type(
        "raw", (BaseSource,),
        {"name": "raw", "label": "raw", "description": "d", "homepage": "h",
         "capabilities": (CapabilitySpec("bars", "by_symbol", (), adjusted=True),)},
    )())  # fmt: skip
    db.set_setting("source_priority", {"bars": ["raw"]})
    frames.invalidate()
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-09-01", periods=n)]
    with db.tx() as c:
        bars = [Bar("AAA", d, 100 + i, 101 + i, 99 + i, 100 + i, 1000) for i, d in enumerate(days)]
        save_bars("raw", bars, c)
        save_actions("raw", [Action("AAA", days[10], "Bonus 1:1", "bonus", 0.5),
                             Action("AAA", days[12], "Dividend", "other", None)], c)  # fmt: skip
    return days


def test_shapes(client):
    days = seed()
    r = client.get("/api/prices/aaa", params={"start": "2026-01-01", "indicators": "sma:5,rsi:14"}).json()
    assert r["symbol"] == "AAA" and r["source"] == "raw" and len(r["bars"]) == 30
    assert set(r["bars"][0]) == {"t", "o", "h", "l", "c", "v"}
    assert r["indicators"]["sma:5"][0]["t"] == days[4]  # NaN warm-up omitted
    assert r["indicators"]["sma:5"][-1]["v"] == 127.0
    assert r["indicators"]["rsi:14"][-1]["v"] > 99
    assert r["actions"] == [{"ex_date": days[10], "subject": "Bonus 1:1", "factor": 0.5, "source": "raw"}]


def test_indicator_parsing_positional(client):
    seed()
    r = client.get("/api/prices/AAA", params={"start": "2026-01-01", "indicators": "sma_slope:5:3"})
    assert r.status_code == 200 and len(r.json()["indicators"]["sma_slope:5:3"]) > 0


def test_start_slices_but_averages_are_warmed(client):
    days = seed()
    r = client.get("/api/prices/AAA", params={"start": days[20], "indicators": "sma:15"}).json()
    assert r["bars"][0]["t"] == days[20] and r["indicators"]["sma:15"][0]["t"] == days[20]


def test_bad_indicator_and_params(client):
    seed()
    for spec in ("nope:5", "sma:1", "sma:5:6", "sma:x"):
        r = client.get("/api/prices/AAA", params={"indicators": spec})
        assert r.status_code == 400, spec
    assert client.get("/api/prices/AAA", params={"start": "junk"}).status_code == 400


def test_unknown_symbol_empty(client):
    seed()
    r = client.get("/api/prices/ZZZ", params={"indicators": "sma:5"}).json()
    assert r["bars"] == [] and r["source"] == "" and r["indicators"]["sma:5"] == []
