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
- **Contract changes to fold into the SPEC (§10, §8.3):** `POST /api/screens/preview` now returns
  `{run_id}` (job `screen_preview`; matches are the run's `ok` items, key = symbol, detail = values
  JSON). `POST /api/custom-indicators/{id}/approve` returns the still-pending indicator plus `run_id`
  (job `indicator_approve`); `sample` is gone from the response, and the 5 values are in the run's message.
  Both use one code path in local and cloud, as the ticket preferred.
- `job_runs` has no `result` column (the ticket mentions one), and the schema was not changed. Results live in
  `job_items` (preview) and two internal settings keys: `score_prices` (written by `screens_run`) and
  `bars_coverage` (written by `housekeeping`). See `docs/CLOUD_ROUTES.md`.
- Files changed beyond the ticket's list, each the narrowest fix for a heavy route: `sources/registry.py`
  (`ordered()` reads every source's on/off state in one query, and caches the order on Vercel for at most
  `VERCEL_CACHE_TTL_S`, cleared by `frames.invalidate()`), `bardb.py` (coverage SQL),
  `analytics/score.py`, `jobs/defs/screens_run.py`, `jobs/defs/housekeeping.py`, and the API modules
  dashboard, data, jobs, news, positions, signals, sources, watchlist, screens, custom_indicators.
- `PUT /api/sources/{name}/secrets` writes `data/secrets.json`, which fails on Vercel (read-only
  file system). Cloud secrets need another home (env vars or a DB table): a ticket for later.
- Custom indicators aren't loaded on Vercel, so a rule that names one fails validation there (save a
  screen, describe a rule, `/prices?indicators=`). Option: load the approved rows' names and params
  on Vercel without ever running their code.
- `POST /api/jobs/refresh` is ~53 statements: about 5 per job enqueued, all inside `runner.enqueue`. A
  `runner.enqueue_many` (one transaction) would bring it to ~10.
- The frontend doesn't know the runtime, so the job wait text says "cloud worker" locally too (for the
  second or so a local job waits). Exposing `runtime` (it's in `/api/health`) to the UI would fix that.
- `/api/signals/summary` and `/signals/ideas` read the whole signal log in one statement: fine now,
  revisit past ~50k signals. `/api/ai/prompt` is at 41 statements; N010 should not add to it.
- `bars_coverage` row counts read 0 on Vercel until the first `housekeeping` run. N020 could run
  housekeeping once after the seed.
- Flaky test, not touched here: `tests/test_dbdriver.py::test_executemany_upsert_and_empty` failed once
  (sqlite3.ProgrammingError) in four full runs and passes on its own.
