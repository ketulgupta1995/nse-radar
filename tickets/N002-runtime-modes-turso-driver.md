# N002: Runtime modes and the Turso driver behind `db.connect()`
Cloud · Depends on: N001 · Model: sonnet

## Goal
The same code talks to a local SQLite file (tests, dev), to Turso remotely (Vercel) or to a Turso embedded replica (Actions), chosen only by environment variables (SPEC §17.2). Every existing test still runs on plain SQLite, unchanged.

## Read first
SPEC §17.2, §4 (`db.py` contract), `docs/CLOUD_SPIKE.md` (the driver findings: follow them where they differ from this ticket, and note it), `backend/app/config.py`, `backend/app/db.py`, `backend/tests/conftest.py`

## Files
- `backend/app/config.py`: `RUNTIME`, `TURSO_URL`, `TURSO_TOKEN`, `REPLICA_PATH`, `GITHUB_REPO` exactly as §17.2, plus `USER_AGENT = "nse-radar/0.1 (personal research; single user; low rate)"`
- `backend/app/dbdriver.py` (new): `connect_turso() -> Connection-like`, which wraps a libsql connection so callers see the sqlite3 surface the code uses: `execute`, `executemany`, `executescript`, cursors with `fetchone`/`fetchall`/iteration/`lastrowid`/`rowcount`/`description`, and rows that behave like `sqlite3.Row` (`row["col"]`, `row[0]`, `keys()`, `dict(row)`). libsql errors are re-raised as `sqlite3.IntegrityError` / `sqlite3.OperationalError` (matched on the message), so the existing `except sqlite3.…` blocks keep working. Remote mode skips the file PRAGMAs (WAL, synchronous, cache_size, journal_size_limit) and keeps `foreign_keys=ON` if Turso accepts it. Replica mode uses `REPLICA_PATH` + `sync_url`.
- `backend/app/db.py`: `connect()` returns `dbdriver.connect_turso()` when `config.TURSO_URL` is set, else today's sqlite3 connection. New `sync() -> None` (replica: `conn.sync()`; otherwise a no-op). `init_db()` raises `RuntimeError("migrations run in the drain, not on Vercel")` when `RUNTIME == "vercel"`. New `schema_status() -> str` (`"ok"` or `"update pending"`, comparing `user_version` with `SCHEMA_VERSION`).
- `backend/app/api/health.py`: add `"runtime"` and `"schema"` (from `schema_status()`) to the response.
- `backend/pyproject.toml`: `libsql` (already added in N001; check)
- `.env.example` (new, repo root): every variable from §17.2/§17.5 with a comment, no values
- `.gitignore`: add `.env*` (but not `.env.example`), `.vercel/`, `data/`
- Tests: `backend/tests/test_dbdriver.py` (new). Fake the libsql module with a tiny in-memory stand-in built on sqlite3 that returns plain tuples and raises its own exception class, to test row wrapping, error mapping, `lastrowid`/`rowcount` and driver selection by env. No network.

## Requirements
- With no `TURSO_DATABASE_URL`, behaviour is byte-for-byte today's: all 753+ backend tests pass untouched.
- No import of `libsql` at module import time in local mode (import inside `connect_turso`), so tests don't need it installed to pass.

## Notes for the planner
