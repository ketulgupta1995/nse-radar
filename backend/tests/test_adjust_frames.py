import pandas as pd
import pytest

from app import bardb, db
from app.analytics import adjust, frames
from app.sources import registry
from app.sources.base import Action, Bar, BaseSource, CapabilitySpec, IndexBar
from app.sources.store import save_actions, save_bars, save_index


def make(name, adjusted=None, caps=("bars", "actions", "index")):
    specs = tuple(
        CapabilitySpec(c, "by_symbol", (), adjusted=adjusted if c == "bars" else None) for c in caps
    )
    return type(
        name, (BaseSource,),
        {"name": name, "label": name, "description": "d", "homepage": "h", "capabilities": specs},
    )()  # fmt: skip


@pytest.fixture(autouse=True)
def _setup():
    db.init_db()
    registry.clear()
    registry.register(make("raw", adjusted=False))
    registry.register(make("adj", adjusted=True))
    db.set_setting(
        "source_priority",
        {"bars": ["raw", "adj"], "actions": ["raw", "adj"], "index": ["raw", "adj"]},
    )
    frames.invalidate()
    yield
    registry.clear()
    frames.invalidate()


DAYS = [f"2026-10-{d:02d}" for d in range(1, 11)]  # 10 days; the split is on day 5 (Oct 5)


def seed_raw_split(symbol="AAA"):
    """Unadjusted: 100 before the 10->2 split on Oct 5, 20 from then on."""
    bars = [
        Bar(symbol, d, *(([100.0] * 4) if i < 4 else ([20.0] * 4)), volume=1000.0 if i < 4 else 5000.0)
        for i, d in enumerate(DAYS)
    ]
    with db.tx() as c:
        save_bars("raw", bars, c)
        save_actions("raw", [Action(symbol, "2026-10-05", "Split", "split", 0.2)], c)


def test_split_makes_series_flat_and_volume_scaled():
    seed_raw_split()
    df, source = adjust.adjusted_ohlcv("AAA")
    assert source == "raw"
    assert (df["close"] == 20.0).all()
    assert (df["volume"] == 5000.0).all()  # 1000 / 0.2 before the split


def test_adjusted_source_returned_unchanged():
    bars = [Bar("BBB", d, 50, 51, 49, 50, 10) for d in DAYS]
    with db.tx() as c:
        save_bars("adj", bars, c)
        save_actions("adj", [Action("BBB", "2026-10-05", "Split", "split", 0.5)], c)
    df, source = adjust.adjusted_ohlcv("BBB")
    assert source == "adj" and (df["close"] == 50).all() and (df["volume"] == 10).all()


def test_priority_and_fallback_source():
    with db.tx() as c:
        save_bars("raw", [Bar("AAA", "2026-10-01", 1, 1, 1, 1, 1)], c)
        save_bars("adj", [Bar("AAA", "2026-10-01", 2, 2, 2, 2, 2)], c)
        save_bars("adj", [Bar("ZZZ", "2026-10-01", 3, 3, 3, 3, 3)], c)
    assert frames.load_frame("AAA").attrs["source"] == "raw"
    z = frames.load_frame("ZZZ")
    assert z.attrs["source"] == "adj" and z["close"].iloc[0] == 3
    assert frames.load_frame("NONE").empty and frames.load_frame("NONE").attrs["source"] == ""
    db.set_setting("source_priority", {"bars": ["adj", "raw"]})
    frames.invalidate()
    assert frames.load_frame("AAA").attrs["source"] == "adj"


def test_same_split_from_two_sources_applied_once():
    seed_raw_split()
    with db.tx() as c:
        save_actions("adj", [Action("AAA", "2026-10-06", "Split (Yahoo)", "split", 0.2)], c)
        assert adjust.adjustment_factors("AAA", c) == [("2026-10-05", 0.2)]
        save_actions("adj", [Action("AAA", "2026-10-20", "Another", "split", 0.5)], c)
        assert adjust.adjustment_factors("AAA", c) == [("2026-10-05", 0.2), ("2026-10-20", 0.5)]


def test_manual_adjustment_replaces_factor():
    seed_raw_split()
    with db.tx() as c:
        c.execute("INSERT INTO manual_adjustments(symbol, ex_date, factor) VALUES ('AAA','2026-10-05',0.5)")
        assert adjust.adjustment_factors("AAA", c) == [("2026-10-05", 0.5)]
    frames.invalidate()
    assert (frames.load_frame("AAA")["close"].iloc[0]) == 50.0


def test_dividends_and_unparsed_ignored():
    with db.tx() as c:
        save_actions("raw", [Action("AAA", "2026-10-05", "Div", "other", None),
                             Action("AAA", "2026-10-06", "??", "unparsed", None)], c)
        assert adjust.adjustment_factors("AAA", c) == []


