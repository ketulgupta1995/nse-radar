from app import db
from app.analytics import frames
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec
from app.sources.store import save_bars


def _fake_source():
    return type(
        "raw", (BaseSource,),
        {"name": "raw", "label": "raw", "description": "d", "homepage": "h",
         "capabilities": (CapabilitySpec("bars", "by_symbol", (), adjusted=False),)},
    )()  # fmt: skip


def seed():
    registry.clear()
    registry.register(_fake_source())
    db.set_setting("source_priority", {"bars": ["raw"]})
    frames.invalidate()
    with db.tx() as c:
        c.executemany(
            "INSERT INTO symbols(symbol, name, industry, in_universe) VALUES (?,?,?,?)",
            [("TCS", "Tata Consultancy Services", "IT", 1), ("TATASTEEL", "Tata Steel", "Metals", 1),
             ("INFY", "Infosys", "IT", 0)],
        )
        save_bars(
            "raw",
            [
                Bar("TCS", "2026-11-05", 100, 101, 99, 100, 10),
                Bar("TCS", "2026-11-06", 100, 111, 99, 110, 10),
            ],
            c,
        )


def test_search_prefix_and_name(client):
    seed()
    r = client.get("/api/symbols/search", params={"q": "tc"}).json()
    assert r[0]["symbol"] == "TCS"
    r = client.get("/api/symbols/search", params={"q": "consultancy"}).json()
    assert [x["symbol"] for x in r] == ["TCS"] and r[0]["in_universe"] is True
    assert client.get("/api/symbols/search", params={"q": "tata"}).json()[0]["symbol"] == "TATASTEEL"
    assert client.get("/api/symbols/search", params={"q": ""}).json() == []


def test_search_cap(client):
    with db.tx() as c:
        c.executemany("INSERT INTO symbols(symbol, name, in_universe) VALUES (?,?,1)",
                      [(f"AB{i:02d}", f"Co {i}") for i in range(30)])
    assert len(client.get("/api/symbols/search", params={"q": "AB"}).json()) == 20


def test_detail(client):
    seed()
    d = client.get("/api/symbols/tcs").json()
    assert d["symbol"] == "TCS" and d["last_date"] == "2026-11-06" and d["last_close"] == 110
    assert d["change_pct"] == 10.0 and d["bars_source"] == "raw"
    assert d["in_watchlist"] is False and d["open_position_id"] is None
    nobars = client.get("/api/symbols/INFY").json()
    assert nobars["last_close"] is None and nobars["bars_source"] is None
    assert client.get("/api/symbols/NOPE").status_code == 404


def test_detail_trade_for_trade(client):
    seed()
    with db.tx() as c:
        c.executemany(
            "INSERT INTO instruments(symbol, isin, series, last_date, source) VALUES (?,?,?,?,?)",
            [("TCS", None, "BE", "2026-11-06", "raw"), ("TATASTEEL", None, "EQ", "2026-11-06", "raw")],
        )
    d = client.get("/api/symbols/TCS").json()
    assert d["series"] == "BE" and d["trade_for_trade"] is True
    d = client.get("/api/symbols/TATASTEEL").json()
    assert d["series"] == "EQ" and d["trade_for_trade"] is False
    d = client.get("/api/symbols/INFY").json()
    assert d["series"] is None and d["trade_for_trade"] is False


def test_watchlist_flow(client):
    seed()
    assert client.post("/api/watchlist", json={"symbol": "NOPE"}).status_code == 400
    assert client.post("/api/watchlist", json={"symbol": "tcs", "note": "IT"}).status_code == 200
    items = client.get("/api/watchlist").json()
    assert len(items) == 1 and items[0]["symbol"] == "TCS" and items[0]["name"].startswith("Tata")
    assert items[0]["last_close"] == 110 and items[0]["note"] == "IT"
    assert items[0]["added_close"] is not None  # derived from bars on or before the add date
    assert client.get("/api/symbols/TCS").json()["in_watchlist"] is True
    client.delete("/api/watchlist/TCS")
    assert client.get("/api/watchlist").json() == []
