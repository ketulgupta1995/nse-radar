"""Thread-free job drain for GitHub Actions (SPEC §17.3).

    python -m app.jobs.drain [--tick] [--budget-min N] [--lane background|interactive|all]

Runs queued jobs in the foreground until the queue is empty or the time budget runs out.
Output is counts only (§17.8): never params, messages or rows.
"""

import argparse
import json
import logging
import threading
import time

from app import bardb, bootstrap, config, db, timeutil
from app.jobs import runner, scheduler

log = logging.getLogger("app.jobs.drain")  # explicit: under `python -m` __name__ is "__main__"

DEFAULT_BUDGET_MIN = 100.0
STOP_REPEAT_S = 1.0  # after the budget, keep asking whatever is running to stop


def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m app.jobs.drain", description="Run queued jobs, then exit.")
    p.add_argument("--tick", action="store_true", help="enqueue every due schedule first")
    p.add_argument("--budget-min", type=float, default=None, help=f"minutes (default {DEFAULT_BUDGET_MIN:g})")
    p.add_argument("--lane", choices=("background", "interactive", "all"), default="all")
    return p.parse_args(argv)


def _setup_logging() -> None:
    if config.RUNTIME == "actions":  # public logs: job output stays in job_runs (§17.8)
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
        logging.getLogger().setLevel(logging.WARNING)
    else:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log.setLevel(logging.INFO)


def _lanes(choice: str) -> tuple[str, ...]:
    return ("interactive", "background") if choice == "all" else (choice,)


def _stop_running() -> None:
    """Ask every running run to stop. After recover_on_startup only this drain's run can be running."""
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM job_runs WHERE status='running'")]
    for run_id in ids:
        runner.request_stop(run_id)


def _watchdog(expired: threading.Event, finished: threading.Event) -> None:
    expired.set()
    while not finished.is_set():
        try:
            _stop_running()
        except Exception:
            log.exception("watchdog could not request a stop")
        finished.wait(STOP_REPEAT_S)


def _row(run_id: int):
    with db.tx() as c:
        return c.execute(
            "SELECT job, params, status, stop_requested, ok, failed FROM job_runs WHERE id=?", (run_id,)
        ).fetchone()


def _resume_if_stopped(row) -> bool:
    """A run stopped by the budget is queued again with the same params (trigger "system")."""
    if row["status"] != "cancelled" or not row["stop_requested"]:
        return False
    runner.enqueue(row["job"], params=json.loads(row["params"]), trigger="system")
    return True


def _run_next(lanes: tuple[str, ...]) -> int | None:
    db.sync()  # replica reads are local: pull jobs queued on the site since the last pick
    for lane in lanes:
        run_id = runner.run_one(lane)
        if run_id is not None:
            return run_id
    return None


def _startup(tick: bool) -> None:
    db.sync()
    db.init_db()
    bootstrap.load_plugins()
    scheduler.ensure_schedules()
    runner.recover_on_startup()
    if tick:
        scheduler.tick(timeutil.now())
    _ensure_bar_counts()


def _ensure_bar_counts() -> None:
    """A freshly seeded cloud DB has no `bars_coverage` snapshot (the seed file is made offline, so it
    enqueues nothing): queue `housekeeping` once so the Sources page on Vercel shows row counts (N021)."""
    if config.RUNTIME != "actions":
        return
    try:
        db.get_setting(bardb.COVERAGE_KEY)
        return
    except KeyError:
        pass
    runner.enqueue("housekeeping", trigger="system")


def _drain(lanes: tuple[str, ...], expired: threading.Event, counts: dict[str, int]) -> None:
    while not expired.is_set():
        run_id = _run_next(lanes)
        if run_id is None:
            return
        row = _row(run_id)
        counts["jobs"] += 1
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        counts["items_ok"] += row["ok"] or 0
        counts["items_failed"] += row["failed"] or 0
        if expired.is_set() and _resume_if_stopped(row):
            counts["resumed"] += 1
            return


def _summary(counts: dict[str, int], minutes: float, budget_hit: bool) -> str:
    return (
        f"drain finished: jobs={counts['jobs']} done={counts.get('done', 0)} "
        f"failed={counts.get('failed', 0)} cancelled={counts.get('cancelled', 0)} "
        f"items_ok={counts['items_ok']} items_failed={counts['items_failed']} "
        f"resumed={counts['resumed']} budget_hit={'yes' if budget_hit else 'no'} minutes={minutes:.1f}"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    _setup_logging()
    t0 = time.monotonic()
    budget_min = DEFAULT_BUDGET_MIN if args.budget_min is None else args.budget_min
    _startup(args.tick)
    expired, finished = threading.Event(), threading.Event()
    timer = threading.Timer(budget_min * 60, _watchdog, args=(expired, finished))
    timer.daemon = True
    timer.start()
    counts = {"jobs": 0, "items_ok": 0, "items_failed": 0, "resumed": 0}
    try:
        _drain(_lanes(args.lane), expired, counts)
    finally:
        finished.set()
        timer.cancel()
    db.sync()
    log.info(_summary(counts, (time.monotonic() - t0) / 60, expired.is_set()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
