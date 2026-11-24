from datetime import date, datetime, time, timedelta

import pytest

from app import config, db, timeutil
from app.jobs import registry as jobs_registry
from app.jobs import runner
from app.sources import jobs as sj
from app.sources import registry, store
from app.sources.base import (
    Announcement,
    Bar,
    BaseSource,
    CapabilitySpec,
    JobVariant,
    NewsItem,
    NotFound,
    SourceError,
    SourceRefused,
)

NOW = datetime(2026, 11, 9, 20, 0, tzinfo=config.TZ)  # a Monday evening
TODAY = NOW.date()
CALLS: dict[str, list] = {"bars": [], "ann": []}
BEHAVIOUR: dict[str, object] = {}  # key -> exception to raise


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class FakeSym(BaseSource):
    name, label, description, homepage = "fakesym", "Fake symbols", "fake by-symbol source", "h"
    capabilities = (
        CapabilitySpec("bars", "by_symbol", (JobVariant(title="all", max_items=2),)),
        CapabilitySpec(
            "announcements", "by_symbol", (JobVariant(suffix="watch", scope="watch", params={"days": 7}),)
        ),
        CapabilitySpec("actions", "by_symbol", (JobVariant(),)),
    )

    def bars_for_symbol(self, symbol, start, end):
        CALLS["bars"].append((symbol, start, end))
        exc = BEHAVIOUR.get(symbol)
        if exc:
            raise exc
        return [Bar(symbol, "2026-11-06", 1, 2, 1, 2)]

    def announcements(self, symbol, since):
        CALLS["ann"].append((symbol, since))
        return [Announcement(symbol, "2026-11-06T10:00:00", "Board Meeting")]

    def actions(self, symbol):
        return []


class FakeDate(BaseSource):
    name, label, description, homepage = "fakedate", "Fake dates", "fake by-date source", "h"
    capabilities = (
        CapabilitySpec(
            "bars",
            "by_date",
            (
                JobVariant(suffix="daily", title="daily", params={"recent_days": 30, "not_before": "18:30"}),
                JobVariant(suffix="backfill", max_items=5, params={"newest_first": True}),
            ),
            history_start="2026-10-01",
        ),
    )

    def bars_for_date(self, d):
        CALLS["bars"].append(d.isoformat())
        if d.isoformat() in BEHAVIOUR:
            raise BEHAVIOUR[d.isoformat()]
        return [Bar("AAA", d.isoformat(), 1, 2, 1, 2)]


class FakeSecret(BaseSource):
    name, label, description, homepage = "fakesec", "Fake secret", "needs a key", "h"
    secrets = ("API_KEY",)
    capabilities = (CapabilitySpec("news", "whole", (JobVariant(),)),)

    def news(self):
        return [NewsItem("f", "2026-11-09T10:00:00", "t", "http://x/1")]


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init_db()
    registry.clear()
    saved = dict(jobs_registry._JOBS)
    jobs_registry._JOBS.clear()
    CALLS["bars"].clear()
    CALLS["ann"].clear()
    BEHAVIOUR.clear()
    monkeypatch.setattr(timeutil, "now", lambda: NOW)
    for cls in (FakeSym, FakeDate, FakeSecret):
        registry.register(cls())
    sj.register_source_jobs()
    yield
    registry.clear()
    jobs_registry._JOBS.clear()
    jobs_registry._JOBS.update(saved)


def seed_universe(*symbols):
    with db.tx() as c:
        for s in symbols:
            c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES (?,?,1)", (s, s))


def run(job, **params):
    run_id = runner.enqueue(job, params=params)
    assert runner.run_one() == run_id
    with db.tx() as c:
        r = dict(c.execute("SELECT * FROM job_runs WHERE id=?", (run_id,)).fetchone())
        rows = c.execute("SELECT * FROM job_items WHERE run_id=?", (run_id,))
        r["items"] = {i["key"]: dict(i) for i in rows}
    return r


def fetch_row(source, cap, key):
    with db.tx() as c:
        row = c.execute(
            "SELECT * FROM source_fetch WHERE source=? AND capability=? AND key=?", (source, cap, key)
        ).fetchone()
    return dict(row) if row else None


# ---- registration ----


