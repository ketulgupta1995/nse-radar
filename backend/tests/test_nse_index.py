from datetime import date, datetime
from pathlib import Path

import pytest

from app import config, timeutil
from app.sources import http
from app.sources.adapters.nse_archives import NseArchives
from app.sources.base import SourceRefused
from app.sources.parsers.nse_lists import index_close_url, parse_index_close

FX = Path(__file__).parent / "fixtures/sources/nse_archives/ind_close_all_06112026.csv"


def test_url():
    assert index_close_url(date(2026, 11, 6)).endswith("/indices/ind_close_all_06112026.csv")


def test_parse_fixture():
    data = FX.read_bytes()
    assert parse_index_close(data, "NIFTY 500") == 23456.95
    assert parse_index_close(data, "Nifty 50") is not None
    assert parse_index_close(data, "No Such Index") is None


def test_dash_value_is_none():
    csv = b"Index Name,Closing Index Value\nNifty 500,-\n"
    assert parse_index_close(csv, "Nifty 500") is None


def test_index_bars_skips_404_days(monkeypatch):
    monkeypatch.setattr(timeutil, "now", lambda: datetime(2026, 11, 9, 20, 0, tzinfo=config.TZ))
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    data = FX.read_bytes()
    http.set_transport(lambda url, p, h: (200, data) if "06112026" in url else (404, b""))
    try:
        bars = NseArchives().index_bars("NIFTY 500", date(2026, 11, 2))
    finally:
        http.set_transport(None)
    assert [(b.date, b.close) for b in bars] == [("2026-11-06", 23456.95)]


def test_index_bars_refusal_propagates(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    http.set_transport(lambda url, p, h: (403, b""))
    try:
        with pytest.raises(SourceRefused):
            NseArchives().index_bars("NIFTY 500", date(2026, 11, 2))
    finally:
        http.set_transport(None)
