from datetime import datetime
from pathlib import Path

import pytest

from app import db, timeutil
from app.sources import http
from app.sources.adapters.rss import Rss
from app.sources.base import NewsItem, SourceError, SourceRefused
from app.sources.parsers.rss import parse_feed
from app.sources.store import save_news

SAMPLE = (Path(__file__).parent / "fixtures/sources/rss/sample.xml").read_bytes()


def test_parse_feed_on_fixture(monkeypatch):
    monkeypatch.setattr(timeutil, "now", lambda: datetime.fromisoformat("2026-11-09T20:00:00+05:30"))
    items = parse_feed(SAMPLE, "Sample")
    urls = [f"https://example.test/news/{n}" for n in (1, 2, 3)]
    assert [i.url for i in items] == urls  # the blank-title item is skipped
    first = items[0]
    assert first.feed == "Sample" and first.ts == "2026-11-09T18:41:00+05:30"
    assert first.summary == "Tata Consultancy Services announced a multi-year contract. Shares rose."
    assert items[1].ts == "2026-11-09T21:15:00+05:30"  # GMT converted to IST
    assert items[2].ts == "2026-11-09T20:00:00+05:30"  # no date: fetch time
    assert all(isinstance(i, NewsItem) for i in items)


def test_garbage_feed_gives_nothing():
    assert parse_feed(b"not a feed at all", "x") == []


def _serve(routes):
    def fake(url, params, headers):
        status, body = routes.get(url, (404, b""))
        return status, body

    http.set_transport(fake)


@pytest.fixture(autouse=True)
def _reset_transport():
    yield
    http.set_transport(None)


def test_one_failing_feed_does_not_stop_the_others(client):
    with db.tx() as c:
        db.set_setting("rss_feeds", [{"name": "Good", "url": "https://a.test/f"},
                                     {"name": "Dead", "url": "https://b.test/f"},
                                     {"name": "Broken", "url": "https://c.test/f"}], c)  # fmt: skip
    _serve({"https://a.test/f": (200, SAMPLE), "https://c.test/f": (200, b"<html>oops</html>")})
    items = Rss().news()
    assert len(items) == 3 and {i.feed for i in items} == {"Good"}


def test_every_feed_failing_raises(client):
    with db.tx() as c:
        db.set_setting("rss_feeds", [{"name": "A", "url": "https://a.test/f"},
                                     {"name": "B", "url": "https://b.test/f"}], c)  # fmt: skip
    _serve({})
    with pytest.raises(SourceError):
        Rss().news()
    _serve({"https://a.test/f": (403, b""), "https://b.test/f": (403, b"")})
    with pytest.raises(SourceRefused):
        Rss().news()


def test_store_links_symbols_and_api_filters(client):
    with db.tx() as c:
        ins = "INSERT INTO symbols(symbol, name, in_universe) VALUES (?,?,1)"
        c.execute(ins, ("TCS", "Tata Consultancy Services Limited"))
        c.execute(ins, ("RELIANCE", "Reliance Industries Limited"))
        items = parse_feed(SAMPLE, "Sample")
        save_news("rss", items, c)
        save_news("rss", items, c)  # rerun: no duplicates
        assert c.execute("SELECT COUNT(*) FROM news_items").fetchone()[0] == 3
    tcs = client.get("/api/news/items?symbol=tcs").json()
    assert [n["title"] for n in tcs] == ["TCS wins a large cloud deal in Europe"]
    assert tcs[0]["symbols"] == ["TCS"]
    allitems = client.get("/api/news/items").json()
    assert len(allitems) == 3 and allitems[0]["ts"] >= allitems[-1]["ts"]
    by_sym = {n["url"]: n["symbols"] for n in allitems}
    assert by_sym["https://example.test/news/3"] == ["RELIANCE"]
    assert by_sym["https://example.test/news/2"] == []
    assert len(client.get("/api/news/items?limit=1").json()) == 1


def test_default_feeds_have_no_dead_entry():
    names = [f["name"] for f in db.DEFAULT_SETTINGS["rss_feeds"]]
    assert names == ["ET Markets", "Business Standard"]
