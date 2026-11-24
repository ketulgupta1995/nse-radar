# Adding a data source

A source is **one adapter file, its fixtures and a `cases.json`**. You never edit `main.py`, any `__init__.py`, the jobs code or the API: the app finds the adapter, builds its jobs and lists it on the Sources page by itself (SPEC §2.4, §3.4).

Worked example: `backend/tests/contract/example_source.py` with `backend/tests/fixtures/sources/example/`.

## 1. Add a source, or just reorder priorities?
- The data is already available from a source we have → **don't add one**. Change the order on the Sources page (setting `source_priority`).
- A site gives data we don't have, or a second opinion we want to cross-check against → add a source.
- Sources are never merged inside one price series: per symbol the first source in priority order that has bars wins (SPEC §3.5).

## 2. Pick a `name` and capabilities
- `name` matches `^[a-z][a-z0-9_]{1,30}$` and is **permanent**. It is stored in every `source` column, so never rename it.
- Capabilities, with their mode: `universe` (whole) · `bars` (by_date or by_symbol) · `actions` (by_symbol) · `index` (whole) · `fundamentals` (by_symbol) · `quarters` (by_symbol) · `announcements` (by_symbol) · `news` (whole) · `symbol_changes` (whole) · `events` (whole).
- Implement only the methods for the capabilities you declare. Everything else keeps raising `NotImplementedError`.

## 3. Write the adapter: `backend/app/sources/adapters/<name>.py`
- Subclass `BaseSource` and finish the file with `registry.register(MySource())`.
- Return only the normalized records from `sources/base.py` (`SymbolRow`, `Bar`, …). Uppercase symbols, ISO dates (`YYYY-MM-DD`), timestamps with a UTC offset (announcements and news).
- Convert units to the §9.4 units (₹ crore, percent, …) **inside the adapter**. Fundamentals field names must be in §9.4.
- Set `adjusted` on `bars` honestly: `True` only if the source already adjusts for splits and bonuses.
- Network calls go through `sources/http.py` (`http.get`, `http.get_json`). Map failures with `from_fetch_error(e)`:
  - 401 / 403 / 429 → `SourceRefused` (the job stops and the source is paused)
  - 404 → `NotFound` (no data for this key: a holiday, an unlisted symbol)
  - anything else, including parse errors → `SourceError` (this key fails, the run goes on)
- Put non-trivial parsing (HTML, XML, CSV quirks) in `backend/app/sources/parsers/<name>.py` as pure functions that take bytes and return plain data, so they can be tested alone.
- A library that doesn't use `http.py` (like yfinance) must throttle itself and wrap its errors into the three exceptions above.

## 4. Declare jobs and network policy
- Each `CapabilitySpec` has `JobVariant`s; each variant becomes one job named `<capability>.<name>[.<suffix>]`.
  - `schedule`: `{"kind": "daily", "at_time": "19:30", "weekdays_only": 1}`, `{"kind": "interval", "interval_min": 60}`, `{"kind": "weekly", "weekday": 0, "at_time": "08:00"}` or `{"kind": "manual"}`
  - `max_items`: keys per run. Keep it small enough to finish in a sensible time at your rate limit.
  - `min_age_hours`: skip keys fetched OK more recently than this.
  - `scope`: `universe`, `watch` (watchlist + open positions) or `none`.
  - `refresh=True` only for quick jobs the owner wants in "Refresh now".
  - by_date sources: set `history_start`, and add a `recent_days` variant (daily catch-up) and a `backfill` variant (history, runs at the lowest priority).
- `http_policies = {"host": HttpPolicy(min_interval_s, timeout_s, retries)}`. Be conservative: a slow polite fetch beats a ban.

## 5. Secrets
- List the credential names in `secrets = ("API_KEY",)`. The Sources page shows a box for each.
- Read them with `self.secret("API_KEY")`. **Never log them, never put them in an error message, never return them.**
- If a listed secret is missing, the generated job fails with "missing credentials: API_KEY" before any request.

