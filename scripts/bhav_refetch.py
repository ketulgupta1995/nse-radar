#!/usr/bin/env python3
"""One-off: re-download every bhavcopy date with the fixed parser, fetch weekend sessions, then re-check.

Before T075/T080 the parser kept only EQ-series rows, so days a stock spent in the trade-for-trade series
(BE/BZ) were dropped (93 universe stocks were missing ~10,400 trading days), REIT/InvIT units (RR/IV)
were never stored, and weekend sessions (Budget day 2025-02-01, Muhurat days...) were never requested.
The raw files were never kept, so the only fix is to fetch each date again. Existing rows are
overwritten with the same values. Weekends with no session are a quick 404 and are never asked again.

Resumable: a date counts as done once it has been fetched after the T080 fix (REFETCH_AFTER). Stop with
Ctrl+C at any time and run the script again later; it continues where it stopped.

After the last date it also runs, in this order (skip with --no-after):
  1. event_factors      - demerger/rights factors from the complete prices (T084)
  2. price_checks_full  - full-history price checks (T079)
  3. quarters re-run    - stocks whose 2021-22 results failed with "no context matches the period",
                          now readable (T081); about 1 hour of NSE downloads
  4. fundamentals_merge - picks up all re-fetched quarterly results

Usage (from the repo root; the app may be stopped or running):
    backend/.venv/bin/python scripts/bhav_refetch.py [--batch 200] [--yes] [--no-after]

About 1.5-2 s per trading date at NSE's polite 1 request/second: ~4,160 dates = about 2 hours, plus
~1,750 weekend dates that are mostly fast 404s (about 30-40 minutes).
"""

from __future__ import annotations

import argparse
import dataclasses
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _backfill import (
    PrintingContext,
    _setup,
    _variant,
    ask,
    busy_runs,
    fmt_dur,
    run_one_batch,
    start_run,
)
from app import db
from app.jobs import runner
from app.jobs.context import StopRequested

SOURCE, CAP, SUFFIX = "nse_bhav", "bars", "backfill"
REFETCH_AFTER = "2026-11-11T00:13:28+05:30"  # commit time of T080 (BE/BZ + RR/IV parsing, weekends)
HISTORY_START = date(2010, 1, 1)
OTHER_NSE_SCRIPTS = ("quarters_backfill.py", "announcements_backfill.py", "actions_backfill.py")


def pending_dates() -> tuple[list[str], int]:
    """(dates still to fetch, newest first; total dates in scope).

    In scope: every calendar day from HISTORY_START to yesterday. Done: fetched OK after REFETCH_AFTER,
    or a 404 (holiday / no weekend session) at any time.
    """
    with db.tx() as c:
        rows = c.execute(
            "SELECT key, status, fetched_at FROM source_fetch WHERE source=? AND capability=?",
            (SOURCE, CAP),
        ).fetchall()
    done = {
        r["key"]
        for r in rows
        if r["status"] == "not_found" or (r["status"] == "ok" and r["fetched_at"] >= REFETCH_AFTER)
    }
    last = date.today() - timedelta(days=1)
    days = [(HISTORY_START + timedelta(days=i)).isoformat() for i in range((last - HISTORY_START).days + 1)]
    todo = sorted((d for d in days if d not in done), reverse=True)
    return todo, len(days)


def other_nse_script_running() -> str | None:
    for name in OTHER_NSE_SCRIPTS:
        if subprocess.run(["pgrep", "-f", name], check=False, capture_output=True).returncode == 0:
            return name
    return None


def run_job(name: str, fn) -> None:
    """Run an app job inline, recorded on the Jobs page like a manual run."""
    run_id = start_run(name, "{}")
    print(f"\n=== {name}  (job run #{run_id}) ===")
    ctx = PrintingContext(run_id, {}, name, "items")
    status, message = "done", None
    try:
        message = fn(ctx)
    except (KeyboardInterrupt, StopRequested):
        status, message = "cancelled", "stopped from script"
    except Exception as e:  # noqa: BLE001 - record the failure, like the job runner
        status, message = "failed", f"{type(e).__name__}: {e}"
    runner._finish(run_id, status, message)
    if status == "done":
        runner._enqueue_followups(run_id, name)
    print(f"\n  {name} {status}: {message}")
    if status == "cancelled":
        raise KeyboardInterrupt


