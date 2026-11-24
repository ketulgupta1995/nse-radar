"""Shared engine for the per-dataset backfill scripts (screener_backfill.py, quarters_backfill.py, ...).

Same code path as the app's source jobs (`run_source_job`), run batch by batch from the terminal with
progress + ETA, asking before each batch. Each batch is a normal job run (trigger=manual), so it shows on
the Jobs page, can be stopped there, and queues the same follow-up jobs (fundamentals_merge, alerts_scan...).

Keys that fail during this session are not retried in a later batch of the same session (no endless loop);
run the script again later to retry them.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import config, db, timeutil
from app.jobs import runner
from app.jobs.context import JobContext, StopRequested
from app.plugins import import_all
from app.sources import jobs as sjobs
from app.sources import registry


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
    """JobContext that also prints each item with progress + ETA."""

    def __init__(self, run_id: int, params: dict, job_name: str, unit: str):
        super().__init__(run_id, params, job_name)
        self.unit = unit
        self.total = 0
        self.n = 0
        self.counts = {"ok": 0, "skipped": 0, "failed": 0}
        self.failed_keys: list[str] = []
        self.t0 = time.monotonic()

    def set_total(self, n: int) -> None:
        super().set_total(n)
        self.total = n
        self.t0 = time.monotonic()
        print(f"  batch has {n} {self.unit} to fetch\n")

    def item(self, key, status, detail=None) -> None:
        super().item(key, status, detail)
        self.n += 1
        self.counts[status] += 1
        if status == "failed":
            self.failed_keys.append(key)
        elapsed = time.monotonic() - self.t0
        eta = elapsed / self.n * (self.total - self.n)
        w = len(str(self.total))
        mark = {"ok": "ok  ", "skipped": "skip", "failed": "FAIL"}[status]
        print(
            f"  [{self.n:>{w}}/{self.total}] {self.n / self.total:4.0%}  {key:<12}"
            f"  {mark}  {(detail or '')[:60]:<60}  eta {fmt_dur(eta)}",
            flush=True,
        )

    def log(self, msg, level="info") -> None:
        super().log(msg, level)
        print(f"  [{level}] {msg}", flush=True)


def _setup() -> None:
    db.init_db()
    import_all("app.sources.adapters")
    import_all("app.jobs.defs")
    sjobs.register_source_jobs()


def _variant(source: str, cap: str, suffix: str):
    spec = registry.spec(source, cap)
    if spec is None:
        raise SystemExit(f"!! {source} has no '{cap}' capability")
    for v in spec.jobs:
        if v.suffix == suffix:
            return spec, v
    raise SystemExit(f"!! {source}/{cap} has no job variant '{suffix}'")


def coverage(source: str, cap: str, variant, exclude: set[str]) -> dict:
    """Universe/watch coverage: done = fetched ok/not_found within the variant's freshness window."""
    now = timeutil.now()
    with db.tx() as conn:
        fetched = sjobs._fetched(conn, source, cap)
        symbols = sjobs._scope_symbols(conn, variant.scope)
    status: dict[str, int] = {}
    for k in symbols:
        s = fetched.get(k, ("missing", None))
        if s[0] in ("ok", "not_found") and sjobs._age_ok(s[1], now, variant.min_age_hours):
            label = s[0]
        elif s[0] in ("ok", "not_found"):
            label = "stale"
        else:
            label = s[0]  # missing / failed
        status[label] = status.get(label, 0) + 1
    pending = sjobs.select_symbol_keys(symbols, fetched, now, variant.min_age_hours, 10**9)
    pending = [k for k in pending if k not in exclude]
    return {
        "total": len(symbols),
        "done": status.get("ok", 0) + status.get("not_found", 0),
        "ok": status.get("ok", 0),
        "not_found": status.get("not_found", 0),
        "stale": status.get("stale", 0),
        "failed": status.get("failed", 0),
        "missing": status.get("missing", 0),
        "pending": pending,
    }


def print_coverage(o: dict, unit: str, held_back: int) -> None:
    print(f"\n  Overall  {bar(o['done'], o['total'])}  {o['done']}/{o['total']} {unit} fresh")
    print(
        f"           ok={o['ok']}  not_found={o['not_found']}  never={o['missing']}  "
        f"stale={o['stale']}  failed={o['failed']}  -> pending={len(o['pending'])}"
        + (f"  (+{held_back} failed this session, held back)" if held_back else "")
    )


def busy_runs(source: str) -> list:
    """Queued/running runs of any job of this source (they share the host's rate limit)."""
    with db.tx() as c:
        return c.execute(
            "SELECT id, job, status FROM job_runs WHERE status IN ('queued','running') "
            "AND (job LIKE ? OR job LIKE ?) ORDER BY id",
            (f"%.{source}", f"%.{source}.%"),
        ).fetchall()


def start_run(job: str, params: str) -> int:
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO job_runs(job, params, trigger, status, queued_at, started_at) "
            "VALUES (?, ?, 'manual', 'running', ?, ?)",
            (job, params, timeutil.now_iso(), timeutil.now_iso()),
        )
        return int(cur.lastrowid)


def ask(prompt: str) -> bool:
    try:
        ans = input(prompt).strip().lower()
        return ans in ("y", "yes") or (ans == "" and "[Y/n]" in prompt)
    except EOFError:
        return False