def test_job_names_titles_and_metadata():
    j = jobs_registry.get("bars.fakesym")
    assert j.title == "Fake symbols: daily prices (all)"
    assert (j.group, j.stage, j.lane) == ("source:fakesym", 1, "background")
    assert j.followups == ("event_factors", "price_checks", "screens_run")
    assert jobs_registry.get("announcements.fakesym.watch").followups == ("alerts_scan",)
    assert jobs_registry.get("announcements.fakesym.watch").stage == 3
    assert jobs_registry.get("actions.fakesym").stage == 2
    assert jobs_registry.get("news.fakesec").followups == ("alerts_scan",)
    daily, backfill = jobs_registry.get("bars.fakedate.daily"), jobs_registry.get("bars.fakedate.backfill")
    assert daily.stage == 1 and backfill.stage == 7
    assert daily.title == "Fake dates: daily prices (daily)"
    assert backfill.title == "Fake dates: daily prices"


def test_register_is_idempotent():
    n = len(jobs_registry.all_jobs())
    sj.register_source_jobs()
    assert len(jobs_registry.all_jobs()) == n


# ---- pure selection ----


def test_symbol_keys_ordering_age_cap_override():
    f = {
        "OLD": ("ok", iso(NOW - timedelta(hours=50))),
        "NEW": ("ok", iso(NOW - timedelta(hours=1))),
        "BAD": ("failed", iso(NOW - timedelta(hours=2))),
        "GONE": ("not_found", iso(NOW - timedelta(hours=3))),
        "OLDER": ("ok", iso(NOW - timedelta(hours=90))),
    }
    syms = ["NEW", "OLD", "BAD", "GONE", "FRESH1", "OLDER", "FRESH2"]
    got = sj.select_symbol_keys(syms, f, NOW, 20, 100)
    assert got == ["FRESH1", "FRESH2", "OLDER", "OLD", "BAD"]
    assert sj.select_symbol_keys(syms, f, NOW, 20, 3) == ["FRESH1", "FRESH2", "OLDER"]
    assert sj.select_symbol_keys(syms, f, NOW, 20, 3, override=["NEW"]) == ["NEW"]


def d(s):
    return date.fromisoformat(s)


def test_recent_days_not_before_and_gap_catchup():
    # Monday 2026-11-09. Everything up to Fri 10-23 done; 12-day gap since.
    fetched = {x: ("ok", NOW) for x in sj.weekdays(d("2026-09-01"), d("2026-10-23"))}
    p = {"recent_days": 30, "not_before": "18:30"}
    got = sj.select_date_keys(d("2010-01-01"), TODAY, time(20, 0), p, fetched)
    assert got == sj.weekdays(d("2026-10-26"), d("2026-11-09")) and len(got) == 11
    early = sj.select_date_keys(d("2010-01-01"), TODAY, time(9, 0), p, fetched)
    assert early[-1] == d("2026-11-06") and d("2026-11-09") not in early


def test_recent_days_skips_not_found_but_retries_failed():
    fetched = {d("2026-11-04"): ("not_found", NOW), d("2026-11-05"): ("failed", NOW)}
    p = {"recent_days": 5, "not_before": "18:30"}
    got = sj.select_date_keys(d("2010-01-01"), TODAY, time(20, 0), p, fetched)
    assert got == [d("2026-11-03"), d("2026-11-05"), d("2026-11-06"), d("2026-11-09")]


def test_weekends_backfill_includes_saturday_and_skips_not_found():
    fetched = {d("2026-11-01"): ("not_found", NOW)}
    got = sj.select_date_keys(d("2026-10-30"), TODAY, time(20, 0), {"weekends": True}, fetched)
    want = ["2026-10-30", "2026-10-31", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
            "2026-11-06", "2026-11-07", "2026-11-08"]  # fmt: skip
    assert got == [d(x) for x in want]
    plain = sj.select_date_keys(d("2026-10-30"), TODAY, time(20, 0), {}, fetched)
    assert plain == sj.weekdays(d("2026-10-30"), d("2026-11-08"))


