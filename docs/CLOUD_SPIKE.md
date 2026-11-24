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
