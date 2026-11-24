# Cloud routes: what each API route costs on Vercel (N009)

SPEC §17.5 says a Vercel request makes at most ~50 SQL statements, never loads frames for more than a
few symbols, never touches the price store and never loops over `bar_symbols` in Python. Heavy work is
a job that runs in the cloud worker (the GitHub Actions drain, §17.3), and the UI reads its results.

**How the numbers were measured.** `backend/tests/test_route_weight.py` seeds a fixture DB (60
universe stocks with 300 days of bars, 40 on the watchlist, 30 open and 10 closed positions, 60
signals, 30 news items, 30 backtests). It switches to vercel mode, clears every cache before each call
(a cold instance), and counts every `execute`/`executemany` plus one per connection (Turso runs
`PRAGMA foreign_keys` on connect). On remote Turso each statement is a round trip (~20 ms or more).
The test fails if any GET route goes over 50, or if a GET route is missing from its list.

**Vercel-mode rules that apply to every route (§17.2):**
- The price store is off (`price_store.enabled()` is false: validating it reads every bar).
- Every price-derived cache (frames, breadth, industries, indicator memo, `frames.memo` answers, and
  `registry.ordered` source orders) is dropped once it is `frames.VERCEL_CACHE_TTL_S` = 300 s old, and
  at once by `frames.invalidate()`.
- Custom indicators are never loaded or run. Approving one is a job (see below).

Column guide. **Light**: within budget on the request path. **Job**: the request only enqueues; the
work runs in the worker. "Statements" is the measured count on the fixture (GET routes) or a spot
check (write routes). "Snapshot" means a value a job saved in an internal settings key; internal keys
never appear in `GET /api/settings`.

## GET routes