def run_one_batch(source, cap, variant, job, keys, unit, label) -> tuple[str, PrintingContext]:
    import json

    params = {"keys": keys}
    run_id = start_run(job, json.dumps(params))
    print(f"\n=== {label}  (job run #{run_id}) ===")
    ctx = PrintingContext(run_id, params, job, unit)
    status, message = "done", None
    try:
        message = sjobs.run_source_job(ctx, source, cap, variant)
    except (KeyboardInterrupt, StopRequested):
        status, message = "cancelled", "stopped from script"
    except Exception as e:  # noqa: BLE001 - record the failure, like the job runner
        status, message = "failed", f"{type(e).__name__}: {e}"
    runner._finish(run_id, status, message)
    if status == "done":
        runner._enqueue_followups(run_id, job)
    el = time.monotonic() - ctx.t0
    c = ctx.counts
    print(f"\n  {label} {status}: {message}")
    print(
        f"  ok={c['ok']}  skipped={c['skipped']}  failed={c['failed']}  in {fmt_dur(el)}"
        + (f"  ({el / ctx.n:.1f}s/{unit.removesuffix('s')})" if ctx.n else "")
    )
    return status, ctx


def main(source: str, cap: str, suffix: str = "", title: str = "", unit: str = "stocks") -> int:
    ap = argparse.ArgumentParser(
        description=f"{title} backfill ({cap}.{source}{'.' + suffix if suffix else ''}).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--batch", type=int, default=None, help="items per batch (default: the job's max per run)")
    ap.add_argument("--yes", action="store_true", help="don't ask between batches")
    ap.add_argument("--keys", nargs="+", metavar="KEY", help="fetch exactly these keys (symbols or dates), once")
    ap.add_argument("--force", action="store_true", help="run even if the app has a run of this source going")
    args = ap.parse_args()

    _setup()
    spec_probe, base = _variant(source, cap, suffix)
    variant = dataclasses.replace(base, max_items=10**9)  # we pass explicit keys per batch
    job = sjobs.job_name(source, cap, base)
    batch_size = args.batch or base.max_items

    print(f"{title}  (job {job}, db {config.DB_PATH})")
    if not registry.is_enabled(source):
        print(f"\n!! The {source} source is disabled (paused). Re-enable it on the Sources page first.")
        return 1
    busy = busy_runs(source)
    if busy and not args.force:
        ids = ", ".join(f"#{r['id']} {r['job']} ({r['status']})" for r in busy)
        print(f"\n!! The app is already fetching from {source}: {ids}.")
        print("   Two processes would each keep their own rate limit and hit the site twice as fast.")
        print("   Wait for it (or stop it on the Jobs page), or pass --force.")
        return 1

    if args.keys:
        status, ctx = run_one_batch(source, cap, variant, job, args.keys, unit, "Selected keys")
        if status == "cancelled":
            return 130
        return 0 if status == "done" and not ctx.failed_keys else 1

    if spec_probe.mode != "by_symbol":
        print(f"!! {source}/{cap} is '{spec_probe.mode}' mode; use --keys (or bhav_backfill.py for bhavcopy).")
        return 1

    print(f"batch size {batch_size}; freshness window {base.min_age_hours:g}h; scope {base.scope}")
    held: set[str] = set()
    o = coverage(source, cap, base, held)
    print_coverage(o, unit, 0)
    if not o["pending"]:
        print("\nNothing left to fetch.")
        return 0

    batch_no, t_session, stored, rates, status = 0, time.monotonic(), 0, [], "done"
    while True:
        keys = o["pending"][:batch_size]
        left = -(-len(o["pending"]) // batch_size)
        if not args.yes and not ask(
            f"\nRun batch {batch_no + 1} ({len(keys)} {unit}: {keys[0]} .. {keys[-1]}, "
            f"~{left} batch(es) left)? [Y/n] "
        ):
            break
        batch_no += 1
        status, ctx = run_one_batch(source, cap, variant, job, keys, unit, f"Batch {batch_no}")
        stored += ctx.counts["ok"]
        held.update(ctx.failed_keys)
        if ctx.n:
            rates.append((time.monotonic() - ctx.t0) / ctx.n)
        o = coverage(source, cap, base, held)
        print_coverage(o, unit, len(held))
        if o["pending"] and rates:
            print(f"           est. time for the rest: {fmt_dur(sum(rates) / len(rates) * len(o['pending']))}")

        if status != "done":
            break
        if not registry.is_enabled(source):
            print(f"\n!! {source} refused requests and was paused. Re-enable it on the Sources page later.")
            break
        if not o["pending"]:
            print("\nAll caught up." + (f" {len(held)} failed; run again later to retry them." if held else ""))
            break
        if ctx.n and ctx.counts["failed"] == ctx.n:
            print("\nEvery item in this batch failed; stopping (site down or blocking?). Try again later.")
            break

    print(f"\nSession: {batch_no} batch(es), {stored} {unit} stored, {fmt_dur(time.monotonic() - t_session)}"
          f" (finished {datetime.now():%H:%M}).")
    if held:
        print(f"Failed this session ({len(held)}): {', '.join(sorted(held)[:30])}{' ...' if len(held) > 30 else ''}")
    if batch_no:
        print("Follow-up jobs were queued; they run when the app is up.")
    return 130 if status == "cancelled" else 0
