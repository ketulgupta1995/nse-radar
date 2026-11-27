# Cloud spike results (N001)

Run with `scripts/spike_cloud.py`. Only timings, status codes and booleans are recorded here.

## 1. libsql driver (checked from the laptop, 2026-11-24, `libsql` 0.1.11)

| Check | Result | Consequence |
|---|---|---|
| Rows | plain `tuple`; no `row_factory` attribute | N002's wrapper must build `sqlite3.Row`-like rows from `cursor.description` |
| Errors | `ValueError("Hrana: … SQLite error: UNIQUE constraint failed … code: SQLITE_CONSTRAINT")`, `… no such table … SQLITE_UNKNOWN` | map by message: `SQLITE_CONSTRAINT` / "constraint failed" → `sqlite3.IntegrityError`, other SQLite errors → `sqlite3.OperationalError` |
| `lastrowid`, `rowcount`, `description` | work | — |
| `isolation_level=None` + `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK` | work remotely and on the replica | `db.tx()` unchanged |
| PRAGMAs (remote) | `foreign_keys=ON` and `user_version` OK; `journal_mode`, `busy_timeout`, `synchronous`, `cache_size` **refused** (`SQL not allowed statement`) | remote `connect()` sends only `foreign_keys=ON` |
| `executemany` | **one round trip per row** (1,000 rows: 18–20 s to Mumbai, even inside a transaction; 200 rows to US-East from India: 89 s) | wrapper rewrites `INSERT … VALUES (?,…)` into chunked multi-row `VALUES` (5,000–16,000 rows in 0.3 s in one statement); other statements → one `executescript` batch |
| Multi-row `INSERT … VALUES (…),(…)` | 16,000 rows / 32,000 params in 0.33 s (Mumbai, from India) | the bulk path |
| `executescript` of 500 UPDATEs | applied all 500; one batch | batch path for non-INSERT `executemany` (literals inlined safely: int/float/None/str/bytes) |
| Embedded replica | first sync of a small DB 0.8 s; reads local (< 1 ms); read-your-write inside a transaction ✔; remote sees replica writes ✔; replica sees remote writes after `sync()` ✔ | works for Actions |
| Replica **single** writes | each write is forwarded to the primary: ~110 ms to Mumbai, ~1.1 s to US-East from India | writes must be batched (same wrapper); row-by-row write loops in jobs are the thing to watch in the first drains |
| Turso plan | "embedded syncs" quota **3 GB/month** besides reads/writes | a full replica sync of the ~370 MB seed uses ~12%, so the Actions cache of the replica matters |

## 2. Where the database lives

A remote statement costs about **3–4 network round trips** (India → Mumbai: RTT ~80 ms, statement ~100–150 ms; India → US-East: RTT ~260 ms, statement ~900 ms). So the DB must sit next to the code that queries it, not next to the owner:
- GitHub-hosted runners and Vercel's default function region (`iad1`, Washington DC) are both in the US East.
- **Decision:** the nse-radar database lives in a new Turso group `us` at **aws-us-east-1** (created 2026-11-24; the free plan allowed it). Vercel functions stay in `iad1`. The owner's browser makes one ~250 ms trip to Vercel; the 10–50 queries behind a page are then local to the region.
- Confirm with the Actions latency check below.

## 3. Data sources

| Source | From the laptop (honest UA) | From GitHub Actions |
|---|---|---|
| UDiFF bhavcopy (last 3 trading days) | 200, ~210 KB each | 200, same sizes (0.1–1.3 s) |
| Nifty 500 list CSV | 200 | 200 |
| NSE corporate actions API (TCS) | 200 | 200 |
| NSE announcements API (TCS, 7 days) | 200 | 200 |
| NSE XBRL file | 200 | 200 |
| Screener.in company page | 200 | 200 |
| RSS: ET Markets, Business Standard | 200 | 200 |
| yfinance TCS.NS 1 month | 21 rows | 21 rows |

