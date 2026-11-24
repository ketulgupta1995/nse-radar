import json

import pytest

from app import db
from app.sources import registry, store
from app.sources.base import (
    Action,
    Announcement,
    Bar,
    BaseSource,
    CapabilitySpec,
    FundSnapshot,
    IndexBar,
    NewsItem,
    Quarter,
    SymbolRow,
)


def _src(name):
    return type(
        name,
        (BaseSource,),
        {
            "name": name, "label": name, "description": "d", "homepage": "h",
            "capabilities": (CapabilitySpec("universe", "whole", ()),),
        },
    )()  # fmt: skip


@pytest.fixture(autouse=True)
def _setup():
    db.init_db()
    registry.clear()
    store._cache["count"] = None
    registry.register(_src("prim"))
    registry.register(_src("sec"))
    db.set_setting("source_priority", {"universe": ["prim", "sec"]})
    yield
    registry.clear()


def rows(conn, sql, *args):
    return [dict(r) for r in conn.execute(sql, args)]


def test_universe_primary_vs_secondary():
    with db.tx() as c:
        store.save_universe("prim", [SymbolRow("AAA", "Alpha Ltd", "IT", "I1"), SymbolRow("BBB", "Beta")], c)
        store.save_universe("sec", [SymbolRow("AAA", "Other", "X", "I9"), SymbolRow("CCC", "Gamma", "Y")], c)
        got = {r["symbol"]: r for r in rows(c, "SELECT * FROM symbols")}
    assert (got["AAA"]["name"], got["AAA"]["industry"], got["AAA"]["in_universe"]) == ("Alpha Ltd", "IT", 1)
    assert got["BBB"]["in_universe"] == 1
    assert got["CCC"]["in_universe"] == 0 and got["CCC"]["industry"] == "Y"


def test_universe_primary_resets_others_and_is_idempotent():
    with db.tx() as c:
        store.save_universe("prim", [SymbolRow("AAA", "A"), SymbolRow("BBB", "B")], c)
        store.save_universe("prim", [SymbolRow("AAA", "A")], c)
        store.save_universe("prim", [SymbolRow("AAA", "A")], c)
        got = {r["symbol"]: r["in_universe"] for r in rows(c, "SELECT * FROM symbols")}
    assert got == {"AAA": 1, "BBB": 0}


def test_bars_roundtrip_idempotent_and_last_date():
    bars = [Bar("AAA", "2026-11-03", 1, 2, 0.5, 1.5, 100, 1e5, 10), Bar("AAA", "2026-11-04", 1.5, 2, 1, 2)]
    with db.tx() as c:
        for _ in range(2):
            assert store.save_bars("s", bars, c) == 2
        got = rows(c, "SELECT * FROM bars ORDER BY day")
        assert [r["day"] for r in got] == [20261103, 20261104]
        assert len(got) == 2 and got[0]["volume"] == 100 and got[1]["volume"] is None
        assert store.last_bar_date("s", "AAA", c) == "2026-11-04"
        assert store.last_bar_date("s", "ZZZ", c) is None
        assert store.last_bar_date("other", "AAA", c) is None


def test_instruments_upsert_keeps_latest_date():
    with db.tx() as c:
        store.save_bars("s", [Bar("AAA", "2024-01-02", 1, 1, 1, 1, series="EQ", isin="INE000A01010")], c)
        store.save_bars("s", [Bar("AAA", "2023-12-29", 1, 1, 1, 1, series="BE", isin="INE999A01010")], c)
        store.save_bars("s", [Bar("BBB", "2024-01-02", 1, 1, 1, 1)], c)  # no isin/series: no row
        got = rows(c, "SELECT * FROM instruments")
        assert len(got) == 1 and (got[0]["isin"], got[0]["series"]) == ("INE000A01010", "EQ")
        store.save_bars("s", [Bar("AAA", "2024-02-01", 1, 1, 1, 1, series="BE", isin="INE000A01010")], c)
        got = rows(c, "SELECT * FROM instruments")
        assert got[0]["series"] == "BE" and got[0]["last_date"] == "2024-02-01"


def test_actions_roundtrip_idempotent():
    a = [Action("AAA", "2026-10-01", "Split 1:2", "split", 0.5)]
    with db.tx() as c:
        store.save_actions("s", a, c)
        store.save_actions("s", a, c)
        got = rows(c, "SELECT * FROM corp_actions")
    assert len(got) == 1 and got[0]["factor"] == 0.5 and got[0]["kind"] == "split"


def test_index_roundtrip_idempotent():
    b = [IndexBar("NIFTY 500", "2026-11-03", 100.0), IndexBar("NIFTY 500", "2026-11-04", 101.0)]
    with db.tx() as c:
        store.save_index("s", b, c)
        store.save_index("s", b, c)
        assert len(rows(c, "SELECT * FROM index_bars")) == 2
        assert store.last_index_date("s", c) == "2026-11-04"
        assert store.last_index_date("x", c) is None


