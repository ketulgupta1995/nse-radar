#!/usr/bin/env python3
"""Interactive NSE bhavcopy backfill: same code path as the `bars.nse_bhav.backfill` job,
run batch by batch from the terminal, asking before each new batch.

Usage (from the repo root):
    backend/.venv/bin/python scripts/bhav_backfill.py [--batch 400] [--oldest-first] [--yes]

Each batch is recorded as a normal job run (trigger=manual), so it also shows on the Jobs page.
Ctrl+C stops cleanly; the run is marked cancelled and everything fetched so far is kept.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import config, db, timeutil
from app.jobs import runner
from app.jobs.context import JobContext, StopRequested
from app.plugins import import_all
from app.sources import jobs as sjobs
from app.sources import registry

SOURCE, CAP = "nse_bhav", "bars"


def fmt_dur(s: float) -> str:
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{sec:02d}s"


def bar(done: int, total: int, width: int = 30) -> str:
    frac = done / total if total else 1.0
    n = round(frac * width)
    return f"[{'#' * n}{'.' * (width - n)}] {frac:6.1%}"


class PrintingContext(JobContext):
    """JobContext that also prints each item with progress + ETA, like the Jobs page."""

    def __init__(self, run_id: int, job_name: str):
        super().__init__(run_id, {}, job_name)
        self.total = 0
        self.n = 0
        self.counts = {"ok": 0, "skipped": 0, "failed": 0}
        self.t0 = time.monotonic()

    def set_total(self, n: int) -> None:
        super().set_total(n)
        self.total = n
        self.t0 = time.monotonic()
        print(f"  batch has {n} dates to fetch\n")

    def item(self, key, status, detail=None) -> None:
        super().item(key, status, detail)
        self.n += 1
        self.counts[status] += 1
        elapsed = time.monotonic() - self.t0
        eta = elapsed / self.n * (self.total - self.n)
        w = len(str(self.total))
        mark = {"ok": "ok  ", "skipped": "skip", "failed": "FAIL"}[status]
        print(
            f"  [{self.n:>{w}}/{self.total}] {self.n / self.total:4.0%}  {key} ({date.fromisoformat(key):%a})"
            f"  {mark}  {(detail or '')[:60]:<60}  eta {fmt_dur(eta)}",
            flush=True,
        )

    def log(self, msg, level="info") -> None:
        super().log(msg, level)
        print(f"  [{level}] {msg}", flush=True)


def overall(variant) -> dict:
    """Coverage over every weekday from history_start to yesterday."""
    spec = registry.spec(SOURCE, CAP)
    start = date.fromisoformat(spec.history_start) if spec.history_start else config.HISTORY_START
    all_days = sjobs.weekdays(start, timeutil.today() - timedelta(days=1))
    with db.tx() as conn:
        fetched = sjobs._fetched(conn, SOURCE, CAP)
    dated = {date.fromisoformat(k): (s, datetime.fromisoformat(at)) for k, (s, at) in fetched.items()}
    pending = sjobs.select_date_keys(start, timeutil.today(), timeutil.now().timetz(), variant.params, dated)
    status = {}
    for d in all_days:
        s = dated.get(d, ("missing",))[0]
        status[s] = status.get(s, 0) + 1
    done = status.get("ok", 0) + status.get("not_found", 0)
    return {
        "start": start,
        "total": len(all_days),
        "done": done,
        "ok": status.get("ok", 0),
        "holidays": status.get("not_found", 0),
        "failed": status.get("failed", 0),
        "pending": len(pending),
        "oldest_pending": min(pending) if pending else None,
        "newest_pending": max(pending) if pending else None,
    }


def print_overall(o: dict) -> None:
    print(f"\n  Overall  {bar(o['done'], o['total'])}  {o['done']}/{o['total']} weekdays since {o['start']}")
    print(f"           ok={o['ok']}  holidays(404)={o['holidays']}  failed={o['failed']}  pending={o['pending']}")
    if o["pending"]:
        print(f"           pending range: {o['oldest_pending']} .. {o['newest_pending']}")


def active_backfill(job: str):
    with db.tx() as c:
        return c.execute(
            "SELECT id, status FROM job_runs WHERE job=? AND status IN ('queued','running') ORDER BY id",
            (job,),
        ).fetchall()


def start_run(job: str) -> int:
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO job_runs(job, params, trigger, status, queued_at, started_at) "
            "VALUES (?, '{}', 'manual', 'running', ?, ?)",
            (job, timeutil.now_iso(), timeutil.now_iso()),
        )
        return int(cur.lastrowid)


def ask(prompt: str) -> bool:
    try:
        ans = input(prompt).strip().lower()
        return ans in ("y", "yes") or (ans == "" and "[Y/n]" in prompt)
    except EOFError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=int, default=400, help="dates per batch (default 400, same as the job)")
    ap.add_argument("--oldest-first", action="store_true", help="fill from 2010 forwards instead of newest first")
    ap.add_argument("--yes", action="store_true", help="don't ask between batches")
    args = ap.parse_args()

    db.init_db()
    import_all("app.sources.adapters")
    import_all("app.jobs.defs")
    sjobs.register_source_jobs()

    spec = registry.spec(SOURCE, CAP)
    base = next(v for v in spec.jobs if v.suffix == "backfill")
    variant = dataclasses.replace(
        base, max_items=args.batch, params={**base.params, "newest_first": not args.oldest_first}
    )
    job = sjobs.job_name(SOURCE, CAP, base)

    print(f"NSE bhavcopy backfill  (job {job}, db {config.DB_PATH})")
    print(f"batch size {args.batch}, order {'oldest' if args.oldest_first else 'newest'} first")
    if not registry.is_enabled(SOURCE):
        print("\n!! The nse_bhav source is disabled (paused). Re-enable it on the Sources page first.")
        return 1

    busy = active_backfill(job)
    if busy:
        ids = ", ".join(f"#{r['id']} ({r['status']})" for r in busy)
        print(f"\n!! The app already has a backfill run {ids}. Running both fetches the same dates twice.")
        if not ask("   Continue anyway? [y/N] "):
            return 1

    o = overall(variant)
    print_overall(o)
    if not o["pending"]:
        print("\nNothing left to fetch.")
        return 0

    batch_no, session_t0, session_ok = 0, time.monotonic(), 0
    while True:
        batches_left = -(-o["pending"] // args.batch)
        if not args.yes and not ask(
            f"\nRun batch {batch_no + 1} (up to {min(args.batch, o['pending'])} dates, "
            f"~{batches_left} batch(es) left)? [Y/n] "
        ):
            break
        batch_no += 1
        run_id = start_run(job)
        print(f"\n=== Batch {batch_no}  (job run #{run_id}) ===")
        ctx = PrintingContext(run_id, job)
        status, message = "done", None
        try:
            message = sjobs.run_source_job(ctx, SOURCE, CAP, variant)
        except (KeyboardInterrupt, StopRequested):
            status, message = "cancelled", "stopped from script"
        except Exception as e:  # noqa: BLE001 - record the failure, like the job runner
            status, message = "failed", f"{type(e).__name__}: {e}"
        runner._finish(run_id, status, message)
        if status == "done":
            runner._enqueue_followups(run_id, job)  # price_checks / screens_run, picked up by the app

        el = time.monotonic() - ctx.t0
        c = ctx.counts
        session_ok += c["ok"]
        print(f"\n  Batch {batch_no} {status}: {message}")
        print(f"  ok={c['ok']}  skipped={c['skipped']}  failed={c['failed']}  in {fmt_dur(el)}"
              + (f"  ({el / ctx.n:.1f}s/date)" if ctx.n else ""))

        o = overall(variant)
        print_overall(o)
        if o["pending"] and ctx.n:
            print(f"           est. time for the rest: {fmt_dur(el / ctx.n * o['pending'])}")

        if status != "done":
            break
        if not o["pending"]:
            print("\nAll caught up.")
            break
        if ctx.n == 0:
            print("\nBatch selected no dates (remaining ones failed in the last 24h and are on cooldown).")
            break

    print(f"\nSession: {batch_no} batch(es), {session_ok} dates stored, {fmt_dur(time.monotonic() - session_t0)}.")
    if batch_no:
        print("Follow-up jobs (price checks, screens) were queued; they run when the app is up.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
