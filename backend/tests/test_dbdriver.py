"""N002: the Turso driver wrapper, tested against a fake libsql built on sqlite3 (no network)."""

import importlib
import sqlite3
import sys
import types

import pytest

from app import dbdriver


class FakeLibsqlError(ValueError):
    pass


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


def _hrana(e: sqlite3.Error) -> FakeLibsqlError:
    code = "SQLITE_CONSTRAINT" if isinstance(e, sqlite3.IntegrityError) else "SQLITE_UNKNOWN"
    return FakeLibsqlError(f"Hrana: `api error: SQLite error: {e}` code: {code}")


class FakeConn:
    """Plain tuples as rows, its own exception class: like libsql (docs/CLOUD_SPIKE.md)."""

    def __init__(self, path: str, log: list) -> None:
        # autocommit=True: executescript must not COMMIT an open transaction (sqlite3's legacy mode does)
        self._c = sqlite3.connect(path, autocommit=True)
        self.log = log
        self.synced = 0

    def execute(self, sql, params=()):
        self.log.append(("execute", sql, params))
        try:
            return FakeCursor(self._c.execute(sql, params))
        except sqlite3.Error as e:
            raise _hrana(e) from None

    def executescript(self, script):
        self.log.append(("executescript", script, None))
        try:
            self._c.executescript(script)
        except sqlite3.Error as e:
            raise _hrana(e) from None

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def sync(self):
        self.synced += 1

    def close(self):
        self._c.close()


@pytest.fixture
def fake_libsql(tmp_path, monkeypatch):
    calls: list = []
    log: list = []
    conns: list[FakeConn] = []

    def connect(database, sync_url=None, auth_token=None, isolation_level="DEFERRED"):
        calls.append({"database": database, "sync_url": sync_url, "auth_token": auth_token,
                      "isolation_level": isolation_level})
        path = database if sync_url else str(tmp_path / "remote.db")
        conn = FakeConn(path, log)
        conns.append(conn)
        return conn

    mod = types.SimpleNamespace(connect=connect, calls=calls, log=log, conns=conns)
    monkeypatch.setitem(sys.modules, "libsql", mod)
    return mod


def _use_turso(monkeypatch, replica: str = "", runtime: str = ""):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test-db.example")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "tok")
    if replica:
        monkeypatch.setenv("STOCK_REPLICA_PATH", replica)
    if runtime:
        monkeypatch.setenv("STOCK_RUNTIME", runtime)
    import app.config

    importlib.reload(app.config)


@pytest.fixture
def tconn(fake_libsql, monkeypatch):
    _use_turso(monkeypatch)
    conn = dbdriver.connect_turso()
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, Name TEXT UNIQUE, v REAL, b BLOB)")
    yield conn
    conn.close()


def test_rows_behave_like_sqlite_rows(tconn):
    tconn.execute("INSERT INTO t(Name, v) VALUES (?, ?)", ("a", 1.5))
    row = tconn.execute("SELECT id, Name, v FROM t").fetchone()
    assert row["Name"] == "a" and row["name"] == "a" and row[0] == 1 and row[2] == 1.5
    assert row.keys() == ["id", "Name", "v"]
    assert dict(row) == {"id": 1, "Name": "a", "v": 1.5}
    assert tuple(row) == (1, "a", 1.5)
    with pytest.raises(IndexError):
        row["missing"]
    assert [r["Name"] for r in tconn.execute("SELECT Name FROM t")] == ["a"]
    assert tconn.execute("SELECT * FROM t WHERE Name='zz'").fetchone() is None
    assert tconn.execute("SELECT Name FROM t").description[0][0] == "Name"


def test_lastrowid_and_rowcount(tconn):
    cur = tconn.execute("INSERT INTO t(Name) VALUES (?)", ["x"])
    assert cur.lastrowid == 1
    tconn.execute("INSERT INTO t(Name) VALUES ('y')")
    assert tconn.execute("UPDATE t SET v=2").rowcount == 2


def test_errors_map_to_sqlite3(tconn):
    tconn.execute("INSERT INTO t(Name) VALUES ('dup')")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        tconn.execute("INSERT INTO t(Name) VALUES ('dup')")
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        tconn.execute("SELECT * FROM nope")
    with pytest.raises(sqlite3.OperationalError):
        tconn.executescript("SELECT * FROM nope;")


def test_executemany_insert_is_chunked_multirow(tconn, fake_libsql, monkeypatch):
    monkeypatch.setattr(dbdriver, "MAX_PARAMS", 10)  # 2 params per row -> 5 rows per statement
    fake_libsql.log.clear()
    rows = ((f"n{i}", i) for i in range(12))
    cur = tconn.executemany("INSERT OR IGNORE INTO t(Name, v) VALUES (?, ?)", rows)
    assert cur.rowcount == 12
    inserts = [e for e in fake_libsql.log if e[0] == "execute"]
    assert len(inserts) == 3  # 5 + 5 + 2
    assert inserts[0][1].count("(?, ?)") == 5 and len(inserts[0][2]) == 10
    assert tconn.execute("SELECT count(*) FROM t").fetchone()[0] == 12
    again = tconn.executemany("INSERT OR IGNORE INTO t(Name, v) VALUES (?, ?)", [("n0", 0), ("new", 1)])
    assert again.rowcount == 1