## 6. Fixtures and `cases.json`
Save real samples (a few KB each) under `backend/tests/fixtures/sources/<name>/`, then write `cases.json` there:
```jsonc
{"transport": {"https://host/path/file.csv": {"status": 200, "file": "file.csv"}},   // exact URL first, then longest prefix; unmapped URL -> 404
 "cases": [{"capability": "universe", "args": {}, "expect": {"min_rows": 3, "symbols": ["AAA"]}},
           {"capability": "bars", "args": {"d": "2026-11-06"}, "expect": {"min_rows": 3}},
           {"capability": "bars", "args": {"d": "2026-11-07"}, "expect": {"raises": "NotFound"}}],
 "refusal": {"capability": "bars", "args": {"d": "2026-11-06"}}}   // the suite serves 403 for everything and expects SourceRefused
```
- `args` by capability: bars by_date `{"d"}` · bars by_symbol `{"symbol","start","end"}` · actions/fundamentals `{"symbol"}` · quarters `{"symbol","known":[]}` · announcements `{"symbol","since"}` · index `{"start"}` · universe/news/symbol_changes/events `{}`. Dates are `YYYY-MM-DD`.
- `expect`: `min_rows` (default 1), `symbols` (must all be present) or `raises` (`NotFound`, `SourceError`, `SourceRefused`).
- Every declared capability needs at least one passing case.
- No network in tests, ever. If the adapter doesn't use `http.py`, add `fixtures/sources/<name>/fake.py` with `install(monkeypatch, fixtures_dir)` (and optionally `install_refusal(monkeypatch, fixtures_dir)` to make every call refuse).
- **A source without `cases.json` fails the suite.**

## 7. Run the checks
```bash
cd backend
.venv/bin/pytest tests/contract -q      # contract suite for every source
.venv/bin/pytest -q && .venv/bin/ruff check app tests
```
The suite checks record types, ISO dates, finite numbers, uppercase symbols, bar sanity (`low ≤ open, close ≤ high`, `volume ≥ 0`), split/bonus factors in (0, 1], fundamentals field names, timestamp offsets and the refusal path.

## 8. After merging
- The source appears on the **Sources page** (enable/disable, secrets, last status). Set its place in the priority list there.
- Its jobs appear on the **Jobs page**, grouped under the source, with schedules the owner can pause.
- New data flows through `sources/store.py`, so prices, charts and screens pick it up without further code.

## 9. Etiquette
- Honest User-Agent (already set by `http.py`). No browser impersonation, no cookie harvesting, no headless browsers, no workarounds for bot protection.
- If a site refuses, record it and stop; don't get around it. Read the site's terms and keep to public pages.
- Respect rate limits (§3.1) and prefer bulk files over per-symbol calls where the site offers them.

## 10. Ticket template: "Add source X"
Copy into `tickets/T0NN-adapter-<name>.md` and fill in the blanks.
```markdown
# T0NN: `<name>` adapter (<what it provides>)
Phase N · Depends on: T012 (and T0MM if it needs another source's data) · Model: sonnet

## Goal
<one sentence: which data, from which site, for which capabilities>

## Read first
SPEC §3.2, §3.3 (adapter row), §3.7, docs/ADDING_A_SOURCE.md, <any parser spec>

## Files
- `backend/app/sources/adapters/<name>.py`
- `backend/app/sources/parsers/<name>.py` (if parsing is non-trivial)
- `backend/tests/fixtures/sources/<name>/` (real samples + `cases.json`)
- `backend/tests/test_<name>.py` (parser unit tests)
- `docs/DATA_SOURCES.md` (add what you learned about the site)

## Requirements
- Capabilities: <list with modes>; `adjusted=<True|False>` for bars
- Endpoints: <URLs, params>; host policy <seconds between requests>
- Jobs: <variants with schedule, max_items, min_age_hours, refresh>
- Units: <conversions to §9.4 / record units>
- Errors: 401/403/429 → SourceRefused, 404 → NotFound, parse failure → SourceError

## Tests
- `pytest tests/contract -q` passes for `<name>`
- <parser cases: normal, empty, malformed>

## Manual check (needs the owner's OK; only for tickets that touch the network)
<one real request, record the result in docs/DATA_SOURCES.md>
```
