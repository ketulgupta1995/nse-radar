from pathlib import Path

import pytest

from app import db
from app.jobs import registry as jobs_registry
from app.jobs import runner
from app.sources import http, registry
from app.sources import jobs as sj
from app.sources.adapters import nse_archives
from app.sources.base import SourceError
from app.sources.parsers.nse_lists import parse_nifty500, parse_symbol_changes

FIXTURE = Path(__file__).parent / "fixtures/sources/nse_archives/nifty500list.csv"


def test_parse_fixture():
    rows = parse_nifty500(FIXTURE.read_bytes())
    assert len(rows) == 500  # the file has 501 rows; NSE's DUMMYHEG placeholder is dropped
    assert not [r for r in rows if r.symbol.startswith("DUMMY")]
    assert rows[0].symbol == "360ONE" and rows[0].name == "360 ONE WAM Ltd."
    assert rows[0].industry == "Financial Services" and rows[0].isin == "INE466L01038"


CHANGES = Path(__file__).parent / "fixtures/sources/nse_archives/symbolchange.csv"


def test_parse_symbol_changes_fixture():
    parsed = parse_symbol_changes(CHANGES.read_bytes())
    rows = {(r.old_symbol, r.new_symbol, r.effective_date) for r in parsed}
    assert ("ZOMATO", "ETERNAL", "2025-04-09") in rows
    assert ("INFOSYSTCH", "INFY", "2011-06-29") in rows
    assert ("LTI", "LTIM", "2022-12-05") in rows
    assert ("LTIM", "LTM", "2026-02-27") in rows


def test_parse_symbol_changes_skips_bad_rows(caplog):
    data = (
        "﻿NAME OF THE COMPANY, Old Symbol ,NEW SYMBOL,EFFECTIVE DATE\n"
        "A Ltd,aaa,bbb,01-JAN-2020\n"
        "B Ltd,ccc,ddd,not-a-date\n"
        "C Ltd,eee,EEE,01-JAN-2020\n"
    ).encode()
    rows = parse_symbol_changes(data)
    assert [(r.old_symbol, r.new_symbol) for r in rows] == [("AAA", "BBB")]
    assert sum("skipped 2" in m for m in caplog.messages) == 1


def test_parse_symbol_changes_rejects_unknown_header():
    with pytest.raises(SourceError):
        parse_symbol_changes(b"a,b,c\n1,2,3\n")


def test_symbol_changes_job_exists(job):
    j = jobs_registry.get("symbol_changes.nse_archives")
    assert j.stage == 0
    assert set(j.followups) == {"price_checks", "screens_run"}


def test_parse_rejects_garbage():
    with pytest.raises(SourceError):
        parse_nifty500(b"nothing,useful\n")


@pytest.fixture
def job(monkeypatch):
    db.init_db()
    saved_src, saved_jobs = dict(registry._sources), dict(jobs_registry._JOBS)
    registry._sources.clear()
    jobs_registry._JOBS.clear()
    registry.register(nse_archives.NseArchives())
    sj.register_source_jobs()
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    yield
    http.set_transport(None)
    registry._sources.clear()
    registry._sources.update(saved_src)
    jobs_registry._JOBS.clear()
    jobs_registry._JOBS.update(saved_jobs)


def _serve(data: bytes):
    http.set_transport(lambda url, params, headers: (200, data))


def _run():
    rid = runner.enqueue("universe.nse_archives", params={"keys": ["all"]})
    assert runner.run_one() == rid


def test_generated_job_fills_and_resets_universe(job):
    assert jobs_registry.get("universe.nse_archives").stage == 0
    lines = FIXTURE.read_text().splitlines()
    _serve("\n".join(lines).encode())
    _run()
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM symbols WHERE in_universe=1").fetchone()[0] == 500
    _serve("\n".join(lines[:1] + lines[2:]).encode())  # drop 360ONE
    _run()
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM symbols WHERE in_universe=1").fetchone()[0] == 499
        assert c.execute("SELECT in_universe FROM symbols WHERE symbol='360ONE'").fetchone()[0] == 0
