import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from app import db
from app.jobs import registry as jobs_registry
from app.jobs import runner
from app.sources import http, registry
from app.sources import jobs as sj
from app.sources.adapters import nse_bhav
from app.sources.base import SourceError
from app.sources.parsers.bhavcopy import bhav_url, parse_bhav

FX = Path(__file__).parent / "fixtures/sources/nse_bhav"
UDIFF = (FX / "bhav_udiff_20261106.csv").read_bytes()
OLD = (FX / "bhav_old_20150102.csv").read_bytes()


def zipped(data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", data)
    return buf.getvalue()


def test_urls():
    assert bhav_url(date(2026, 11, 6)).endswith("BhavCopy_NSE_CM_0_0_0_20261106_F_0000.csv.zip")
    assert bhav_url(date(2015, 1, 2)).endswith("/2015/JAN/cm02JAN2015bhav.csv.zip")
    assert bhav_url(date(2024, 7, 5)).endswith("cm05JUL2024bhav.csv.zip")
    assert "BhavCopy_NSE_CM" in bhav_url(date(2024, 7, 8))


def test_udiff_fixture():
    bars = parse_bhav(UDIFF, date(2026, 11, 6))
    assert len(bars) == 5 and "TCS" in {b.symbol for b in bars}
    b = next(b for b in bars if b.symbol == "HDFCBANK")
    got = (b.open, b.high, b.low, b.close, b.volume, b.trades)
    assert got == (764.4, 788.25, 754.05, 788.25, 73482878, 584286)
    assert b.date == "2026-11-06"


def test_series_and_isin_from_both_formats():
    old = {b.symbol: b for b in parse_bhav(OLD, date(2015, 1, 2))}
    assert (old["20MICRONS"].series, old["20MICRONS"].isin) == ("EQ", "INE144J01027")
    new = {b.symbol: b for b in parse_bhav(UDIFF, date(2026, 11, 6))}
    assert (new["HDFCBANK"].isin, new["HDFCBANK"].series) == ("INE040A01034", "EQ")


def test_old_fixture_and_zip_match():
    bars = parse_bhav(OLD, date(2015, 1, 2))
    assert len(bars) == 5
    h = next(b for b in bars if b.symbol == "HDFCBANK")
    assert h.close == 965.3 and h.volume == 1475096
    assert parse_bhav(zipped(OLD), date(2015, 1, 2)) == bars
    assert parse_bhav(zipped(UDIFF), date(2026, 11, 6)) == parse_bhav(UDIFF, date(2026, 11, 6))


def _udiff_row(sym: str, series: str, close: str = "10", tp: str = "STK") -> str:
    cols = UDIFF.decode().splitlines()[1].split(",")
    cols[4], cols[7], cols[8] = tp, sym, series
    cols[14:18] = ["9", "11", "8", close]
    return ",".join(cols)


def test_udiff_keeps_eq_be_bz():
    head = UDIFF.decode().splitlines()[0]
    rows = [
        _udiff_row("AAA", "EQ"), _udiff_row("BBB", "BE"), _udiff_row("CCC", "BZ"),
        _udiff_row("DDD", "SM"), _udiff_row("EEE", "BE", tp="IDX"),
    ]  # fmt: skip
    got = parse_bhav("\n".join([head, *rows]).encode(), date(2026, 11, 6))
    assert [b.symbol for b in got] == ["AAA", "BBB", "CCC"]


def test_old_format_keeps_eq_be_bz():
    head = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TOTTRDVAL,TOTALTRADES"
    rows = [f"{s},{r},1,2,1,2,10,20,3" for s, r in (("A", "EQ"), ("B", "BE"), ("C", "BZ"), ("D", "SM"))]
    got = parse_bhav("\n".join([head, *rows]).encode(), date(2015, 1, 2))
    assert [b.symbol for b in got] == ["A", "B", "C"]


def test_udiff_keeps_reit_and_invit_units():
    head = UDIFF.decode().splitlines()[0]
    rows = [_udiff_row("REIT1", "RR"), _udiff_row("INV1", "IV"), _udiff_row("X", "RR", tp="IDX")]
    got = parse_bhav("\n".join([head, *rows]).encode(), date(2026, 11, 6))
    assert [b.symbol for b in got] == ["REIT1", "INV1"]


def test_old_format_keeps_reit_and_invit_units():
    head = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TOTTRDVAL,TOTALTRADES"
    rows = [f"{s},{r},1,2,1,2,10,20,3" for s, r in (("A", "RR"), ("B", "IV"))]
    got = parse_bhav("\n".join([head, *rows]).encode(), date(2015, 1, 2))
    assert [b.symbol for b in got] == ["A", "B"]


def test_same_symbol_in_eq_and_be_gives_one_eq_bar():
    head = UDIFF.decode().splitlines()[0]
    for rows in (
        [_udiff_row("XYZ", "BE", "5"), _udiff_row("XYZ", "EQ", "7")],
        [_udiff_row("XYZ", "EQ", "7"), _udiff_row("XYZ", "BE", "5")],
    ):
        got = parse_bhav("\n".join([head, *rows]).encode(), date(2026, 11, 6))
        assert [(b.symbol, b.close) for b in got] == [("XYZ", 7.0)]


def test_filters_and_missing_prices():
    text = UDIFF.decode().splitlines()
    cols = text[1].split(",")
    other_series = cols.copy()
    other_series[8] = "SM"
    not_stock = cols.copy()
    not_stock[4] = "IDX"
    no_close = cols.copy()
    no_close[17] = ""
    data = "\n".join([text[0], ",".join(other_series), ",".join(not_stock), ",".join(no_close), text[2]])
    assert [b.symbol for b in parse_bhav(data.encode(), date(2026, 11, 6))] == ["IRFC"]


def test_bad_inputs():
    with pytest.raises(SourceError):
        parse_bhav(b"a,b\n1,2\n", date(2026, 11, 6))
    with pytest.raises(SourceError):
        parse_bhav(b"PK\x03\x04junk", date(2026, 11, 6))


@pytest.fixture
def job(monkeypatch):
    db.init_db()
    saved_src, saved_jobs = dict(registry._sources), dict(jobs_registry._JOBS)
    registry._sources.clear()
    jobs_registry._JOBS.clear()
    registry.register(nse_bhav.NseBhav())
    sj.register_source_jobs()
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    yield
    http.set_transport(None)
    registry._sources.clear()
    registry._sources.update(saved_src)
    jobs_registry._JOBS.clear()
    jobs_registry._JOBS.update(saved_jobs)


def test_daily_job_stores_bars_and_records_holiday(job):
    def serve(url, params, headers):
        return (200, zipped(UDIFF)) if "20261106" in url else (404, b"")

    http.set_transport(serve)
    rid = runner.enqueue("bars.nse_bhav.daily", params={"keys": ["2026-11-06", "2026-11-07"]})
    assert runner.run_one() == rid
    with db.tx() as c:
        q = "SELECT COUNT(*) FROM bars b JOIN bar_sources s ON s.id=b.source_id WHERE s.name='nse_bhav'"
        assert c.execute(q).fetchone()[0] == 5
        st = {r["key"]: r["status"] for r in c.execute("SELECT key, status FROM source_fetch")}
    assert st == {"2026-11-06": "ok", "2026-11-07": "not_found"}
    assert jobs_registry.get("bars.nse_bhav.backfill").stage == 7
