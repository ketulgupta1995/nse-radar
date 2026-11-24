"""Lazy transactions on the embedded replica, against a fake that behaves like real libsql (2026-11-25):
reads outside a transaction are local, everything else is a round trip, and a failing `executescript`
does not raise: the batch is rolled back and `in_transaction` stays True."""

import importlib
import sqlite3
import sys
import types

import pytest

from app import dbdriver


class FakeLibsqlError(ValueError):
    pass


def _hrana(e: sqlite3.Error) -> FakeLibsqlError:
    code = "SQLITE_CONSTRAINT" if isinstance(e, sqlite3.IntegrityError) else "SQLITE_UNKNOWN"
    return FakeLibsqlError(f"Hrana: `stream error: SQLite error: {e}` code: {code}")


class FakeCursor:
    def __init__(self, cur: sqlite3.Cursor) -> None:
        self._cur = cur
        self.description = cur.description
        self.lastrowid = cur.lastrowid
        self.rowcount = cur.rowcount

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size=1):
        return self._cur.fetchmany(size)


class FakeReplica:
    def __init__(self, path: str, stats: dict) -> None:
        self._c = sqlite3.connect(path, autocommit=True)
        self._c.execute("PRAGMA foreign_keys=ON")  # Turso enforces them without being asked
        self.stats = stats
        self._stuck = False

    @property
    def in_transaction(self) -> bool:
        return self._stuck or self._c.in_transaction

    def execute(self, sql, params=()):
        if self._c.in_transaction or not dbdriver.is_read(sql):
            self.stats["remote"] += 1
        try:
            return FakeCursor(self._c.execute(sql, params))
        except sqlite3.Error as e:
            raise _hrana(e) from None

    def executescript(self, script):
        self.stats["remote"] += 1
        self.stats["scripts"] += 1
        try:
            self._c.executescript(script)
        except sqlite3.Error:
            if self._c.in_transaction:
                self._c.execute("ROLLBACK")
            self._stuck = True  # like libsql: no exception, and the flag stays set

    def sync(self):
        self.stats["syncs"] += 1

    def close(self):
        self._c.close()


@pytest.fixture
def replica(tmp_path, monkeypatch):
    stats = {"remote": 0, "scripts": 0, "syncs": 0}

    def connect(database, sync_url=None, auth_token=None, isolation_level="DEFERRED"):
        assert sync_url, "these tests only cover the embedded replica"
        return FakeReplica(database, stats)

    monkeypatch.setitem(sys.modules, "libsql", types.SimpleNamespace(connect=connect))
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test-db.example")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("STOCK_REPLICA_PATH", str(tmp_path / "replica.db"))
    import app.config

    importlib.reload(app.config)
    from app import db

    with db.read() as c:
        c.executescript(
            "CREATE TABLE p (id INTEGER PRIMARY KEY, name TEXT UNIQUE);"
            "CREATE TABLE ch (id INTEGER PRIMARY KEY, p INTEGER REFERENCES p(id) ON DELETE CASCADE);"
            "INSERT INTO p(id, name) VALUES (1, 'a');"
        )
    stats.update(remote=0, scripts=0)
    return stats


def _names():
    from app import db

    with db.read() as c:
        return [r["name"] for r in c.execute("SELECT name FROM p ORDER BY id")]


def test_read_only_transaction_never_leaves_the_runner(replica):
    from app import db

    with db.tx() as c:
        assert c.execute("SELECT name FROM p").fetchone()["name"] == "a"
    assert replica["remote"] == 0


def test_writes_go_out_in_one_batch_at_commit(replica):
    from app import db

    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM p").fetchone()[0] == 1  # local read first
        c.execute("INSERT INTO p(name) VALUES (?)", ("b",))
        c.execute("UPDATE p SET name=? WHERE id=?", ("a2", 1))
        c.executemany("INSERT INTO p(name) VALUES (?)", [("c",), ("d",)])
        c.executemany("UPDATE p SET name=name || '!' WHERE name=?", [("c",), ("d",)])
    assert replica == {"remote": 1, "scripts": 1, "syncs": 0}
    assert _names() == ["a2", "b", "c!", "d!"]


def test_asking_for_a_result_sends_the_held_writes_first(replica):
    from app import db

    with db.tx() as c:
        c.execute("INSERT INTO p(name) VALUES ('b')")
        cur = c.execute("UPDATE p SET name=name || '!' WHERE name IN ('a', 'b')")
        assert cur.rowcount == 2
        ins = c.execute("INSERT INTO p(name) VALUES ('c')")
        assert ins.lastrowid == 3
        assert c.execute("SELECT COUNT(*) FROM p WHERE name LIKE '%!'").fetchone()[0] == 2  # read-your-writes
    assert replica["scripts"] == 0
    assert _names() == ["a!", "b!", "c"]


