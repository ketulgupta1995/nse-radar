import json
import sqlite3

import pytest

from app import db

NEW = {"signals", "signal_outcomes", "signal_days"}


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _insert(conn, screen_id: int = 1) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO signals(source, screen_id, symbol, as_of, planned_entry, atr14,"
        " planned_stop, planned_target, exit_config, score_weights, app_version, bars_as_of, created_at)"
        " VALUES ('screen', ?, 'ABC', '2026-01-02', 100, 2, 96, 108, '{}', '{}', 'x', '2026-01-02', 'now')",
        (screen_id,),
    )
    return cur.rowcount


def test_fresh_init():
    db.init_db()
    with db.tx() as conn:
        assert NEW <= _tables(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        v = conn.execute("SELECT value FROM settings WHERE key='signal_target_atr_multiple'").fetchone()[0]
        assert json.loads(v) == 4.0


def test_upgrade_from_v1_keeps_data():
    db.init_db()
    with db.tx() as conn:
        conn.execute("INSERT INTO screens(name, rule, created_at, updated_at) VALUES ('s','{}','t','t')")
        before = conn.execute("SELECT COUNT(*) FROM screens").fetchone()[0]
        conn.execute("DROP TABLE signal_outcomes")
        conn.execute("DROP TABLE signal_days")
        conn.execute("DROP TABLE signals")
    conn = db.connect()
    conn.execute("PRAGMA user_version=1")
    conn.close()
    db.init_db()
    with db.tx() as conn:
        assert NEW <= _tables(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM screens").fetchone()[0] == before
        assert conn.execute("SELECT 1 FROM screens WHERE name='s'").fetchone()


def test_append_only():
    db.init_db()
    with db.tx() as conn:
        assert _insert(conn) == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE signals SET symbol='Z'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM signals")


def test_duplicate_ignored():
    db.init_db()
    with db.tx() as conn:
        assert _insert(conn) == 1
        assert _insert(conn) == 0


def test_screen_delete_keeps_signals():
    db.init_db()
    with db.tx() as conn:
        sid = conn.execute(
            "INSERT INTO screens(name, rule, created_at, updated_at) VALUES ('s','{}','t','t')"
        ).lastrowid
        _insert(conn, sid)
        conn.execute("DELETE FROM screens WHERE id=?", (sid,))
        assert conn.execute("SELECT COUNT(*) FROM signals WHERE screen_id=?", (sid,)).fetchone()[0] == 1


def test_setting_validation(client):
    assert client.put("/api/settings", json={"signal_target_atr_multiple": 25}).status_code == 400
    r = client.put("/api/settings", json={"signal_target_atr_multiple": 6})
    assert r.status_code == 200 and r.json()["signal_target_atr_multiple"] == 6
