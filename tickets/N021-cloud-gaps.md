# N021: Cloud gaps found by the route audit
Cloud · Depends on: N009, N005 · Model: opus

## Goal
Close the small gaps N009 found, so every page behaves the same on Vercel as locally.

## Read first
SPEC §17.2, §17.5, §17.12, §3.5 (secrets), §8.3, `docs/CLOUD_ROUTES.md`, the N009 ticket notes, `backend/app/sources/secrets.py`, `backend/app/analytics/custom_indicators.py`, `backend/app/jobs/runner.py`, `backend/app/api/health.py`, `frontend/src/api/client.ts`

## Files and requirements
1. **Source secrets on Vercel:** `data/secrets.json` can't be written there (read-only file system). In `vercel`/`actions` mode, `sources/secrets.py` stores secrets in a new table `source_secrets(source TEXT, key TEXT, value TEXT, PRIMARY KEY(source, key))` (a migration and a `SCHEMA_VERSION` bump are allowed here). Local mode keeps the file. The API never returns the values (unchanged rule). Note in `docs/CLOUD_SETUP.md` that the values sit in Turso, which is private.
2. **Custom indicators on Vercel:** load the approved indicators' names, params and `explain` (never their code), so rules that name one pass validation and describe correctly. Evaluating one stays a job (§17.2).
3. **`runner.enqueue_many(items) -> list[int]`:** one transaction and one `dispatch.kick`. `POST /api/jobs/refresh` uses it. Keep `test_route_weight` passing with a lower limit for that route (≤ 15 statements).
4. **Runtime in the UI:** a `useRuntime()` hook from `/api/health` (`runtime`). Show the job wait text "Waiting for the cloud worker…" only when `runtime === "vercel"`, otherwise "Running…".
5. **`bars_coverage` after seeding:** `scripts/make_seed.py` enqueues nothing (the file is offline). Instead, the drain's startup runs `housekeeping` once when `bars_coverage` is missing.

## Tests
One per item, backend and frontend as relevant. All checks pass.

## Notes for the planner