def test_a_read_after_a_write_sees_it(replica):
    from app import db

    with db.tx() as c:
        c.execute("INSERT INTO p(name) VALUES ('b')")
        assert [r[0] for r in c.execute("SELECT name FROM p ORDER BY id")] == ["a", "b"]
    assert _names() == ["a", "b"]


def test_a_failing_batch_raises_and_applies_nothing(replica):
    from app import db

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        with db.tx() as c:
            c.execute("INSERT INTO p(name) VALUES ('b')")
            c.execute("INSERT INTO p(name) VALUES ('a')")  # duplicate: fails only at COMMIT
            c.execute("INSERT INTO p(name) VALUES ('c')")
    assert _names() == ["a"]
    with db.tx() as c:  # a fresh connection works normally afterwards
        c.execute("INSERT INTO p(name) VALUES ('z')")
    assert _names() == ["a", "z"]


def test_foreign_key_failure_in_a_batch_raises(replica):
    from app import db

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        with db.tx() as c:
            c.execute("INSERT INTO ch(p) VALUES (99)")


def test_an_exception_in_the_body_sends_nothing(replica):
    from app import db

    with pytest.raises(RuntimeError):
        with db.tx() as c:
            c.execute("INSERT INTO p(name) VALUES ('b')")
            raise RuntimeError("boom")
    assert replica["remote"] == 0
    assert _names() == ["a"]


def test_rollback_after_going_remote(replica):
    from app import db

    with pytest.raises(RuntimeError):
        with db.tx() as c:
            assert c.execute("INSERT INTO p(name) VALUES ('b')").rowcount == 1
            raise RuntimeError("boom")
    assert _names() == ["a"]


def test_batched_write_result_after_commit_is_an_error(replica):
    from app import db

    with db.tx() as c:
        cur = c.execute("INSERT INTO p(name) VALUES ('b')")
    with pytest.raises(sqlite3.ProgrammingError):
        _ = cur.rowcount


def test_executemany_outside_a_transaction_raises_on_failure(replica):
    from app import db

    conn = db.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.executemany("UPDATE p SET name=? WHERE id=?", [("q", 1), ("q", 2)])  # 2 has no row: fine
            conn.execute("INSERT INTO p(id, name) VALUES (2, 'r')")
            conn.executemany("UPDATE p SET name=? WHERE id=?", [("s", 1), ("r", 1)])  # UNIQUE on 'r'
    finally:
        conn.close()
    assert _names() == ["q", "r"]  # the failed batch is all-or-nothing


def test_big_transactions_go_remote_instead_of_one_huge_batch(replica, monkeypatch):
    from app import db

    monkeypatch.setattr(dbdriver, "MAX_BATCH_BYTES", 200)
    with db.tx() as c:
        for i in range(20):
            c.execute("INSERT INTO p(name) VALUES (?)", (f"n{i:02d}",))
    assert replica["scripts"] == 0
    assert len(_names()) == 21


def test_settings_and_job_bookkeeping_cost_one_trip_per_write_transaction(replica):
    from app import db
    from app.jobs import runner
    from app.jobs.context import JobContext

    db.init_db()
    replica.update(remote=0, scripts=0)
    assert db.get_setting("capital_inr") == 500000
    assert replica["remote"] == 0
    run_id = runner.enqueue("noop")  # reads lastrowid: goes remote, as before
    ctx = JobContext(run_id, {}, "noop")
    replica.update(remote=0, scripts=0)
    ctx.item("k1", "ok")
    ctx.item("k2", "failed", "x")
    assert replica == {"remote": 2, "scripts": 2, "syncs": replica["syncs"]}
    assert not ctx.stop_requested()
    with db.read() as c:
        row = c.execute("SELECT ok, failed, done FROM job_runs WHERE id=?", (run_id,)).fetchone()
    assert (row["ok"], row["failed"], row["done"]) == (1, 1, 2)


@pytest.mark.parametrize(
    ("sql", "read"),
    [
        ("SELECT 1", True),
        ("  -- note\n/* x */ select * from p", True),
        ("WITH a AS (SELECT 1) SELECT * FROM a", True),
        ("WITH a AS (SELECT 1) INSERT INTO p(name) SELECT 'x' FROM a", False),
        ("PRAGMA user_version", True),
        ("PRAGMA table_info(p)", False),  # unsure: treated as a write
        ("PRAGMA foreign_keys=ON", False),
        ("INSERT INTO p(name) VALUES ('SELECT')", False),
        ("UPDATE p SET name='x'", False),
        ("BEGIN IMMEDIATE", False),
    ],
)
def test_is_read(sql, read):
    assert dbdriver.is_read(sql) is read