def test_frame_cache_follows_data_changes():
    seed_raw_split()
    first = frames.load_frame("AAA")
    assert len(first) == 10
    with db.tx() as c:  # the price store is checked once per data version: invalidate() starts a new one
        save_bars("raw", [Bar("AAA", "2026-10-11", 20, 20, 20, 20, 5000)], c)
    frames.invalidate()
    assert len(frames.load_frame("AAA")) == 11
    assert len(frames.load_frame("AAA", start="2026-10-08")) == 4


def test_universe_union_and_last_trading_date():
    with db.tx() as c:
        c.execute(
            "INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','A',1),('BBB','B',0),('CCC','C',1)"
        )
        c.execute("INSERT INTO watchlist(symbol, added_at) VALUES ('BBB','2026-10-01')")
        c.execute(
            "INSERT INTO positions(symbol, qty, entry_date, entry_price, status, created_at) "
            "VALUES ('DDD', 1, '2026-10-01', 10, 'open', '2026-10-01')"
        )
        c.execute(
            "INSERT INTO positions(symbol, qty, entry_date, entry_price, status, created_at) "
            "VALUES ('EEE', 1, '2026-10-01', 10, 'closed', '2026-10-01')"
        )
        save_bars("raw", [Bar("AAA", "2026-10-08", 1, 1, 1, 1), Bar("CCC", "2026-10-09", 1, 1, 1, 1),
                          Bar("BBB", "2026-10-30", 1, 1, 1, 1)], c)
        save_bars("adj", [Bar("AAA", "2026-10-31", 1, 1, 1, 1)], c)
        assert frames.universe(c) == ["AAA", "BBB", "CCC", "DDD"]
        assert frames.last_trading_date(c) == "2026-10-09"  # primary source, universe symbols only


def test_benchmark_follows_priority():
    with db.tx() as c:
        save_index("adj", [IndexBar("NIFTY 500", "2026-10-01", 100.0)], c)
        save_index("adj", [IndexBar("NIFTY 500", "2026-10-02", 101.0)], c)
    b = frames.load_benchmark()
    assert list(b) == [100.0, 101.0] and b.attrs["source"] == "adj"
    with db.tx() as c:
        save_index("raw", [IndexBar("NIFTY 500", "2026-10-01", 5.0)], c)
    b = frames.load_benchmark()
    assert list(b) == [5.0, 101.0] and b.attrs["source"] == "raw"  # raw wins its date, adj fills the gap
    assert list(frames.load_benchmark(start="2026-10-02")) == [101.0]
    assert isinstance(frames.load_benchmark(), pd.Series)


def test_benchmark_short_primary_does_not_cut_history():
    with db.tx() as c:
        save_index("adj", [IndexBar("NIFTY 500", f"2026-09-{d:02d}", 100.0 + d) for d in range(1, 11)], c)
        save_index("raw", [IndexBar("NIFTY 500", "2026-09-10", 110.0)], c)
    b = frames.load_benchmark()
    assert len(b) == 10 and b.iloc[0] == 101.0 and b.iloc[-1] == 110.0
    assert b.index.is_monotonic_increasing


# ---- ticker lineage (T078) ----


def _bars(symbol, days, price):
    return [Bar(symbol, d, price, price, price, price, 1000.0) for d in days]


def _days(a, b):
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(a, b)]


def _change(old, new, eff, source="manual"):
    with db.tx() as c:
        c.execute(
            "INSERT OR REPLACE INTO symbol_changes(source, old_symbol, new_symbol, effective_date) "
            "VALUES (?,?,?,?)",
            (source, old, new, eff),
        )


def test_two_step_chain_uses_old_bars_before_rename():
    with db.tx() as c:
        save_bars("adj", _bars("A", _days("2020-01-01", "2020-01-10"), 1.0), c)
        save_bars("adj", _bars("B", _days("2020-01-08", "2020-01-20"), 2.0), c)
    _change("A", "B", "2020-01-08")
    with db.read() as c:
        df = adjust.load_raw("B", "adj", c)
    assert df.index.is_unique
    assert df.index[0] == pd.Timestamp("2020-01-01") and df.index[-1] == pd.Timestamp("2020-01-20")
    assert (df.loc[:"2020-01-07", "close"] == 1.0).all()
    assert (df.loc["2020-01-08":, "close"] == 2.0).all()
    assert len(df) == 20


