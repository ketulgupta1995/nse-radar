import gzip
import shutil
import sqlite3
from datetime import datetime

import pytest

from app import config, db, timeutil
from app.jobs import registry
from app.jobs.context import JobContext
from app.jobs.defs import backup


@pytest.fixture
def env(monkeypatch):
    db.init_db()
    monkeypatch.setattr(timeutil, "now", lambda: datetime(2026, 11, 11, 2, 30))
    with db.tx() as c:
        c.execute(
            "INSERT INTO job_runs(job, trigger, status, queued_at) VALUES ('backup','manual','running','x')"
        )
        rid = c.execute("SELECT MAX(id) FROM job_runs").fetchone()[0]
    return JobContext(rid, {}, "backup")


def folder():
    return config.DATA_DIR / "backups"


def alerts():
    with db.tx() as c:
        return [r["kind"] for r in c.execute("SELECT kind FROM alerts")]


def test_creates_verified_compressed_copy(env, tmp_path):
    msg = backup.run(env)
    assert msg.startswith("saved stock-auto-2026-11-11.db.gz")
    f = tmp_path / "restored.db"
    with gzip.open(folder() / "stock-auto-2026-11-11.db.gz", "rb") as src:
        f.write_bytes(src.read())
    conn = sqlite3.connect(f)
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] > 0
    conn.close()
    assert not list(folder().glob("*.tmp"))
    assert not (folder() / "stock-auto-2026-11-11.db").exists()


def test_second_run_skipped(env):
    backup.run(env)
    f = folder() / "stock-auto-2026-11-11.db.gz"
    before = f.stat().st_mtime_ns
    assert backup.run(env) == "already backed up today"
    assert f.stat().st_mtime_ns == before


def test_retention_keeps_newest_seven_and_manual(env):
    folder().mkdir(exist_ok=True)
    for d in range(1, 10):  # old uncompressed and new compressed backups share the limit
        ext = ".db" if d < 5 else ".db.gz"
        (folder() / f"stock-auto-2026-11-0{d}{ext}").write_text("x")
    (folder() / "stock-2026-11-10-pre-datafix.db").write_text("m")
    (folder() / "stock-2026-11-10-pre-datafix.db-wal").write_text("w")
    backup.run(env)
    autos = sorted(p.name for p in folder().glob("stock-auto-*"))
    assert autos == (
        ["stock-auto-2026-11-04.db"]
        + [f"stock-auto-2026-11-0{d}.db.gz" for d in range(5, 10)]
        + ["stock-auto-2026-11-11.db.gz"]
    )
    assert (folder() / "stock-2026-11-10-pre-datafix.db").exists()
    assert (folder() / "stock-2026-11-10-pre-datafix.db-wal").exists()


def test_old_uncompressed_backup_today_counts(env):
    folder().mkdir(exist_ok=True)
    (folder() / "stock-auto-2026-11-11.db").write_text("x")
    assert backup.run(env) == "already backed up today"


def test_low_disk_space_fails_with_alert(env, monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 99, 1))
    with pytest.raises(RuntimeError, match="not enough disk space"):
        backup.run(env)
    assert not list(folder().glob("stock-auto-*"))
    assert alerts() == ["backup_failed"]


def test_registered():
    job = registry.get("backup")
    assert job.stage == 9
    assert job.default_schedule == {"kind": "daily", "at_time": "02:30"}


# --- actions mode (SPEC §17.8): weekly, from the replica, one file kept on the runner ---


@pytest.fixture
def cloud(env, monkeypatch):
    synced = []
    monkeypatch.setattr(config, "RUNTIME", "actions")
    monkeypatch.setattr(config, "REPLICA_PATH", str(config.DB_PATH))  # the tmp DB stands in for the replica
    monkeypatch.setattr(db, "sync", lambda: synced.append(1))
    return env, synced


def finish(msg):
    """Marks the running backup as done with `msg` and starts a new run."""
    with db.tx() as c:
        c.execute("UPDATE job_runs SET status='done', message=? WHERE status='running'", (msg,))
        c.execute(
            "INSERT INTO job_runs(job, trigger, status, queued_at) VALUES ('backup','manual','running','x')"
        )
        rid = c.execute("SELECT MAX(id) FROM job_runs").fetchone()[0]
    return JobContext(rid, {}, "backup")


def test_cloud_writes_named_gzip_after_sync(cloud, tmp_path):
    ctx, synced = cloud
    msg = backup.run(ctx)
    assert msg.startswith("saved nse-radar-2026-11-11.db.gz")
    assert synced == [1]
    restored = tmp_path / "restored.db"
    with gzip.open(folder() / "nse-radar-2026-11-11.db.gz", "rb") as src:
        restored.write_bytes(src.read())
    conn = sqlite3.connect(restored)
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] > 0
    conn.close()
    assert not list(folder().glob("stock-auto-*"))
    assert not list(folder().glob("*.tmp"))


def test_cloud_skips_within_a_week(cloud):
    _, synced = cloud
    ctx = finish("saved nse-radar-2026-11-06.db.gz (178 MB)")
    assert backup.run(ctx).startswith("last backup 5 days ago")
    assert synced == []
    assert not list(folder().glob("nse-radar-*"))


def test_cloud_runs_after_seven_days(cloud):
    ctx = finish("saved nse-radar-2026-11-04.db.gz (178 MB)")
    assert backup.run(ctx).startswith("saved nse-radar-2026-11-11.db.gz")


def test_cloud_every_days_setting(cloud):
    db.set_setting("backup_every_days", 3)
    ctx = finish("saved nse-radar-2026-11-08.db.gz (178 MB)")
    assert backup.run(ctx).startswith("saved nse-radar-2026-11-11.db.gz")


def test_cloud_keeps_one_file(cloud):
    folder().mkdir(exist_ok=True)
    (folder() / "nse-radar-2026-11-01.db.gz").write_text("x")
    (folder() / "stock-auto-2026-11-01.db.gz").write_text("x")  # not the cloud's to prune
    backup.run(cloud[0])
    assert sorted(p.name for p in folder().glob("nse-radar-*")) == ["nse-radar-2026-11-11.db.gz"]
    assert (folder() / "stock-auto-2026-11-01.db.gz").exists()


def test_backup_settings_seeded(env):
    assert db.get_setting("backup_every_days") == 7
    with db.tx() as c:
        keys = {r["key"] for r in c.execute("SELECT key FROM settings")}
    assert "backup_every_days" in keys
    assert not {"backup_keep_phone", "backup_every_days_phone"} & keys