def test_fundamentals_drops_unknown_fields(caplog):
    snap = FundSnapshot("AAA", {"pe": 12.5, "sector": "IT", "bogus": 1}, {"t": [1]})
    with db.tx() as c:
        store.save_fundamentals("s", snap, c)
        store.save_fundamentals("s", snap, c)
        got = rows(c, "SELECT * FROM fund_snapshots")
    assert len(got) == 1
    assert json.loads(got[0]["fields"]) == {"pe": 12.5, "sector": "IT"}
    assert json.loads(got[0]["detail"]) == {"t": [1]}
    assert "bogus" in caplog.text


def test_quarters_roundtrip_idempotent():
    q = [Quarter("AAA", "2026-09-30", True, audited=False, revenue=10.0, net_profit=2.0, eps=1.5)]
    with db.tx() as c:
        store.save_quarters("s", q, c)
        store.save_quarters("s", q, c)
        got = rows(c, "SELECT * FROM quarters")
    assert len(got) == 1 and got[0]["consolidated"] == 1 and got[0]["audited"] == 0 and got[0]["eps"] == 1.5


def test_announcements_category_and_idempotent():
    items = [
        Announcement("AAA", "2026-11-03T10:00:00", "Board Meeting Intimation"),
        Announcement("AAA", "2026-11-03T11:00:00", "Whatever", category="custom"),
        Announcement("AAA", "2026-11-03T12:00:00", "Hello", body="trading window closure"),
    ]
    with db.tx() as c:
        store.save_announcements("s", items, c)
        store.save_announcements("s", items, c)
        got = {r["ts"][11:13]: r["category"] for r in rows(c, "SELECT * FROM announcements")}
    assert got == {"10": "board_meeting", "11": "custom", "12": "routine"}


@pytest.mark.parametrize(
    "text,cat",
    [
        ("Financial Results for Q2", "results"),
        ("Pledge created by promoter", "pledge"),
        ("Block Deal executed", "block_deal"),
        ("Bagging of new order worth 100 Cr", "order_win"),
        ("Notice of Board Meeting", "board_meeting"),
        ("Credit Rating upgrade", "credit_rating"),
        ("Interim DIVIDEND declared", "dividend"),
        ("Disclosure under SAST", "insider"),
        ("Closure of Trading Window", "routine"),
        ("Merger announced", "other_important"),
        ("Change in registered office", "other"),
    ],
)
def test_categorize(text, cat):
    assert store.categorize(text) == cat


def seed_symbols():
    with db.tx() as c:
        store.save_universe(
            "prim",
            [
                SymbolRow("TCS", "Tata Consultancy Services Limited"),
                SymbolRow("HDFCBANK", "HDFC Bank Limited"),
                SymbolRow("INFY", "Infosys Limited"),
                SymbolRow("RELIANCE", "Reliance Industries Limited"),
            ],
            c,
        )


def test_match_symbols():
    seed_symbols()
    with db.tx() as c:
        m = store.match_symbols
        assert m("Tata Consultancy Services shares rise", c) == {"TCS"}
        assert m("IT stocks fall", c) == set()
        assert m("HDFC Bank results beat estimates", c) == {"HDFCBANK"}
        assert m("infosys wins deal; RELIANCE rallies", c) == {"INFY", "RELIANCE"}
        assert m("reliance rallies", c) == {"RELIANCE"}  # name match is case-insensitive
        assert m("tcs rallies", c) == set()  # bare symbol must be uppercase
        assert m("Wipro gains", c) == set()
        assert m("Infosysx is not a match", c) == set()


def test_match_cache_rebuilds_when_symbol_count_changes():
    seed_symbols()
    with db.tx() as c:
        assert store.match_symbols("Hindustan Unilever gains", c) == set()
        store.save_universe("prim", [SymbolRow("HINDUNILVR", "Hindustan Unilever Limited")], c)
        assert store.match_symbols("Hindustan Unilever gains", c) == {"HINDUNILVR"}


def test_news_links_symbols_and_idempotent():
    seed_symbols()
    items = [
        NewsItem("f", "2026-11-03T10:00:00", "TCS wins big deal", "http://x/1", "Tata Consultancy Services"),
        NewsItem("f", "2026-11-03T11:00:00", "Markets flat", "http://x/2"),
    ]
    with db.tx() as c:
        store.save_news("s", items, c)
        store.save_news("s", items, c)
        assert len(rows(c, "SELECT * FROM news_items")) == 2
        links = rows(c, "SELECT symbol FROM news_symbols")
    assert links == [{"symbol": "TCS"}]


def test_save_symbol_changes_is_idempotent():
    from app.sources.base import SymbolChange

    items = [SymbolChange("ZOMATO", "ETERNAL", "2025-04-09", "ETERNAL LIMITED")]
    with db.tx() as c:
        assert store.save("symbol_changes", "s", items, key="all", conn=c) == 1
        store.save_symbol_changes("s", items, c)
        rows = c.execute("SELECT * FROM symbol_changes").fetchall()
    assert len(rows) == 1
    assert rows[0]["new_symbol"] == "ETERNAL" and rows[0]["note"] is None


def test_save_dispatch():
    with db.tx() as c:
        assert store.save("bars", "s", [Bar("A", "2026-11-03", 1, 1, 1, 1)], key="2026-11-03", conn=c) == 1
        assert store.save("fundamentals", "s", [FundSnapshot("A", {"pe": 1.0}, {})], key="A", conn=c) == 1
        with pytest.raises(ValueError):
            store.save("nope", "s", [], key="k", conn=c)