def test_lineage_only_where_source_has_old_ticker_bars():
    with db.tx() as c:
        save_bars("s1", _bars("A", _days("2020-01-01", "2020-01-10"), 1.0), c)
        save_bars("s1", _bars("B", _days("2020-01-08", "2020-01-20"), 2.0), c)
        save_bars("s2", _bars("B", _days("2019-12-01", "2020-01-20"), 3.0), c)
    _change("A", "B", "2020-01-08")
    with db.read() as c:
        d1 = adjust.load_raw("B", "s1", c)
        d2 = adjust.load_raw("B", "s2", c)
    assert len(d1) == 20 and d1.index[0] == pd.Timestamp("2020-01-01")
    assert d2.index[0] == pd.Timestamp("2019-12-01") and len(d2) == 51
    assert (d2["close"] == 3.0).all()


def test_three_step_lineage_and_no_changes():
    _change("LTI", "LTIM", "2022-12-05")
    _change("LTIM", "LTM", "2026-02-27")
    with db.read() as c:
        assert adjust.lineage("LTM", c) == [
            ("LTI", None, "2022-12-05"),
            ("LTIM", "2022-12-05", "2026-02-27"),
            ("LTM", "2026-02-27", None),
        ]
        assert adjust.lineage("ZZZ", c) == [("ZZZ", None, None)]


def test_recycled_ticker_drops_old_company_bars():
    with db.tx() as c:
        save_bars("adj", _bars("C", _days("2015-01-01", "2015-01-10"), 9.0), c)
        save_bars("adj", _bars("X", _days("2019-12-20", "2019-12-31"), 1.0), c)
        save_bars("adj", _bars("C", _days("2020-01-01", "2020-01-05"), 2.0), c)
    _change("X", "C", "2020-01-01")
    with db.read() as c:
        df = adjust.load_raw("C", "adj", c)
    assert df.index.min() == pd.Timestamp("2019-12-20")
    assert not ((df.index >= "2015-01-01") & (df.index <= "2015-12-31")).any()
    assert len(df) == 12 + 5


def test_lineage_cycle_terminates():
    _change("A", "B", "2020-01-01")
    _change("B", "A", "2021-01-01")
    with db.read() as c:
        assert len(adjust.lineage("B", c)) <= 11
        assert len(adjust.lineage("A", c)) <= 11


def test_no_changes_reads_as_before():
    seed_raw_split()
    with db.read() as c:
        rows = c.execute(
            "SELECT day, close_p / 100.0 AS close FROM bars WHERE source_id=(SELECT id FROM bar_sources "
            "WHERE name='raw') AND sym_id=(SELECT id FROM bar_symbols WHERE symbol='AAA') ORDER BY day"
        ).fetchall()
        new = adjust.load_raw("AAA", "raw", c)
    assert list(new.index) == list(pd.to_datetime([bardb.iso(r["day"]) for r in rows]))
    assert list(new["close"]) == [r["close"] for r in rows]


def test_frame_follows_manual_change():
    with db.tx() as c:
        save_bars("adj", _bars("A", _days("2020-01-01", "2020-01-10"), 1.0), c)
        save_bars("adj", _bars("B", _days("2020-01-08", "2020-01-20"), 2.0), c)
    assert len(frames.load_frame("B")) == 13
    _change("A", "B", "2020-01-08")
    frames.invalidate()
    assert len(frames.load_frame("B")) == 20


def test_symbol_change_endpoints(client):
    r = client.post(
        "/api/data/symbol-change",
        json={"old_symbol": "lti", "new_symbol": "ltim", "effective_date": "2022-12-05", "note": "n"},
    )
    assert r.status_code == 200
    assert r.json()["old_symbol"] == "LTI" and r.json()["source"] == "manual"
    for body in (
        {"old_symbol": "A", "new_symbol": "a", "effective_date": "2022-12-05"},
        {"old_symbol": "A", "new_symbol": "B", "effective_date": "2022-13-45"},
        {"old_symbol": "A", "new_symbol": "B", "effective_date": "5/12/2022"},
    ):
        assert client.post("/api/data/symbol-change", json=body).status_code == 400
    g = client.get("/api/data/symbol-changes", params={"symbol": "LTIM"}).json()
    assert g["symbol"] == "LTIM"
    assert g["lineage"] == [
        {"ticker": "LTI", "from_date": None, "until_date": "2022-12-05"},
        {"ticker": "LTIM", "from_date": "2022-12-05", "until_date": None},
    ]
    assert [x["old_symbol"] for x in g["rows"]] == ["LTI"]


def test_load_frame_carries_symbol_attr_also_from_cache():
    seed_raw_split()
    assert frames.load_frame("AAA").attrs["symbol"] == "AAA"
    assert frames.load_frame("AAA").attrs["symbol"] == "AAA"  # cached path
    assert frames.load_frame("NOPE").attrs["symbol"] == "NOPE"  # empty-frame path


def test_repair_frame_keeps_symbol_attr():
    from app.backtest.history import repair_frame

    seed_raw_split()
    out, _ = repair_frame(frames.load_frame("AAA"))
    assert out.attrs["symbol"] == "AAA"