def test_weekends_recent_days_adds_weekend_inside_window():
    wed = d("2026-11-11")
    p = {"recent_days": 5, "not_before": "18:30", "weekends": True}
    got = sj.select_date_keys(d("2010-01-01"), wed, time(20, 0), p, {d("2026-11-08"): ("not_found", NOW)})
    assert got == [d("2026-11-05"), d("2026-11-06"), d("2026-11-07"), d("2026-11-09"), d("2026-11-10"), wed]


def test_backfill_newest_first_failed_after_a_day():
    fetched = {
        d("2026-11-06"): ("not_found", NOW),
        d("2026-11-05"): ("failed", NOW - timedelta(hours=3)),
        d("2026-11-04"): ("failed", NOW - timedelta(days=2)),
        d("2026-11-03"): ("ok", NOW),
    }
    got = sj.select_date_keys(d("2026-10-30"), TODAY, time(20, 0), {"newest_first": True}, fetched, 4)
    assert got[0] == d("2026-11-04") and d("2026-11-05") not in got and d("2026-11-06") not in got
    assert d("2026-11-03") not in got and TODAY not in got
    assert got == [d("2026-11-04"), d("2026-11-02"), d("2026-10-30")]


def test_announcement_since():
    assert sj.announcement_since(NOW - timedelta(days=10), TODAY, 7) == TODAY - timedelta(days=11)
    assert sj.announcement_since(None, TODAY, 7) == TODAY - timedelta(days=7)
    assert sj.announcement_since(NOW - timedelta(days=60), TODAY, 7) == TODAY - timedelta(days=30)


# ---- running ----


def test_by_symbol_run_stores_and_resumes():
    seed_universe("AAA", "BBB", "CCC")
    r = run("bars.fakesym")
    assert r["status"] == "done" and r["total"] == 2 and r["ok"] == 2  # max_items=2
    assert fetch_row("fakesym", "bars", "AAA")["status"] == "ok"
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 2
        assert c.execute("SELECT last_ok_at FROM source_state WHERE source='fakesym'").fetchone()[0]
    r2 = run("bars.fakesym")  # resumes with the unfetched one
    assert r2["total"] == 1 and list(r2["items"]) == ["CCC"]
    # start = HISTORY_START first time; last stored (2026-11-06) - 5 days on a later fetch
    assert CALLS["bars"][0][1] == config.HISTORY_START
    with db.tx() as c:
        c.execute("DELETE FROM source_fetch")
    run("bars.fakesym")
    assert CALLS["bars"][-1][1] == d("2026-11-01")


def test_not_found_is_skipped():
    seed_universe("AAA")
    BEHAVIOUR["AAA"] = NotFound("no such symbol")
    r = run("bars.fakesym")
    assert r["items"]["AAA"]["status"] == "skipped" and r["skipped"] == 1
    assert fetch_row("fakesym", "bars", "AAA")["status"] == "not_found"


def test_source_error_fails_item_only():
    seed_universe("AAA", "BBB")
    BEHAVIOUR["AAA"] = SourceError("parse failure")
    r = run("bars.fakesym")
    assert r["status"] == "done" and r["failed"] == 1 and r["ok"] == 1
    assert fetch_row("fakesym", "bars", "AAA")["status"] == "failed"
    with db.tx() as c:
        err = c.execute("SELECT last_error FROM source_state WHERE source='fakesym'").fetchone()[0]
    assert "parse failure" in err


def test_refused_pauses_source_and_alerts_once():
    seed_universe("AAA", "BBB")
    BEHAVIOUR["AAA"] = SourceRefused("HTTP 403")
    r = run("bars.fakesym")
    assert "refused" in r["message"] and "HTTP 403" in r["message"]
    assert "BBB" not in r["items"]
    assert registry.is_enabled("fakesym") is False
    with db.tx() as c:
        reason = c.execute("SELECT paused_reason FROM source_state WHERE source='fakesym'").fetchone()[0]
        alerts = c.execute("SELECT * FROM alerts WHERE kind='job_refused'").fetchall()
    assert "refused" in reason and len(alerts) == 1 and alerts[0]["severity"] == "warn"
    again = run("bars.fakesym")
    assert again["message"] == "source disabled"


def test_missing_secret_fails_run():
    r = run("news.fakesec")
    assert r["status"] == "failed" and "missing credentials: API_KEY" in r["message"]
    from app.sources import secrets

    secrets.set("fakesec", "API_KEY", "x")
    r = run("news.fakesec")
    assert r["status"] == "done" and r["ok"] == 1
    assert fetch_row("fakesec", "news", "all")["status"] == "ok"


