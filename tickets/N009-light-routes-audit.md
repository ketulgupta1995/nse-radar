# N009: Make every Vercel route light
Cloud · Depends on: N007 · Model: **opus** (judgement across all ~90 routes)

## Goal
No request on Vercel scans `bars` broadly, loads many frames, or runs longer than a few seconds against remote Turso (SPEC §17.5 "Light routes only"). Heavy work becomes a job whose results the UI reads.

## Read first
SPEC §17.2, §17.5, §6, §10, §12, `backend/app/api/*.py`, `backend/app/analytics/frames.py`, `backend/app/analytics/price_store.py`, `backend/app/bardb.py`

## Files
- `docs/CLOUD_ROUTES.md` (new): a table of every route with columns route · what it reads · light/heavy · how it's handled on Vercel. Measure the statement count with a test helper that counts `execute` calls on a seeded fixture DB.
- `backend/tests/test_route_weight.py` (new): for every GET route listed as light, call it on a fixture DB with a statement-counting connection and assert ≤ 50 statements. Routes that take parameters use fixture values.
- For each heavy route, the narrowest fix:
  - (a) read precomputed results the drain already writes, or
  - (b) turn it into `runner.enqueue(...)` + poll, reusing an existing job where there is one (e.g. `screens_run`). The frontend shows "Running in the cloud worker…", then polls `GET /api/jobs/runs/{id}`.
  - (c) trial runs and screen previews that evaluate rules over the whole universe become a job (new `jobs/defs/screen_preview.py` if needed) with results stored in the existing tables or `job_runs.result`.
- `analytics/frames.py` / `price_store.py`: in vercel mode, the price store is off and frame cache entries expire after `VERCEL_CACHE_TTL_S` (§17.2).
- `api/settings.py`: in vercel mode, manual backup (`POST /api/backup`) returns 409 "Backups run weekly in the cloud worker" (N011 adds the real thing).
- Custom indicators on Vercel: never executed (§17.2). Any route that would evaluate one becomes a job.
- Frontend: only the pages whose API behaviour changed, with tests.

## Requirements
- Local mode keeps today's behaviour unless the route is identical in both. Prefer one code path that works in both, though: enqueue-and-poll also works locally because the local worker runs it.
- Stop and ask the owner before removing any feature outright.

## Notes for the planner
