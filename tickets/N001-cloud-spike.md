# N001: Cloud spike: Turso driver and data sources from GitHub Actions
Cloud · Depends on: none · **Opus + owner** (needs the GitHub repo, a Turso DB and secrets; not for a headless worker)

## Goal
Before any cloud code is written, prove the two assumptions everything else rests on, and record the answers in `docs/CLOUD_SPIKE.md`:
1. The `libsql` Python package can stand in for `sqlite3` behind `db.connect()`, both **remote** (Vercel) and as an **embedded replica** (Actions).
2. NSE, Screener.in, Yahoo and the RSS feeds answer the honest User-Agent from a GitHub-hosted runner.

## Read first
SPEC §17 (all), §3.1, `backend/app/db.py`, `backend/app/sources/http.py`

## Files
- `scripts/spike_cloud.py` (new). `--db` runs the driver checks, `--sources` runs the source checks, `--report` prints the stored results. Results are written as one JSON row into a scratch table `cloud_spike(id INTEGER PRIMARY KEY, at TEXT, where_run TEXT, result TEXT)` in Turso, so they can be read from the laptop without scraping Actions logs. The script prints only status codes, timings and booleans: no data rows (§17.8).
- `.github/workflows/spike.yml` (new): `workflow_dispatch` only. Ubuntu, Python 3.13, `pip install -e backend libsql`, runs `--db --sources` with the Turso secrets, and records `nproc`, `free -g` and `df -h` too.
- `docs/CLOUD_SPIKE.md` (new): the results and the decisions below.
- `backend/pyproject.toml`: add `libsql` to the dependencies.

## Checks
**Driver (`--db`; run locally against Turso first, then in Actions):**
- remote `libsql.connect(TURSO_URL, auth_token=…)`: `execute`/`executemany`/`fetchone`/`fetchall`; explicit `BEGIN IMMEDIATE … COMMIT` and `ROLLBACK` with `isolation_level=None`; `cursor.lastrowid` and `rowcount`; whether `row_factory = sqlite3.Row` works or rows are plain tuples (then the N002 wrapper must build Row-like objects); which exception class a UNIQUE violation and a "no such table" raise; which PRAGMAs from `db.connect()` are accepted remotely; the median latency of 20 sequential `SELECT 1`s
- embedded replica `libsql.connect("data/spike-replica.db", sync_url=…, auth_token=…)` + `conn.sync()`: first-sync time and size for the seeded DB (or a 100k-row test table if not seeded yet); read-your-write inside a `BEGIN IMMEDIATE` transaction; the cost of a second sync after 10 remote writes
- Turso dashboard usage before and after (row reads/writes), to learn how a replica sync is counted

**Sources (`--sources`, Actions only), one polite request each through `app.sources.http` with the honest UA:** UDiFF bhavcopy for the last trading day, the Nifty 500 list CSV, `corporates-corporateActions` (TCS), `corporate-announcements` (TCS, 7 days), one XBRL file, one Screener company page, a yfinance 1-month download for `TCS.NS`, and each default RSS feed. Record the HTTP status and bytes.

## Decisions to record (with the owner)
- **Driver:** libsql remote for Vercel? Replica for Actions? If the replica misbehaves inside transactions, the fallback for Actions is remote writes plus a local read-only SQLite mirror of `bars` kept in the Actions cache, and N002 changes accordingly (Opus updates SPEC §17.2/§17.3 first).
- **Sources:** for each source refused from Actions (403/blocked), the owner picks: drop it, use the next source in `source_priority`, or rethink. Never work around a refusal (§3.1).

## Notes for the planner
