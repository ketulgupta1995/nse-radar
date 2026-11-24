# N004: Thread-free job drain (`python -m app.jobs.drain`)
Cloud · Depends on: N002 · Model: sonnet

## Goal
Jobs run in the foreground until the queue is empty or a time budget runs out, with no worker or scheduler threads, so GitHub Actions can run them (SPEC §17.3). The laptop-style threads stay for `local` mode.

## Read first
SPEC §17.2, §17.3, §17.8, §6 (jobs framework), `backend/app/main.py`, `backend/app/jobs/runner.py`, `backend/app/jobs/scheduler.py`, `backend/app/jobs/context.py`

## Files
- `backend/app/jobs/drain.py` (new): `main(argv: list[str] | None = None) -> int` plus `if __name__ == "__main__"`. Steps 1–5 of §17.3 exactly. Share the plug-in imports with `main.py` by moving them into `app/bootstrap.py` (new): `load_plugins() -> None`, which runs the `import_all` calls, `register_source_jobs()` and `custom_indicators.load_approved()` unless `RUNTIME == "vercel"`.
- Budget stop: a watchdog `threading.Timer` calls `runner.request_stop(current_run_id)` when the budget expires. Once that job ends `stopped`, re-enqueue it with the same params and `trigger="resume"`, then exit 0. Runs still `queued` stay queued.
- Logging in `actions` mode: root WARNING, `app.jobs.drain` INFO. The final summary is one line of counts (§17.8).
- `backend/app/main.py`: lifespan uses `bootstrap.load_plugins()`. When `RUNTIME == "vercel"`, skip `init_db`, `recover_on_startup`, the worker and the scheduler. Local behaviour is unchanged.
- Tests: `backend/tests/test_drain.py` (new): with fake jobs registered, the drain runs queued interactive jobs before background ones, `--tick` enqueues due schedules (frozen time), an empty queue exits 0, the budget path re-enqueues the stopped job with trigger `resume` (budget patched to a tiny value; a fake job that loops until `ctx.should_stop()`), and the summary contains no params or messages. Existing tests pass.

## Notes for the planner
