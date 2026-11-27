"""Round trips to Turso per job on the Actions replica (fake libsql from test_dbdriver_replica).

A read after a held write sends the rest of a lazy transaction to Turso statement by statement
(docs/CLOUD_SPIKE.md, "First drain"). These pin the jobs that used to do that on every item."""

import importlib
import sys
import types

import pytest

import tests.test_source_jobs as sj_tests
from app.sources.base import Action, CapabilitySpec, JobVariant
from tests.test_dbdriver_replica import FakeReplica

N = 40
SYMS = [f"S{i:03d}" for i in range(N)]


@pytest.fixture
def remote(tmp_path, monkeypatch):
    stats = {"remote": 0, "scripts": 0, "syncs": 0}

    def connect(database, sync_url=None, auth_token=None, isolation_level="DEFERRED"):
        return FakeReplica(database, stats)

    monkeypatch.setitem(sys.modules, "libsql", types.SimpleNamespace(connect=connect))
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test-db.example")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("STOCK_REPLICA_PATH", str(tmp_path / "replica.db"))
    import app.config

    importlib.reload(app.config)
    from app import db, timeutil
    from app.jobs import registry as jobs_registry
    from app.sources import jobs as sj
    from app.sources import registry

    class Src(sj_tests.FakeSym):
        capabilities = (CapabilitySpec("bars", "by_symbol", (JobVariant(max_items=N),)),)

    db.init_db()
    registry.clear()
    saved = dict(jobs_registry._JOBS)
    jobs_registry._JOBS.clear()
    monkeypatch.setattr(timeutil, "now", lambda: sj_tests.NOW)
    registry.register(Src())
    sj.register_source_jobs()
    sj_tests.seed_universe(*SYMS)
    sj_tests.run("bars.fakesym")  # every symbol now has bars and a sym_id
    stats["remote"] = 0
    yield stats
    registry.clear()
    jobs_registry._JOBS.clear()
    jobs_registry._JOBS.update(saved)


def test_saving_bars_for_known_symbols_stays_batched(remote):
    r = sj_tests.run("bars.fakesym", keys=SYMS)
    assert r["total"] == N and r["ok"] == N
    # per key: one batch for the save, one for ctx.item (was 10 when the id lookups read after writing)
    assert remote["remote"] <= 3 * N


def test_event_factors_refresh_is_one_batch(remote):
    from app import db
    from app.analytics import events
    from app.sources.store import save_actions

    with db.tx() as c:
        save_actions("fakesym", [Action(s, "2026-11-06", "d", "demerger", None) for s in SYMS], c)
    remote["remote"] = 0
    with db.tx() as c:
        assert events.refresh_event_factors(c) == N
    assert remote["remote"] == 1  # was ~11 per symbol: deletes first, then every read went remote
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM event_factors").fetchone()[0] == N