| Route | What it reads | Statements | Light/heavy | On Vercel |
|---|---|---:|---|---|
| `/api/health` | schema version | 3 | light | as local |
| `/api/me` | the session cookie only | 0 | light | as local |
| `/api/cloud/status` | queued/running counts, dispatch settings | 6 | light | as local |
| `/api/jobs` | registry; schedules, newest run per job, running runs, source on/off | 19 | light (was 123: three queries per job) | batched: one query each for schedules, last runs and running runs; on/off read once per source |
| `/api/jobs/status` | runner status; newest bar day (key seek per source × symbol) | 6 | light | the newest-day answer is reused for up to 5 min (`frames.memo`): the header polls this every 5–60 s |
| `/api/jobs/runs`, `/runs/{id}`, `/runs/{id}/items`, `/runs/{id}/logs` | `job_runs`, `job_items`, `job_logs` | 4–5 | light | as local. Pages poll `/runs/{id}` while a job runs |
| `/api/sources` | registry, `source_state`, 7-day `source_fetch` counts per source | 31 | light | as local |
| `/api/sources/priority` | settings | 4 | light | as local |
| `/api/sources/coverage?capability=bars` | locally: a scan of every bar | 3 | **heavy locally**, light on Vercel | symbols, first and last day come from two key seeks per (source, symbol); `rows` comes from the housekeeping job's daily count (snapshot `bars_coverage`; 0 until the first run). Reused for 5 min |
| `/api/sources/coverage?capability=index\|fundamentals\|quarters` | `GROUP BY` over the small tables | 4 | light | as local |
| `/api/symbols/search` | `symbols` (LIKE, limit 20) | 4 | light | as local |
| `/api/symbols/{sym}` | one stock's frame, instrument, watchlist, open position, next results | 30 | light (one frame) | as local |
| `/api/prices/{sym}` | one stock's frame, benchmark if rel_strength, splits | 31 | light (one frame) | as local. A custom indicator in `indicators=` is unknown on Vercel (400) |
| `/api/fundamentals/fields`, `/api/indicators`, `/api/rules/ops` | code only | 0 | light | as local. `/indicators` lists no custom indicators on Vercel |
| `/api/fundamentals/{sym}` | one stock's fundamentals, quarters, snapshots | 7 | light | as local |
| `/api/screens` | screens, result counts, last-run setting | 6 | light | as local |
| `/api/screens/{id}/results` | the screen's results + the shortlist score | 15 | light (was 168: one frame per candidate) | score from the snapshot (below) |
| `/api/shortlist` | screen results, backtest excess, candidates' fundamentals and names, next results | 14 | light (was 108) | price columns come from the snapshot `score_prices`, which `screens_run` saves after every run. Weights, screens, fundamentals and backtest excess are read live. Empty until the first `screens_run` in the cloud. Fundamentals and names are now read for candidates only (both modes) |
| `/api/score/components` | settings | 4 | light | as local |
| `/api/dashboard` | positions (+ latest closes), unseen alerts, shortlist, data status, the "since last visit" lists | 42 | light (was 207) | positions use batched closes; "moves since your visit" use `frames.closes_on` (no frames); shortlist from the snapshot; data status reads only the newest day and open checks (reused 5 min); small reads share one connection |
| `/api/watchlist` | watchlist rows + latest close + close on the day added | 10 | light (was 65: one frame per stock) | `frames.latest_closes` / `frames.closes_on`: one key-seek statement for all stocks and all bars sources, adjusted for later splits |
| `/api/positions` (open) | positions, entry checklists, next results, latest closes | 13 | light (was 89) | entry checklists read in one query (was one per position); batched closes |
| `/api/positions?status=closed` | closed positions, their checklists | 4 | light | as local |
| `/api/positions/checklist/questions` | preset file | 0 | light | as local |
| `/api/positions/suggest` | one stock's frame (ATR), settings, next results | 28 | light (one frame) | as local |
| `/api/positions/{pid}/checklists` | that position's checklists | 5 | light | as local |
| `/api/journal/stats` | closed positions + their checklists | 4 | light | checklists read in one query (was three per position) |
| `/api/alerts`, `/alerts/count`, `/alerts/kinds` | `alerts` | 0–4 | light | as local |
| `/api/news/categories`, `/news/announcements` | categories file, `announcements` | 0–4 | light | as local |
| `/api/news/items` | `news_items` + their symbols | 5 | light (was 1 + one per item) | symbols for all items in one query |
| `/api/data/health` | counts of small tables; per source: symbols with bars, newest day | 14 | light (was a scan of every bar) | the bars part is one key seek per (source, symbol) instead of a scan (same answer, both modes); the whole answer is reused for 5 min on Vercel |
| `/api/data/checks`, `/data/unparsed-actions`, `/data/event-factors`, `/data/symbol-changes` | small tables | 4–5 | light | as local |
| `/api/backtests`, `/backtests/exits`, `/backtests/{id}` | `backtests` rows (equity/trades only for one) | 0–5 | light | as local |
| `/api/signals` | signals page (limit 200) + latest close per stock | 7 | light (was 84: one frame per stock) | batched closes |
| `/api/signals/summary` | every signal with its outcome, benchmark dates | 9 | light | as local. Reads the whole signal log in one statement: fine at today's size, revisit past ~50k signals |
| `/api/signals/ideas` | every signal grouped into ideas, latest close for the page | 6 | light (was 73) | batched closes. Same whole-log note as above |
| `/api/settings` | one statement per setting | 22 | light | as local |
| `/api/custom-indicators` | `custom_indicators` | 4 | light | as local (static check only, never run) |
| `/api/ai/status`, `/ai/tasks`, `/ai/requests`, `/ai/requests/{id}` | settings, provider check, `ai_requests` | 0–8 | light | as local. The provider is copy-prompt on Vercel (N010) |
| `/api/ai/prompt` (GET and POST) | the task's context: one stock's frame, fundamentals, quarters, news | 41 / 37 | light (one frame) | as local. The closest to the limit; N010 builds on it |

## Write routes (POST / PUT / DELETE)