def test_by_date_daily_and_backfill():
    r = run("bars.fakedate.daily")  # last 30 weekdays up to today (20:00 is after 18:30)
    assert r["status"] == "done" and r["total"] == 30 and r["ok"] == 30
    assert TODAY.isoformat() in r["items"]


def test_backfill_newest_first_capped():
    run("bars.fakedate.backfill")
    assert CALLS["bars"] == ["2026-11-06", "2026-11-05", "2026-11-04", "2026-11-03", "2026-11-02"]


def test_by_date_not_found_never_retried():
    BEHAVIOUR["2026-11-06"] = NotFound("holiday")
    run("bars.fakedate.daily")
    assert fetch_row("fakedate", "bars", "2026-11-06")["status"] == "not_found"
    again = run("bars.fakedate.daily")
    assert "2026-11-06" not in again["items"]


def test_announcement_since_from_last_ok():
    seed_universe("AAA")
    with db.tx() as c:
        c.execute("INSERT INTO watchlist(symbol, added_at) VALUES ('AAA', ?)", (iso(NOW),))
        c.execute(
            "INSERT INTO source_fetch(source, capability, key, status, fetched_at, rows) "
            "VALUES ('fakesym','announcements','AAA','ok',?,1)",
            (iso(NOW - timedelta(days=10)),),
        )
    run("announcements.fakesym.watch")
    assert CALLS["ann"] == [("AAA", TODAY - timedelta(days=11))]


def test_retry_keys_override():
    seed_universe("AAA", "BBB", "CCC")
    r = run("bars.fakesym", keys=["CCC"])
    assert list(r["items"]) == ["CCC"]


def test_followups_only_when_rows_stored():
    for name in ("event_factors", "price_checks", "screens_run"):
        jobs_registry.register(
            jobs_registry.JobDef(name, name, "stub", lambda ctx: None, {"kind": "manual"})
        )

    def queued():
        with db.tx() as c:
            return [r["job"] for r in c.execute("SELECT job FROM job_runs WHERE trigger='system'")]

    seed_universe("AAA")
    BEHAVIOUR["AAA"] = NotFound("none")
    run("bars.fakesym")
    assert queued() == []  # nothing stored -> no follow-ups
    BEHAVIOUR.clear()
    with db.tx() as c:
        c.execute("DELETE FROM source_fetch")
    run("bars.fakesym")
    assert sorted(queued()) == ["event_factors", "price_checks", "screens_run"]


# ---- re-download after a recent split/bonus ----


class FakeAdj(FakeSym):
    name, label = "fakeadj", "Fake adjusted"
    capabilities = (CapabilitySpec("bars", "by_symbol", (JobVariant(),), adjusted=True),)


def _seed_bars_and_action(source: str, ex_date: str | None):
    with db.tx() as c:
        store.save_bars(source, [Bar("AAA", "2026-11-06", None, None, None, 2)], c)
        if ex_date:
            c.execute(
                "INSERT INTO corp_actions(source, symbol, ex_date, subject, kind, factor) "
                "VALUES ('other', 'AAA', ?, 'Bonus', 'bonus', 0.5)",
                (ex_date,),
            )


def _start_used(source: str):
    CALLS["bars"].clear()
    sj._fetch(source, "bars", "AAA", JobVariant())
    return CALLS["bars"][0][1]


def test_recent_bonus_redownloads_history_for_adjusted_source():
    registry.register(FakeAdj())
    _seed_bars_and_action("fakeadj", (NOW.date() - timedelta(days=10)).isoformat())
    assert _start_used("fakeadj") == config.HISTORY_START


def test_old_bonus_keeps_incremental_start():
    registry.register(FakeAdj())
    _seed_bars_and_action("fakeadj", (NOW.date() - timedelta(days=100)).isoformat())
    assert _start_used("fakeadj") == d("2026-11-01")


def test_unadjusted_source_ignores_recent_bonus():
    _seed_bars_and_action("fakesym", (NOW.date() - timedelta(days=10)).isoformat())
    assert _start_used("fakesym") == d("2026-11-01")
