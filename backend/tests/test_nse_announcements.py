import json
from datetime import date
from pathlib import Path

from app import db, timeutil
from app.sources import http
from app.sources.adapters.nse_api import NseApi, parse_announcements
from app.sources.base import Announcement
from app.sources.store import save_announcements

FIX = Path(__file__).parent / "fixtures/sources/nse_api/announcements_TCS.json"
ITEMS = json.loads(FIX.read_text())


def test_parse_fixture():
    rows = parse_announcements(ITEMS, "tcs", date(2026, 10, 1))
    assert len(rows) == 5 and all(r.symbol == "TCS" for r in rows)
    assert [r.ts for r in rows] == sorted((r.ts for r in rows), reverse=True)
    newest = rows[0]
    assert newest.ts == "2026-11-09T17:12:15+05:30"
    assert newest.headline == "Analysts/Institutional Investor Meet/Con. Call Updates"
    assert newest.body and newest.body.startswith("Tata Consultancy Services Limited")
    assert newest.url and newest.url.startswith("https://nsearchives.nseindia.com/")
    assert newest.category is None  # the store categorizes


def test_headline_falls_back_to_text_and_bad_rows_are_skipped():
    items = [
        {"an_dt": "01-Nov-2026 10:00:00", "desc": "", "attchmntText": "x" * 300, "attchmntFile": ""},
        {"an_dt": "garbage", "desc": "Bad date"},
        {"an_dt": "02-Nov-2026 10:00:00", "desc": "", "attchmntText": ""},  # nothing to show
        {"an_dt": "01-Jan-2020 10:00:00", "desc": "Too old"},
        "not a dict",
    ]
    rows = parse_announcements(items, "AAA", date(2026, 10, 1))
    assert len(rows) == 1 and rows[0].headline == "x" * 120 and rows[0].url is None


def test_adapter_sends_the_date_range(monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    seen = {}

    def fake(url, params, headers):
        seen.update(params)
        return 200, FIX.read_bytes()

    http.set_transport(fake)
    try:
        rows = NseApi().announcements("TCS", date(2026, 11, 2))
    finally:
        http.set_transport(None)
    assert seen["from_date"] == "02-11-2026" and seen["to_date"] == "09-11-2026" and seen["symbol"] == "TCS"
    assert [r.ts[:10] for r in rows] == ["2026-11-09"]  # older items are dropped client-side too


def test_variants_match_the_spec():
    spec = next(s for s in NseApi.capabilities if s.capability == "announcements")
    watch, all_ = spec.jobs
    assert (watch.suffix, watch.scope, watch.min_age_hours, watch.params, watch.refresh) == (
        "watch", "watch", 1, {"days": 7}, True)  # fmt: skip
    assert watch.schedule == {"kind": "interval", "interval_min": 90}
    assert (all_.suffix, all_.scope, all_.max_items, all_.min_age_hours, all_.params) == (
        "all", "universe", 500, 20, {"days": 3})  # fmt: skip
    assert all_.schedule == {"kind": "daily", "at_time": "22:30"}


def test_store_categorizes_dedupes_and_api_hides_routine(client):
    extra = [
        Announcement("TCS", "2026-11-03T18:52:12+05:30", "Copy of Newspaper Publication", "n", None),
        Announcement("TCS", "2026-11-02T10:00:00+05:30", "Credit rating", "CRISIL credit rating done", None),
    ]
    rows = [*parse_announcements(ITEMS, "TCS", date(2026, 10, 1)), *extra]
    with db.tx() as c:
        save_announcements("nse_api", rows, c)
        save_announcements("nse_api", rows, c)  # rerun: nothing doubles
        assert c.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 7
        got = c.execute("SELECT headline, category FROM announcements")
        cats = {r["headline"]: r["category"] for r in got}
    assert cats["Copy of Newspaper Publication"] == "routine" and cats["Credit rating"] == "credit_rating"

    shown = client.get("/api/news/announcements?symbol=tcs").json()
    assert len(shown) == 6 and "Copy of Newspaper Publication" not in [a["headline"] for a in shown]
    assert shown[0]["ts"] > shown[-1]["ts"]
    allrows = client.get("/api/news/announcements?symbol=TCS&include_hidden=1").json()
    assert len(allrows) == 7
    only = client.get("/api/news/announcements?category=credit_rating").json()
    assert [a["headline"] for a in only] == ["Credit rating"]
    assert len(client.get("/api/news/announcements?limit=2").json()) == 2
    cats_api = client.get("/api/news/categories").json()
    assert any(c["category"] == "routine" and c.get("hidden") for c in cats_api)
