import gzip
import logging
import os
import shutil
import sqlite3
import time
from datetime import date
from pathlib import Path

from app import config, db, timeutil
from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register

log = logging.getLogger(__name__)

KEEP = 7
MB = 1024 * 1024
SUFFIX = ".db.gz"  # gzip shrinks the database ~2x (367 -> 178 MB); restore with `gunzip -k <file>`
LOCAL_PREFIX = "stock-auto-"
CLOUD_PREFIX = "nse-radar-"  # actions mode (SPEC §17.8): drain.yml encrypts, uploads, then deletes it
CLOUD_KEEP = 1


def _cloud() -> bool:
    return config.RUNTIME == "actions"


def _source() -> Path:
    """The database file to copy: the embedded replica in actions mode, else the local DB."""
    return Path(config.REPLICA_PATH) if _cloud() and config.REPLICA_PATH else config.DB_PATH


def _check_space(folder: Path) -> None:
    need = 2 * _source().stat().st_size
    free = shutil.disk_usage(folder).free
    if free < need:
        raise RuntimeError(f"not enough disk space: need {need // MB} MB, have {free // MB} MB")


def _copy(tmp: Path) -> None:
    if _cloud():  # pull the latest writes, then VACUUM INTO straight from the local replica file
        db.sync()
        conn = sqlite3.connect(_source())
    else:
        conn = db.connect()
    try:
        conn.execute("VACUUM INTO ?", (str(tmp),))
    finally:
        conn.close()


def _verify(tmp: Path) -> None:
    conn = sqlite3.connect(tmp)
    try:
        check = conn.execute("PRAGMA quick_check").fetchone()[0]
        version = db.schema_version(conn)
    finally:
        conn.close()
    if check != "ok":
        raise RuntimeError(f"backup failed the integrity check: {check}")
    if version != db.SCHEMA_VERSION:
        raise RuntimeError(f"backup has schema version {version}, expected {db.SCHEMA_VERSION}")


def _compress(src: Path, dest: Path) -> None:
    with open(src, "rb") as f, gzip.open(dest, "wb", compresslevel=6) as out:
        shutil.copyfileobj(f, out, 4 * MB)


def _prune(folder: Path) -> int:
    # Older uncompressed backups (`.db`) count towards the same limit, oldest first by date in the name.
    prefix, keep = (CLOUD_PREFIX, CLOUD_KEEP) if _cloud() else (LOCAL_PREFIX, KEEP)
    files = sorted(
        (p for p in folder.glob(f"{prefix}*") if p.is_file() and p.name.endswith((".db", SUFFIX))),
        key=lambda p: p.name.removesuffix(".gz"),
    )
    for old in files[:-keep]:
        old.unlink()
    return min(len(files), keep)


def _last_cloud_backup() -> date | None:
    """Date of the newest successful cloud backup. Read from job_runs: the file never stays on the runner."""
    with db.tx() as conn:
        row = conn.execute(
            "SELECT message FROM job_runs WHERE job='backup' AND status='done' AND message LIKE ? "
            "ORDER BY id DESC LIMIT 1",
            (f"saved {CLOUD_PREFIX}%",),
        ).fetchone()
    if not row:
        return None
    try:
        return date.fromisoformat(row[0].removeprefix(f"saved {CLOUD_PREFIX}")[:10])
    except ValueError:
        return None


def _cloud_skip(today: date) -> str | None:
    """A reason to skip when the last cloud backup is younger than `backup_every_days`, else None."""
    every = int(db.get_setting("backup_every_days") or 7)
    last = _last_cloud_backup()
    if last is None or (today - last).days >= every:
        return None
    return f"last backup {(today - last).days} days ago; the next is due after {every} days"


def _backup(ctx: JobContext, folder: Path, name: str) -> str:
    final = folder / name
    tmp = folder / f"{name.removesuffix('.gz')}.tmp"  # the plain copy, checked before compressing
    tmp_gz = folder / f"{name}.tmp"
    started = time.monotonic()
    _check_space(folder)
    tmp.unlink(missing_ok=True)
    tmp_gz.unlink(missing_ok=True)
    try:
        _copy(tmp)
        _verify(tmp)
        _compress(tmp, tmp_gz)
    except Exception:
        tmp_gz.unlink(missing_ok=True)
        raise
    finally:
        tmp.unlink(missing_ok=True)
    os.replace(tmp_gz, final)
    kept = _prune(folder)
    size = round(final.stat().st_size / MB)
    secs = round(time.monotonic() - started)
    ctx.item("backup", "ok", f"{size} MB in {secs} s, kept {kept}")
    return f"saved {name} ({size} MB)"


def run(ctx: JobContext) -> str | None:
    today = timeutil.today()
    folder = config.DATA_DIR / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    prefix = CLOUD_PREFIX if _cloud() else LOCAL_PREFIX
    name = f"{prefix}{today.isoformat()}{SUFFIX}"
    skip = _cloud_skip(today) if _cloud() else None
    if (folder / name).exists() or (folder / name.removesuffix(".gz")).exists():
        skip = "already backed up today"
    if skip:
        ctx.item("backup", "skipped", skip)
        return skip
    try:
        return _backup(ctx, folder, name)
    except Exception as e:
        log.error("backup failed: %s", e)
        db.insert_alert(
            "backup_failed",
            f"Database backup failed: {e}",
            dedupe_key=f"backup_failed:{today}",
            severity="warn",
        )
        raise


register(
    JobDef(
        name="backup",
        title="Database backup",
        description=(
            "Saves a checked, compressed database copy to data/backups nightly; keeps the last 7. "
            "In the cloud: weekly, encrypted, kept 90 days as a GitHub artifact."
        ),
        fn=run,
        default_schedule={"kind": "daily", "at_time": "02:30"},
        stage=9,
        lane="background",
    )
)
