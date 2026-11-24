import pandas as pd
import pytest

from app import bardb, config, db
from app.analytics import adjust, frames, indicators, price_store
from app.backtest import universe as uni
from app.sources import registry
from app.sources.base import Action, Bar, BaseSource, CapabilitySpec
from app.sources.store import save_actions, save_bars


def make(name, adjusted):
    specs = tuple(
        CapabilitySpec(c, "by_symbol", (), adjusted=adjusted if c == "bars" else None)
        for c in ("bars", "actions")
    )
    return type(
        name, (BaseSource,),
        {"name": name, "label": name, "description": "d", "homepage": "h", "capabilities": specs},
    )()  # fmt: skip


@pytest.fixture(autouse=True)
def _world():
    db.init_db()
    registry.clear()
    registry.register(make("raw", False))
    registry.register(make("adj", True))
    db.set_setting("source_priority", {"bars": ["raw", "adj"], "actions": ["raw", "adj"]})
    frames.invalidate()
    yield
    registry.clear()
    price_store.ENABLED = True
    frames.invalidate()


def days(start: str, n: int) -> list[str]:
    return [str(d.date()) for d in pd.bdate_range(start, periods=n)]


def seed() -> None:
    """A split, an event factor, a manual adjustment, a rename, a yfinance-only symbol, an empty one."""
    d = days("2026-01-05", 30)
    with db.tx() as c:
        bars = [Bar("SPL", x, 100 + i, 101 + i, 99 + i, 100 + i, 1000.0 + i) for i, x in enumerate(d)]
        bars += [
            Bar("EVT", x, 50 + i, 51 + i, 49 + i, 50 + i, 10.0, value=500.0 + i) for i, x in enumerate(d)
        ]
        bars += [Bar("MAN", x, 30 + i, 31 + i, 29 + i, 30 + i, 7.0) for i, x in enumerate(d)]
        bars += [Bar("OLD", x, 10 + i, 11 + i, 9 + i, 10 + i, 5.0) for i, x in enumerate(d[:15])]
        bars += [Bar("NEW", x, 20 + i, 21 + i, 19 + i, 20 + i, 6.0) for i, x in enumerate(d[10:], 10)]
        save_bars("raw", bars, c)
        save_bars("adj", [Bar("YF", x, 5 + i, 6 + i, 4 + i, 5 + i, 3.0) for i, x in enumerate(d)], c)
        save_actions("raw", [Action("SPL", d[12], "Split", "split", 0.5)], c)
        c.execute(
            "INSERT INTO event_factors(symbol, ex_date, kind, factor, method, computed_at) "
            "VALUES ('EVT', ?, 'demerger', 0.8, 'open', 'x')", (d[8],),
        )
        c.execute("INSERT INTO manual_adjustments(symbol, ex_date, factor) VALUES ('MAN', ?, 0.25)", (d[5],))
        c.execute(
            "INSERT INTO symbol_changes(source, old_symbol, new_symbol, effective_date) "
            "VALUES ('manual','OLD','NEW',?)", (d[15],),
        )
    frames.invalidate()


SYMBOLS = ["SPL", "EVT", "MAN", "NEW", "YF", "NONE"]


def load_all() -> dict[str, pd.DataFrame]:
    return {s: frames.load_frame(s) for s in SYMBOLS}


def assert_same(a: dict, b: dict) -> None:
    for s in SYMBOLS:
        pd.testing.assert_frame_equal(a[s], b[s])
        assert a[s].attrs["source"] == b[s].attrs["source"]
        assert a[s].attrs["symbol"] == b[s].attrs["symbol"]


def reference() -> dict:
    price_store.ENABLED = False
    frames.invalidate()
    try:
        return load_all()
    finally:
        price_store.ENABLED = True
        frames.invalidate()


def test_store_equals_sql_cold_then_from_disk():
    seed()
    want = reference()
    assert_same(load_all(), want)  # empty store, filled from SQL
    price_store.save_if_dirty()
    assert (config.DATA_DIR / "cache" / "price_store.pkl").exists()
    price_store._store.update(path=None, raw={})  # a new process: only the file is left
    frames.invalidate()
    assert_same(load_all(), want)
    assert price_store._store["raw"]  # came back from the file


def test_append_does_not_reread_everything(monkeypatch):
    seed()
    load_all()
    price_store.save_if_dirty()
    d = days("2026-03-01", 2)
    with db.tx() as c:
        save_bars("raw", [Bar("SPL", x, 200, 201, 199, 200, 1.0) for x in d], c)
    frames.invalidate()
    reads: list = []
    real = price_store.rows_to_frame
    monkeypatch.setattr(price_store, "rows_to_frame", lambda rows: (reads.append(len(rows)), real(rows))[1])
    got = load_all()
    assert reads == [2]  # only the two new bars were turned into rows; nothing was re-read in full
    monkeypatch.undo()
    assert_same(got, reference())
    assert len(got["SPL"]) == 32


