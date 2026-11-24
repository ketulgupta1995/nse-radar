# N005: Kick the cloud worker from Vercel, keep the schedule alive, `/api/cloud/status`
Cloud · Depends on: N004 · Model: sonnet

## Goal
When Vercel enqueues a job, a GitHub Actions drain starts within a minute or two. Scheduled workflows never get auto-disabled. The UI can ask what's happening in the cloud (SPEC §17.4).

## Read first
SPEC §17.4, §17.2, §6, `backend/app/jobs/runner.py` (`enqueue`), `backend/app/db.py` (`after_commit`, settings), `backend/app/sources/http.py` (transport pattern for fakes)

## Files
- `backend/app/cloud/__init__.py` (empty), `backend/app/cloud/dispatch.py` (new): `kick(reason: str) -> bool` and `keepalive() -> bool`, as §17.4. Use `httpx` directly with a module-level injectable transport for tests (this is GitHub's API, not a data source, so it doesn't go through `sources.http`). Read `GITHUB_DISPATCH_TOKEN` from the env. Never log the token.
- `backend/app/jobs/runner.py`: in `enqueue`, when `config.RUNTIME == "vercel"` and a new run was inserted, `db.after_commit(lambda: dispatch.kick(f"enqueue {job}"))`.
- `backend/app/api/cloud.py` (new, auto-mounted): `GET /api/cloud/status` → `{"runtime": str, "dispatch_configured": bool, "last_dispatch_at": str|null, "queued": int, "running": int, "oldest_queued_at": str|null}`. It also calls `dispatch.keepalive()` (rate-limited inside, at most once every 7 days).
- Tests: `backend/tests/test_dispatch.py` (new): kick posts the right URL/body/headers; debounce within 60 s; a failure returns False and the job stays queued; keepalive at most once every 7 days; enqueue in vercel mode kicks after commit and in local mode doesn't; the status shape.

## Notes for the planner
- SPEC §17.4 says keep-alive runs "on any `/api/jobs/status` call"; this ticket says `/api/cloud/status`. Implemented the ticket (only `/api/cloud/status` calls `keepalive()`). Update the SPEC line, or make sure N019's Cloud panel polls `/api/cloud/status` so keep-alive actually fires.
- `kick()` returns True when debounced (a dispatch went out < 60 s ago), False when not configured or when GitHub/network fails. `last_dispatch_at` is recorded only on success, so a failed kick is retried by the next enqueue. `last_keepalive_at` is recorded on every attempt, so a failing keep-alive doesn't hit GitHub on every status poll.
- Added `dispatch.configured()` and `dispatch.last_dispatch_at()` helpers (used by the status route).