| Route | What it does | Statements | Light/heavy | On Vercel |
|---|---|---:|---|---|
| `POST /api/login`, `/logout` | cookie only | 0 | light | as local (N008) |
| `POST /api/screens/preview` | locally it was a 20-second universe scan on the request | 5 | **heavy → job** | validates the rule (400 at once), then enqueues `screen_preview` and returns `{run_id}`. The job writes one `ok` item per matching stock (key = symbol, detail = values JSON). The Screener shows "Waiting for the cloud worker…" / "Running in the cloud worker…", polls `GET /jobs/runs/{id}`, then reads `GET /jobs/runs/{id}/items?status=ok`. One code path: the local worker runs it too |
| `POST /api/custom-indicators/{id}/approve` | locally it ran the code (trial run) on the request | ~5 | **heavy → job** (custom code never runs on Vercel) | checks that need no execution answer at once (400); then enqueues `indicator_approve` and returns the indicator plus `run_id`. The job trial-runs, approves and registers it; its message carries the 5 sample values or the reason. The review modal polls the run, then re-reads the indicator: approved, or still pending with the reason |
| `POST /api/backup` | `sqlite3` file copy of `DB_PATH` | 0 | n/a on Vercel | **409** "Backups run weekly in the cloud worker" (N011 adds the weekly job). Locally unchanged |
| `POST /api/screens/{id}/run`, `/screens/{id}/backtest`, `/backtests`, `/backtests/batch`, `/backtests/{id}/final`, `/jobs/{name}/run`, `/jobs/runs/{id}/retry`, `/ai/requests` | insert rows and enqueue a job | 5–17 | light (job) | already enqueue-and-poll: the drain runs `screens_run`, `backtest`, `backtest_batch`, `ai_request`… (`dispatch.kick` after commit, §17.4) |
| `POST /api/jobs/refresh` | enqueues every refresh job (~10) | 53 | light-ish (about 5 statements per job enqueued) | source on/off read in one transaction (was one per job). The rest is `runner.enqueue` per job; see the planner notes |
| `POST /api/jobs/runs/{id}/stop`, `/jobs/pause`, `PUT /jobs/{name}/schedule` | one or two row updates | ≤ 8 | light | as local |
| `POST /api/screens`, `PUT /screens/{id}`, `DELETE /screens/{id}`, `POST /rules/describe` | validate rule, write one row | 0–7 | light | as local. A rule naming a custom indicator fails validation on Vercel (not loaded) |
| `POST /api/watchlist`, `DELETE /watchlist/{sym}` | one row, `frames.invalidate()` | 4–6 | light | as local |
| `POST /api/positions`, `/positions/{id}/close`, `PUT /positions/{id}` | checklist + position rows, then the position view | ~18 | light | as local (batched close) |
| `POST /api/alerts/seen`, `/dashboard/visit` | one update | 4 | light | as local |
| `PUT /api/settings` | validate, write settings | ~23 | light | as local |
| `PUT /api/sources/priority`, `PUT /sources/{name}` | settings / `source_state`, `frames.invalidate()` | ~6 | light | as local (also clears the cached source orders) |
| `PUT /api/sources/{name}/secrets` | writes `data/secrets.json` | small | light | **fails on Vercel**: the function's file system is read-only. See the planner notes |
| `POST /api/data/checks/{id}`, `/data/manual-adjustment`, `/data/symbol-change` | one or two rows, `frames.invalidate()` | small | light | as local |
| `POST /api/custom-indicators`, `/custom-indicators/{id}/reject`, `DELETE /custom-indicators/{id}`, `DELETE /backtests/{id}` | one row (static check only) | ≤ 6 | light | as local |

## Snapshots written by jobs (internal settings keys)

| Key | Written by | Read by (Vercel) | Shape |
|---|---|---|---|
| `score_prices` | `screens_run`, after every run (`score.save_prices`) | shortlist, dashboard, screen results | `{"at", "prices": {symbol: {close, rs63, rs126, sma50, sma200, sma_slope, pct_from_high}}}` |
| `bars_coverage` | `housekeeping`, daily (`bardb.COVERAGE_SQL`) | `/api/sources/coverage?capability=bars` | `{"at", "rows": {source: bar count}}` |
