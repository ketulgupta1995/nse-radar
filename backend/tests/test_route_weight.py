"""Every light GET route stays light on Vercel (SPEC §17.5, N009): at most ~50 SQL statements.

The fixture DB is seeded with enough symbols, watchlist rows, positions and signals that a route
which loads one frame per symbol (or loops over the universe) blows the budget. Statements are
counted with a connection that counts every `execute`/`executemany`, plus one per connection
(Turso runs `PRAGMA foreign_keys` on connect).
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from datetime import date

import pandas as pd
import pytest

from app import config, db, timeutil
from app.analytics import frames, price_store, score
from app.sources import registry
from app.sources.base import Bar, BaseSource, CapabilitySpec, IndexBar
from app.sources.store import save_bars, save_index

BUDGET = 50
N_SYMBOLS = 60
DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=300)]
SYMS = [f"S{i:02d}" for i in range(N_SYMBOLS)]

# Every GET route (docs/CLOUD_ROUTES.md lists them all as light), as its path template plus a query.
# `{name}` parts are filled from the fixture's ids. A new GET route must be added here.
LIGHT = [
    "/api/health",
    "/api/me",
    "/api/cloud/status",
    "/api/cloud/tick",
    "/api/jobs",
    "/api/jobs/status",
    "/api/jobs/runs",
    "/api/jobs/runs/{run_id}",
    "/api/jobs/runs/{run_id}/items",
    "/api/jobs/runs/{run_id}/logs",
    "/api/sources",
    "/api/sources/priority",
    "/api/sources/coverage?capability=bars",
    "/api/sources/coverage?capability=index",
    "/api/sources/coverage?capability=fundamentals",
    "/api/sources/coverage?capability=quarters",
    "/api/symbols/search?q=S0",
    "/api/symbols/{sym}",
    "/api/prices/{sym}?indicators=sma:50,rel_strength:63",
    "/api/fundamentals/fields",
    "/api/fundamentals/{sym}",
    "/api/indicators",
    "/api/rules/ops",
    "/api/screens",
    "/api/screens/{screen_id}/results",
    "/api/shortlist",
    "/api/score/components",
    "/api/dashboard",
    "/api/watchlist",
    "/api/positions",
    "/api/positions?status=closed",
    "/api/positions/checklist/questions",
    "/api/positions/suggest?symbol=S01",
    "/api/positions/{pid}/checklists",
    "/api/journal/stats",
    "/api/alerts",
    "/api/alerts/count",
    "/api/alerts/kinds",
    "/api/news/categories",
    "/api/news/announcements",
    "/api/news/items",
    "/api/data/health",
    "/api/data/checks",
    "/api/data/unparsed-actions",
    "/api/data/event-factors",
    "/api/data/symbol-changes?symbol=S01",
    "/api/backtests",
    "/api/backtests/exits",
    "/api/backtests/{backtest_id}",
    "/api/signals",
    "/api/signals/summary",
    "/api/signals/ideas",
    "/api/settings",
    "/api/custom-indicators",
    "/api/ai/status",
    "/api/ai/tasks",
    "/api/ai/requests",
    "/api/ai/requests/{request_id}",
    "/api/ai/prompt?kind=stock_brief&symbol=S01",
]


class Counting(sqlite3.Connection):
    count = 0

    def execute(self, *a, **k):  # type: ignore[override]
        Counting.count += 1
        return super().execute(*a, **k)

    def executemany(self, *a, **k):  # type: ignore[override]
        Counting.count += 1
        return super().executemany(*a, **k)


def _counting_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10, isolation_level=None, factory=Counting)
    conn.row_factory = sqlite3.Row
    sqlite3.Connection.execute(conn, "PRAGMA busy_timeout=10000")
    Counting.count += 1  # Turso's PRAGMA foreign_keys=ON on every connect
    return conn


def _seed() -> dict:
    caps = (CapabilitySpec("bars", "by_symbol", ()), CapabilitySpec("index", "whole", ()))
    registry.register(type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d",
                                                 "homepage": "h", "capabilities": caps})())  # fmt: skip
    ids: dict = {"sym": "S01"}
    with db.tx() as c:
        c.executemany(
            "INSERT INTO symbols(symbol, name, industry, in_universe) VALUES (?,?,?,1)",
            [(s, f"Name {s}", f"Ind{i % 5}") for i, s in enumerate(SYMS)],
        )
        bars = [Bar(s, d, p := 100 + i * 0.3 + k, p + 1, p - 1, p, 1000.0)
                for k, s in enumerate(SYMS) for i, d in enumerate(DAYS)]  # fmt: skip
        save_bars("px", bars, c)
        save_index("px", [IndexBar(frames.INDEX_NAME, d, 1000.0 + i) for i, d in enumerate(DAYS)], c)
        sid = c.execute("SELECT id FROM screens ORDER BY id LIMIT 1").fetchone()["id"]
        ids["screen_id"] = sid
        c.executemany(
            "INSERT INTO screen_results(screen_id, symbol, as_of, values_json, first_seen) "
            "VALUES (?,?,?,?,?)",
            [(sid, s, DAYS[-1], "{}", "2026-11-01") for s in SYMS],
        )
        c.executemany(
            "INSERT INTO watchlist(symbol, added_at, note) VALUES (?,?,?)",
            [(s, "2026-06-01T10:00:00+05:30", None) for s in SYMS[:40]],
        )
        for s in SYMS[:30]:
            cl = c.execute(
                "INSERT INTO checklists(kind, symbol, answers, created_at) VALUES ('entry',?,?,'x')",
                (s, json.dumps({"stop": 90})),
            ).lastrowid
            ids["pid"] = c.execute(
                "INSERT INTO positions(symbol, qty, entry_date, entry_price, stop, entry_checklist_id, "
                "created_at) VALUES (?,10,'2026-06-01',100,90,?,'x')",
                (s, cl),
            ).lastrowid
        for s in SYMS[30:40]:
            c.execute(
                "INSERT INTO positions(symbol, qty, entry_date, entry_price, stop, status, exit_date, "
                "exit_price, exit_reason, created_at) VALUES (?,10,'2026-01-01',100,90,'closed',"
                "'2026-03-01',110,'target','x')",
                (s,),
            )
        for i, s in enumerate(SYMS):
            sig = c.execute(
                "INSERT INTO signals(source, screen_id, screen_name, symbol, as_of, reasons, planned_entry, "
                "atr14, planned_stop, planned_target, exit_config, score_weights, app_version, bars_as_of, "
                "created_at) VALUES ('screen',?,'scr',?,?,'[]',100,2,96,108,'{}','{}','t',?,'x')",
                (sid, s, DAYS[-20 + i % 10], DAYS[-1]),
            ).lastrowid
            c.execute(
                "INSERT INTO signal_outcomes(signal_id, status, updated_at) VALUES (?, 'open', 'x')", (sig,)
            )
        c.execute("INSERT INTO signal_days(as_of, logged, run_at) VALUES (?, 10, 'x')", (DAYS[-1],))
        for i in range(30):
            nid = c.execute(
                "INSERT INTO news_items(source, feed, ts, title, url) VALUES ('rss','f',?,?,?)",
                (f"2026-11-0{1 + i % 5}T10:00:00", f"t{i}", f"https://x/{i}"),
            ).lastrowid
            c.execute("INSERT INTO news_symbols(news_id, symbol) VALUES (?,?)", (nid, SYMS[i]))
        for i in range(30):
            c.execute(
                "INSERT INTO backtests(name, config, status, kind, created_at) "
                "VALUES (?,?,'done','explore','x')",
                (f"b{i}", json.dumps({"start": "2015-01-01", "oos_start": "2022-01-01", "entry_rule": {}})),
            )
        ids["backtest_id"] = 1
        run = c.execute(
            "INSERT INTO job_runs(job, trigger, status, queued_at) VALUES ('noop','manual','done','x')"
        ).lastrowid
        ids["run_id"] = run
        ids["request_id"] = c.execute(
            "INSERT INTO ai_requests(kind, prompt, status, created_at) VALUES ('stock_brief','p','done','x')"
        ).lastrowid
    frames.invalidate()
    assert score.save_prices() == N_SYMBOLS  # what the screens_run job leaves for the shortlist
    db.set_setting("last_visit_at", "2026-11-01T18:00:00+05:30")  # the dashboard's "since" part runs too
    return ids


def _builtin_sources() -> None:
    """Other tests clear the source registry; the source jobs still name those sources."""
    for name in sorted(sys.modules):
        if name.startswith("app.sources.adapters.") and name.rsplit(".", 1)[1] not in registry._sources:
            importlib.reload(sys.modules[name])


@pytest.fixture
def heavy_world(client, monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    _builtin_sources()  # routes see the real sources and priority lists, plus the fixture's "px"
    ids = _seed()
    monkeypatch.setattr(config, "RUNTIME", "vercel")  # price store off, light-route code paths
    frames.invalidate()
    monkeypatch.setattr(db, "connect", _counting_connect)
    yield ids
    registry._sources.pop("px", None)
    frames.invalidate()


def _measure(client, path: str) -> tuple[int, int]:
    frames.invalidate()  # a cold Vercel instance: nothing cached
    Counting.count = 0
    r = client.get(path, headers={"Authorization": "Bearer cron-test"})  # /api/cloud/tick checks it
    return r.status_code, Counting.count


def test_every_light_route_is_under_budget(heavy_world, client, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "cron-test")
    over = []
    for raw in LIGHT:
        path = raw.format(**heavy_world)
        status, n = _measure(client, path)
        assert status == 200, f"{path}: {status}"
        if n > BUDGET:
            over.append(f"{path}: {n} statements")
    assert not over, "\n".join(over)


def test_every_get_route_is_listed(client):
    paths = client.app.openapi()["paths"]  # routers are nested in app.routes; the schema lists them all
    gets = {p for p, ops in paths.items() if "get" in ops and p.startswith("/api/")}
    listed = {p.split("?")[0] for p in LIGHT}
    assert gets - listed == set(), "add these GET routes to LIGHT (and to docs/CLOUD_ROUTES.md)"
    assert listed - gets == set()


def test_price_store_is_off_on_vercel(monkeypatch):
    assert price_store.enabled()
    monkeypatch.setattr(config, "RUNTIME", "vercel")
    assert not price_store.enabled()
    with db.read() as c:
        assert price_store.ensure_valid(c) is None


def test_vercel_caches_expire(monkeypatch):
    monkeypatch.setattr(config, "RUNTIME", "vercel")
    frames.invalidate()
    calls: list[int] = []
    assert frames.memo("k", lambda: calls.append(1) or 7) == 7
    assert frames.memo("k", lambda: calls.append(1) or 8) == 7  # reused
    monkeypatch.setattr(frames, "_cleared_at", frames._cleared_at - frames.VERCEL_CACHE_TTL_S - 1)
    assert frames.memo("k", lambda: calls.append(1) or 9) == 9  # expired after the TTL
    assert len(calls) == 2
    monkeypatch.setattr(config, "RUNTIME", "local")
    assert frames.memo("k", lambda: 10) == 10  # local mode never reuses


def test_frame_cache_expires_on_vercel(heavy_world, monkeypatch):
    frames.invalidate()
    frames.load_frame("S01")
    assert len(frames._cache) == 1
    monkeypatch.setattr(frames, "_cleared_at", frames._cleared_at - frames.VERCEL_CACHE_TTL_S - 1)
    Counting.count = 0
    frames.load_frame("S02")
    assert len(frames._cache) == 1  # S01's entry was dropped with the rest
    assert Counting.count > 0


def test_closes_match_frames(heavy_world, client):
    """The batched helpers give what `load_frame` would show, splits included."""
    with db.tx() as c:
        c.execute(
            "INSERT INTO corp_actions(source, symbol, ex_date, kind, subject, factor) "
            "VALUES ('px','S03',?,'split','Split 1:2',0.5)",
            (DAYS[-50],),
        )
    registry._sources.pop("px")
    caps = (CapabilitySpec("bars", "by_symbol", (), adjusted=False),
            CapabilitySpec("actions", "by_symbol", ()), CapabilitySpec("index", "whole", ()))  # fmt: skip
    registry.register(type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d",
                                                 "homepage": "h", "capabilities": caps})())  # fmt: skip
    frames.invalidate()
    days = {"S01": DAYS[-100], "S03": DAYS[-100], "S04": None, "NOPE": DAYS[-1]}
    got = frames.closes_on(days)
    for sym, d in days.items():
        f = frames.load_frame(sym)
        want = None if f.empty else float(f[: d or DAYS[-1]]["close"].iloc[-1])
        assert got[sym] == pytest.approx(want) if want is not None else got[sym] is None, sym
    assert got["S03"] == pytest.approx(frames.load_frame("S03")[: DAYS[-100]]["close"].iloc[-1])
    assert frames.latest_closes(["s01"])["S01"] == pytest.approx(frames.load_frame("S01")["close"].iloc[-1])


REFRESH_BUDGET = 15  # N021: one transaction and one dispatch for the whole batch


def test_refresh_enqueues_in_few_statements(heavy_world, client, monkeypatch):
    from app.cloud import dispatch

    kicks: list[str] = []
    monkeypatch.setattr(dispatch, "kick", lambda reason: kicks.append(reason) or True)
    Counting.count = 0
    r = client.post("/api/jobs/refresh")
    assert r.status_code == 200 and len(r.json()["run_ids"]) >= 5
    assert Counting.count <= REFRESH_BUDGET, f"{Counting.count} statements"
    assert len(kicks) == 1  # one dispatch, not one per job
