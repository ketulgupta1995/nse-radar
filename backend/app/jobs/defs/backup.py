import gzip
import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path

from app import config, db, timeutil
from app.jobs.context import JobContext
from app.jobs.registry import JobDef, register

log = logging.getLogger(__name__)

KEEP = 7
MB = 1024 * 1024
SUFFIX = ".db.gz"  # gzip shrinks the database ~2x (367 -> 178 MB); restore with `gunzip -k <file>`


def _check_space(folder: Path) -> None:
    need = 2 * config.DB_PATH.stat().st_size
    free = shutil.disk_usage(folder).free
    if free < need:
        raise RuntimeError(f"not enough disk space: need {need // MB} MB, have {free // MB} MB")


def _copy(tmp: Path) -> None:
    conn = db.connect()
    try:
        conn.execute("VACUUM INTO ?", (str(tmp),))
    finally:
        conn.close()


def _verify(tmp: Path) -> None:
    conn = sqlite3.connect(tmp)
    try:
        check = conn.execute("PRAGMA quick_check").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
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
    # Older uncompressed backups (`.db`) count towards the same 7, oldest first by date in the name.
    files = sorted(
        (p for p in folder.glob("stock-auto-*") if p.is_file() and p.name.endswith((".db", SUFFIX))),
        key=lambda p: p.name.removesuffix(".gz"),
    )
    for old in files[:-KEEP]:
        old.unlink()
    return min(len(files), KEEP)


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
    name = f"stock-auto-{today.isoformat()}{SUFFIX}"
    if (folder / name).exists() or (folder / name.removesuffix(".gz")).exists():
        msg = "already backed up today"
        ctx.item("backup", "skipped", msg)
        return msg
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
        description="Saves a checked, compressed database copy to data/backups nightly; keeps the last 7.",
        fn=run,
        default_schedule={"kind": "daily", "at_time": "02:30"},
        stage=9,
        lane="background",
    )
)