Run 45408652532 (2026-11-24): runner 4 CPUs, 16.4 GB RAM, 93 GB free disk, Python 3.13. Turso latency from the runner to aws-us-east-1 (`/health`, warm): **62 ms** (runners aren't always in US East; the first drains in N020 measure real statement times).

## Decisions
- Driver: **libsql**, remote on Vercel, embedded replica in Actions, behind the N002 wrapper (row objects, error mapping, batched `executemany`).
- DB region: **aws-us-east-1** (group `us`).
- Sources: **every source answers the honest User-Agent from GitHub Actions.** No fallback needed.

## First drain (N020, 2026-11-24) and the lazy-transaction fix (2026-11-25)

The first real drain (run 45415461408, Turso freshly seeded) took **104 min** and hit its time budget. That covered 7 of 15 jobs: the bhavcopy catch-up (11 days in 12 min), the index, announcements, news, events and event factors (22 min with no network items). `price_checks` reached 184 of 500 symbols in 64 min and then failed with `interactive transaction was rolled back because the stream was idle for too long`.

Why: on the embedded replica, every write, `BEGIN`, `COMMIT` and every read *inside* an open transaction goes to the primary, and each connection also sent `PRAGMA foreign_keys=ON` to the primary. `db.tx()` always opened `BEGIN IMMEDIATE`, so every read the jobs did (whole price histories in `price_checks`, settings in `get_setting`, the once-a-second stop check) was a network read. That was slow, it used Turso's monthly read quota, and it kept a remote transaction open while pandas worked, which caused the idle timeout.

Measured from the laptop against the spike DB (India to aws-us-east-1, so about 10× a runner's latency):

| Step | Cost |
|---|---|
| new replica connection | 2 ms |
| `PRAGMA foreign_keys=ON` on it | ~1.9 s (remote) |
| read outside a transaction | < 1 ms (local) |
| `BEGIN IMMEDIATE` + read + `COMMIT` | ~2.2 s |
| one `executescript` with `BEGIN; …; COMMIT` | one round trip (~0.9 s), even with 2,000 statements (~3.9 s) |
| `sync()` with nothing new | ~0.3 s |

Behaviour found on the way (libsql 0.1.11, replica):
- Turso enforces foreign keys and `ON DELETE CASCADE` **without** the PRAGMA.
- `executescript` **does not raise** when a statement fails. It stops, the primary rolls the batch back, and the connection's `in_transaction` stays `True`. The old batched `executemany` path could therefore drop writes silently.

Fix (`app/dbdriver.py`, `db.tx()`): no PRAGMA per connection, and on the replica `db.tx()` is a lazy transaction. Reads run on the local file, writes are held, and COMMIT sends them as one checked `BEGIN IMMEDIATE; …; COMMIT` batch. If `in_transaction` is still set afterwards, the batch is replayed statement by statement to raise the real error. A transaction that needs `rowcount` / `lastrowid` or reads after writing goes remote and runs as before. Because reads are local, the drain calls `sync()` before picking each job, and a running job syncs every 15 s to see stop requests from the site. `price_checks` now does all its reads before its writes.

Same laptop measurements after the fix: a read-only transaction takes 7 ms instead of ~4 s, and 1 read + 8 writes takes 2.3 s instead of ~12 s.

### Two more read-after-write paths (2026-11-27)

The same effect remained in two places, measured with the fake replica in `tests/test_replica_roundtrips.py`:
- `refresh_event_factors` deleted every universe symbol's rows first, then read corporate actions and price histories, so the whole job ran remotely: 442 round trips for 40 symbols. It now computes everything first and writes at the end: 1 round trip.
- `save_bars` called `bardb.ensure_source` and `bardb.symbol_ids`, which always wrote (`INSERT OR IGNORE`) and then read the ids back, so every by-symbol price fetch went remote: 10.3 round trips per symbol. They now read first and insert only new names: 2.3 per symbol (the save batch and `ctx.item`).

Also on 2026-11-27: by-symbol universe jobs that are meant to refresh every stock each run (`bars.yfinance`, the weekly `actions.*` and `fundamentals.yfinance`) were capped at the default `max_items` = 200, so 300 of the Nifty 500 waited up to 2.5 runs or weeks. They now use `WHOLE_UNIVERSE` = 600. `quarters.nse_api` went from 30 to 60 per drain, because the cloud runs it 12 times a week, not hourly.