def oned_quarter_symbols() -> list[str]:
    with db.tx() as c:
        rows = c.execute(
            "SELECT DISTINCT symbol FROM quarters WHERE parse_error LIKE 'no context%' ORDER BY symbol"
        ).fetchall()
    return [r["symbol"] for r in rows]


def rerun_quarters() -> None:
    syms = oned_quarter_symbols()
    if not syms:
        print("\nNo quarters with the old XBRL context error; skipping the quarters re-run.")
        return
    _, qbase = _variant("nse_api", "quarters", "")
    qvariant = dataclasses.replace(qbase, max_items=10**9)
    status, _ = run_one_batch(
        "nse_api", "quarters", qvariant, "quarters.nse_api", syms, "stocks", "Quarters re-run (T081)"
    )
    if status == "cancelled":
        raise KeyboardInterrupt


def after_steps() -> None:
    from app.jobs.defs import event_factors, fundamentals_merge, price_checks

    run_job("event_factors", event_factors.run)
    run_job("price_checks_full", lambda ctx: price_checks.run_checks(ctx, None))
    rerun_quarters()
    run_job("fundamentals_merge", fundamentals_merge.run)
    print("\nOpen price checks are on the Data health page; demerger/rights factors at /api/data/event-factors.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=int, default=200, help="dates per batch (default 200)")
    ap.add_argument("--yes", action="store_true", help="don't ask between batches")
    ap.add_argument("--no-after", action="store_true", help="skip the price checks + fundamentals merge")
    args = ap.parse_args()

    other = other_nse_script_running()
    if other:
        print(f"!! {other} is still running. It downloads from the same NSE server; wait until it ends.")
        return 1
    _setup()
    busy = busy_runs(SOURCE) + busy_runs("nse_api")
    running = [r for r in busy if r["status"] == "running"]
    if running:
        ids = ", ".join(f"#{r['id']} {r['job']}" for r in running)
        print(f"!! The app is fetching from NSE right now ({ids}). Wait for it (Jobs page), then run again.")
        return 1

    _, base = _variant(SOURCE, CAP, SUFFIX)
    variant = dataclasses.replace(base, max_items=10**9)
    job = f"{CAP}.{SOURCE}.{SUFFIX}"

    todo, total = pending_dates()
    print(f"Bhavcopy re-fetch: {total - len(todo)}/{total} days already done, {len(todo)} to go.")
    t0, done_now, batch_no = time.monotonic(), 0, 0
    try:
        while todo:
            keys = todo[: args.batch]
            left = -(-len(todo) // args.batch)
            if not args.yes and not ask(
                f"\nRun batch {batch_no + 1} ({len(keys)} dates: {keys[0]} .. {keys[-1]}, ~{left} left)? [Y/n] "
            ):
                print("Stopped. Run the script again later to continue.")
                return 0
            batch_no += 1
            status, ctx = run_one_batch(SOURCE, CAP, variant, job, keys, "dates", f"Batch {batch_no}")
            done_now += ctx.counts["ok"] + ctx.counts["skipped"]
            if status != "done":
                print("Batch did not finish; run the script again later to continue.")
                return 130 if status == "cancelled" else 1
            if ctx.n and ctx.counts["failed"] == ctx.n:
                print("Every date in this batch failed (NSE down or refusing?). Try again later.")
                return 1
            todo, total = pending_dates()
            rate = (time.monotonic() - t0) / max(done_now, 1)
            print(f"  progress: {total - len(todo)}/{total} dates; about {fmt_dur(rate * len(todo))} left")
    except KeyboardInterrupt:
        print("\nStopped. Everything fetched so far is kept; run again later to continue.")
        return 130

    print(f"\nAll {total} dates re-fetched ({done_now} this session, {fmt_dur(time.monotonic() - t0)}).")
    if not args.no_after:
        try:
            after_steps()
        except KeyboardInterrupt:
            print("\nStopped during the follow-up steps. Run them from the Jobs page instead.")
            return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