def test_rewritten_bar_is_dropped_and_reread():
    seed()
    load_all()
    first = days("2026-01-05", 1)[0]
    with db.tx() as c:
        c.execute("UPDATE bars SET close_p=77700 WHERE "
                  "source_id=(SELECT id FROM bar_sources WHERE name='raw') "
                  "AND sym_id=(SELECT id FROM bar_symbols WHERE symbol='MAN') "
                  "AND day=?", (bardb.day(first),))
    frames.invalidate()
    got = load_all()
    assert ("raw", "MAN") in price_store._store["raw"]
    assert got["MAN"]["close"].iloc[0] == pytest.approx(777 * 0.25)
    assert_same(got, reference())


@pytest.mark.parametrize("damage", ["corrupt", "version", "order"])
def test_bad_file_means_silent_rebuild(damage):
    seed()
    want = reference()
    load_all()
    price_store.save_if_dirty()
    path = config.DATA_DIR / "cache" / "price_store.pkl"
    if damage == "corrupt":
        path.write_bytes(b"not a pickle")
    elif damage == "version":
        monkey = price_store.VERSION
        price_store.VERSION = monkey + 1
        try:
            price_store._store.update(path=None, raw={})
            frames.invalidate()
            assert_same(load_all(), want)
        finally:
            price_store.VERSION = monkey
        return
    else:
        db.set_setting("source_priority", {"bars": ["adj", "raw"], "actions": ["raw", "adj"]})
    price_store._store.update(path=None, raw={})
    frames.invalidate()
    if damage == "order":
        want = reference()
        frames.invalidate()
    assert_same(load_all(), want)


def test_warm_hit_makes_no_queries(monkeypatch):
    seed()
    load_all()
    seen: list[str] = []
    real = db.connect

    def traced():
        conn = real()
        conn.set_trace_callback(seen.append)
        return conn

    monkeypatch.setattr(db, "connect", traced)
    load_all()
    assert seen == []


def test_cache_tag_is_a_string_and_memo_hits():
    seed()
    f = frames.load_frame("SPL")
    assert isinstance(f.attrs["cache_key"], str)
    a = indicators.compute("sma", f, n=5)
    assert indicators._memo_key(indicators.get("sma"), f, None, {"n": 5}) in indicators._memo
    pd.testing.assert_series_equal(a, indicators.compute("sma", f, n=5))


def ranks_via_sql():
    price_store.ENABLED = False
    try:
        with db.read() as c:
            return uni._compute_ranks(c, registry.ordered("bars", c))
    finally:
        price_store.ENABLED = True


def ranks_via_store():
    with db.read() as c:
        return uni._compute_ranks(c, registry.ordered("bars", c))


def test_ranks_equal_sql_scratch_and_after_new_month():
    seed()
    pd.testing.assert_frame_equal(ranks_via_store(), ranks_via_sql())
    price_store.save_if_dirty()
    assert not price_store._store["months"]["raw"].empty
    with db.tx() as c:  # a new month: January becomes complete, February is partial
        save_bars("raw", [Bar("SPL", "2026-03-02", 5, 5, 5, 5, 1.0)], c)
        save_bars("raw", [Bar("EVT", "2026-03-03", 9, 9, 9, 9, 2.0)], c)
    frames.invalidate()
    pd.testing.assert_frame_equal(ranks_via_store(), ranks_via_sql())
    with db.tx() as c:  # an old month rewritten
        c.execute("UPDATE bars SET close_p=999900 WHERE "
                  "source_id=(SELECT id FROM bar_sources WHERE name='raw') "
                  "AND sym_id=(SELECT id FROM bar_symbols WHERE symbol='MAN') "
                  "AND day=20260106")
    frames.invalidate()
    pd.testing.assert_frame_equal(ranks_via_store(), ranks_via_sql())


def test_lineage_and_factors_match_sql():
    seed()
    with db.read() as c:
        want = {s: (adjust.lineage(s, c), adjust.adjustment_factors(s, c)) for s in SYMBOLS}
    load_all()
    assert price_store.current() is not None
    got = {s: (adjust.lineage(s, None), adjust.adjustment_factors(s, None)) for s in SYMBOLS}
    assert got == want


def test_invalidate_inside_tx_clears_again_after_commit():
    """A load between invalidate() and COMMIT must not leave pre-commit data cached."""
    from app import db
    from app.analytics import frames

    calls: list[str] = []
    frames.register_cache(_Spy(calls))
    with db.tx():
        frames.invalidate()
        assert calls == ["clear"]
    assert calls == ["clear", "clear"]
    frames.invalidate()  # outside a transaction: both clears run at once
    assert calls == ["clear", "clear", "clear", "clear"]
    frames._extra_caches[:] = [c for c in frames._extra_caches if not isinstance(c, _Spy)]


class _Spy(dict):
    def __init__(self, calls: list[str]) -> None:
        super().__init__()
        self.calls = calls

    def clear(self) -> None:
        self.calls.append("clear")
