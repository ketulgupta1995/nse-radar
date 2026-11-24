"""Make the one-time Turso seed from a read-only copy of the laptop DB (SPEC §17.6).

    python scripts/make_seed.py --from ~/ketul/claude_projects/stock-tools/data/stock.db --out data/seed.db

The source is opened with a `mode=ro` URI and copied with `VACUUM INTO`; nothing in it is written.
Only the copy is changed. Prints row counts and sizes only, never row contents (§17.8).
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger("make_seed")

HISTORY_TABLES = ("job_runs", "job_items", "ai_requests")
CLOUD_SETTINGS = {"ai_provider": "copy_prompt", "backtest_workers": 3, "jobs_paused": False}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="src", required=True, type=Path, help="laptop stock.db (read-only)")
    p.add_argument("--out", required=True, type=Path, help="seed file to write, e.g. data/seed.db")
    p.add_argument("--force", action="store_true", help="overwrite --out if it exists")
    return p.parse_args(argv)


def check_paths(src: Path, out: Path, force: bool) -> str | None:
    """Returns why the copy must not run, or None when it may."""
    if not src.is_file():
        return f"source not found: {src}"
    if src.resolve() == out.resolve() or (out.exists() and src.samefile(out)):
        return "--from and --out are the same file"
    if out.exists() and not force:
        return f"{out} already exists (use --force to overwrite)"
    return None


def copy_readonly(src: Path, out: Path) -> None:
    uri = f"file:{quote(str(src.resolve()))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    try:
        conn.execute("VACUUM INTO ?", (str(out),))
    finally:
        conn.close()


def clean_copy(conn: sqlite3.Connection) -> None:
    """Clears laptop history and sets the cloud settings, on the copy only."""
    conn.execute("BEGIN IMMEDIATE")
    for table in HISTORY_TABLES:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("UPDATE job_schedules SET last_run_id=NULL")  # pointed at the cleared laptop runs
    conn.execute("DELETE FROM alerts WHERE kind LIKE 'backup%'")
    conn.execute("DELETE FROM settings WHERE key LIKE 'backup%'")  # laptop-only; defaults apply
    for key, value in CLOUD_SETTINGS.items():
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
    conn.execute("COMMIT")
    conn.execute("VACUUM")  # give back the pages the deletes freed


def finish_copy(conn: sqlite3.Connection) -> str:
    """WAL mode (Turso import needs it), then quick_check. Returns the check result."""
    mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    if mode.lower() != "wal":
        raise RuntimeError(f"could not set WAL mode (got {mode})")
    return conn.execute("PRAGMA quick_check").fetchone()[0]


def row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def report(out: Path, counts: dict[str, int]) -> None:
    width = max((len(t) for t in counts), default=0)
    for table, n in counts.items():
        log.info("  %-*s %12s rows", width, table, f"{n:,}")
    log.info("seed file: %s (%.1f MB)", out, out.stat().st_size / 1e6)
    log.info("next: turso db create nse-radar --group us --from-file %s", out)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    problem = check_paths(args.src, args.out, args.force)
    if problem:
        log.error("refusing: %s", problem)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):  # --force: VACUUM INTO needs an absent target
        Path(f"{args.out}{suffix}").unlink(missing_ok=True)
    log.info("copying %s (read-only) to %s", args.src, args.out)
    copy_readonly(args.src, args.out)
    conn = sqlite3.connect(args.out, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")  # as db.connect(): job_logs go with their job_runs
    try:
        clean_copy(conn)
        check = finish_copy(conn)
        counts = row_counts(conn)
    finally:
        conn.close()
    if check != "ok":
        log.error("quick_check failed on the copy: %s", check)
        return 1
    report(args.out, counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
