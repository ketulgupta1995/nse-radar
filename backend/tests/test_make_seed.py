import importlib.util
import json
import os
import sqlite3
from pathlib import Path

import pytest

_p = Path(__file__).resolve().parents[2] / "scripts" / "make_seed.py"
_spec = importlib.util.spec_from_file_location("make_seed", _p)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


@pytest.fixture
def source(tmp_path) -> Path:
    from app import config, db

    db.init_db()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO job_runs(id, job, trigger, status, queued_at) "
            "VALUES (1, 'bhav', 'manual', 'done', '2026-11-01T10:00:00')"
        )
        conn.execute("INSERT INTO job_items(run_id, key, status, at) VALUES (1, 'x', 'ok', '2026-11-01')")
        conn.execute("INSERT INTO job_logs(run_id, at, level, msg) VALUES (1, '2026-11-01', 'info', 'm')")
        conn.execute(
            "INSERT INTO ai_requests(kind, prompt, status, created_at) "
            "VALUES ('analyse', 'p', 'done', '2026-11-01')"
        )
        conn.execute(
            "INSERT INTO alerts(kind, message, dedupe_key, created_at) "
            "VALUES ('backup_failed', 'm', 'backup_failed:1', '2026-11-01')"
        )
        conn.execute(
            "INSERT INTO alerts(kind, message, dedupe_key, created_at) "
            "VALUES ('price_check', 'm', 'pc:1', '2026-11-01')"
        )
        conn.execute("INSERT INTO watchlist(symbol, added_at) VALUES ('TCS', '2026-11-01')")
    db.set_setting("ai_provider", "claude_cli")
    db.set_setting("backtest_workers", 6)
    db.set_setting("jobs_paused", True)
    db.set_setting("backup_keep", 7)
    src = config.DB_PATH
    c = sqlite3.connect(src)
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    return src


def _settings(conn: sqlite3.Connection) -> dict:
    return {k: json.loads(v) for k, v in conn.execute("SELECT key, value FROM settings")}


def test_make_seed_copies_and_cleans(source, tmp_path, caplog):
    before = (source.read_bytes(), os.stat(source).st_mtime_ns)
    out = tmp_path / "out" / "seed.db"
    with caplog.at_level("INFO", logger="make_seed"):
        assert mod.main(["--from", str(source), "--out", str(out)]) == 0
    assert (source.read_bytes(), os.stat(source).st_mtime_ns) == before

    conn = sqlite3.connect(out)
    for table in ("job_runs", "job_items", "job_logs", "ai_requests"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert [r[0] for r in conn.execute("SELECT kind FROM alerts")] == ["price_check"]
    assert conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 1
    s = _settings(conn)
    assert s["ai_provider"] == "copy_prompt"
    assert s["backtest_workers"] == 3
    assert s["jobs_paused"] is False
    assert "backup_keep" not in s
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    conn.close()
    assert "turso db create nse-radar --group us --from-file" in caplog.text
    assert "watchlist" in caplog.text and "MB" in caplog.text


def test_refuses_existing_out_without_force(source, tmp_path):
    out = tmp_path / "seed.db"
    out.write_bytes(b"keep me")
    assert mod.main(["--from", str(source), "--out", str(out)]) == 1
    assert out.read_bytes() == b"keep me"
    assert mod.main(["--from", str(source), "--out", str(out), "--force"]) == 0
    conn = sqlite3.connect(out)
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    conn.close()


def test_refuses_same_file(source, tmp_path):
    before = source.read_bytes()
    assert mod.main(["--from", str(source), "--out", str(source), "--force"]) == 1
    link = tmp_path / "alias.db"
    link.symlink_to(source)
    assert mod.main(["--from", str(source), "--out", str(link), "--force"]) == 1
    assert source.read_bytes() == before


def test_refuses_missing_source(tmp_path):
    assert mod.main(["--from", str(tmp_path / "nope.db"), "--out", str(tmp_path / "s.db")]) == 1