def test_executemany_other_statements_run_as_one_script(tconn, fake_libsql):
    tconn.executemany("INSERT INTO t(Name) VALUES (?)", [("o'brien",), ("plain",), ("x",)])
    fake_libsql.log.clear()
    tconn.executemany(
        "UPDATE t SET v=?, b=? WHERE Name=?",
        [(1.25, b"\x00\xff", "o'brien"), (None, None, "plain"), (True, None, "x")],
    )
    assert [e[0] for e in fake_libsql.log] == ["executescript"]
    rows = {r["Name"]: (r["v"], r["b"]) for r in tconn.execute("SELECT Name, v, b FROM t")}
    assert rows == {"o'brien": (1.25, b"\x00\xff"), "plain": (None, None), "x": (1, None)}


def test_executemany_upsert_and_empty(tconn, fake_libsql):
    assert tconn.executemany("INSERT INTO t(Name) VALUES (?)", []).rowcount == 0
    sql = "INSERT INTO t(Name, v) VALUES (?, ?) ON CONFLICT(Name) DO UPDATE SET v=excluded.v"
    fake_libsql.log.clear()
    tconn.executemany(sql, [("a", 1), ("a", 2)])
    assert [e[0] for e in fake_libsql.log] == ["execute"]  # one multi-row upsert, not a script
    assert tconn.execute("SELECT v FROM t WHERE Name='a'").fetchone()["v"] == 2
    where = sql + " WHERE excluded.v >= t.v"
    tconn.executemany(where, [("a", 1), ("b", 5)])  # a keeps 2 (1 < 2); b inserted
    assert {r["Name"]: r["v"] for r in tconn.execute("SELECT Name, v FROM t")} == {"a": 2, "b": 5}
    fake_libsql.log.clear()
    tconn.executemany(sql.replace("excluded.v", "v + ?"), [("a", 1, 3)])  # tail with a param -> script
    assert [e[0] for e in fake_libsql.log] == ["executescript"]


def test_inline_params_skips_quotes_and_comments():
    sql = "UPDATE t SET a=?, note='what?' WHERE b=? -- why?\n AND c=? /* ? */"
    out = dbdriver.inline_params(sql, [1, "it's", None])
    assert out == "UPDATE t SET a=1, note='what?' WHERE b='it''s' -- why?\n AND c=NULL /* ? */"
    with pytest.raises(sqlite3.ProgrammingError):
        dbdriver.inline_params("SELECT ?", [])
    with pytest.raises(sqlite3.ProgrammingError):
        dbdriver.inline_params("SELECT ?", [1, 2])
    assert dbdriver.sql_literal(float("inf")) == "1e999"
    assert dbdriver.sql_literal(float("nan")) == "NULL"


def test_remote_mode_selected_by_env(fake_libsql, monkeypatch):
    _use_turso(monkeypatch)
    from app import db

    conn = db.connect()
    assert isinstance(conn, dbdriver.TursoConnection) and not conn.replica
    conn.close()
    assert fake_libsql.calls[-1] == {"database": "libsql://test-db.example", "sync_url": None,
                                     "auth_token": "tok", "isolation_level": None}
    pragmas = [e[1] for e in fake_libsql.log if e[1].upper().startswith("PRAGMA")]
    assert pragmas == ["PRAGMA foreign_keys=ON"]  # file PRAGMAs are refused by Turso
    db.sync()  # remote: no-op
    assert all(c.synced == 0 for c in fake_libsql.conns)


def test_tx_and_settings_work_through_the_wrapper(fake_libsql, monkeypatch):
    _use_turso(monkeypatch)
    from app import db

    assert db.schema_status() == "update pending"
    db.init_db()
    assert db.schema_status() == "ok"
    db.set_setting("capital_inr", 123)
    assert db.get_setting("capital_inr") == 123
    assert db.insert_alert("k", "m", dedupe_key="d1") is True
    assert db.insert_alert("k", "m", dedupe_key="d1") is False
    with pytest.raises(RuntimeError):
        with db.tx() as c:
            c.execute("UPDATE settings SET value='1' WHERE key='capital_inr'")
            raise RuntimeError("boom")
    assert db.get_setting("capital_inr") == 123  # rolled back


def test_replica_mode_uses_sync_url(fake_libsql, monkeypatch, tmp_path):
    replica = tmp_path / "rep" / "replica.db"
    _use_turso(monkeypatch, replica=str(replica))
    from app import db

    db.sync()
    assert fake_libsql.calls[-1]["database"] == str(replica)
    assert fake_libsql.calls[-1]["sync_url"] == "libsql://test-db.example"
    assert fake_libsql.conns[-1].synced == 1


def test_local_mode_never_imports_libsql(monkeypatch):
    monkeypatch.setitem(sys.modules, "libsql", None)  # any import would raise ImportError
    from app import db

    conn = db.connect()
    assert isinstance(conn, sqlite3.Connection)
    conn.close()
    db.sync()  # no-op


def test_init_db_refuses_on_vercel(monkeypatch):
    monkeypatch.setenv("STOCK_RUNTIME", "vercel")
    import app.config

    importlib.reload(app.config)
    from app import db

    with pytest.raises(RuntimeError, match="not on Vercel"):
        db.init_db()


def test_health_reports_runtime_and_schema(client):
    body = client.get("/api/health").json()
    assert body["runtime"] == "local"
    assert body["schema"] == "ok"


def test_all_caps_column_names_come_back_lower_case():
    """Turso uppercases keyword columns (key, rows, trigger, explain) in DDL it ran itself."""
    from app import dbdriver

    class Raw:
        description = (("KEY", None), ("value", None), ("ROWS", None), ("sym_id", None))

        def fetchone(self):
            return ("k", "v", 3, 7)

    row = dbdriver.Cursor(Raw()).fetchone()
    assert row.keys() == ["key", "value", "rows", "sym_id"]
    assert dict(zip(row.keys(), row, strict=True))["key"] == "k"
    assert row["KEY"] == row["key"] == "k"
