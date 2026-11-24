# nse-radar: Specification

> nse-radar is the cloud copy of stock-tools (Vercel + Turso + GitHub Actions). **Read §17 first:** it overrides the laptop-only statements below (no cloud hosting, threads, local SQLite file, `claude` CLI).

This document is the single source of truth. Tickets refer to it as `SPEC §N`.
If a ticket and this spec disagree, **the spec wins**. Stop and tell the user rather than inventing a third answer.
A ticket may only change this spec if it says so explicitly.

**Design principle: plug-ins everywhere.** Anything likely to change later (data sources, jobs, indicators, alerts, score parts, AI back-ends, backtest exits, presets) is an **extension point**. Each one is a small registry with auto-discovered modules or JSON presets (§2.4). Adding or swapping one should mean *adding a file*, not editing many.

---

## §1 What this is

This is a **local, single-user research app** for Indian stocks (NSE). It runs on the owner's laptop, under WSL2, in the browser.

**Purpose:** to stay informed and get **data-backed, tested** stock ideas for holding periods of **a few weeks to 3–4 months**.

**Hard non-goals.** Never build any of these:
- No buying or selling, no orders and no broker account connection: no holdings sync, no orders. (A future *market-data-only* API key is allowed as a data source, §3.)
- No intraday or day-trading features. Daily bars only.
- No accounts and no multi-user support. (Cloud hosting on free tiers is allowed since 2026-11-24, §17: one owner, one password.)
- No Anthropic API key. AI goes through the local `claude` CLI on the owner's Pro plan (§11).

**The owner:** reads Python code but is not comfortable with the maths. Every indicator, metric and score therefore has a **one-line plain-English explanation** in the UI (`explain`). All configuration is editable in the UI.

**Universe:** the **Nifty 500** constituents, plus any symbol on the owner's watchlist or held in their positions.
**Benchmark:** the Nifty 500 index. It is used only as a yardstick ("vs just holding the index") and is never presented as something to buy.

---

## §2 Architecture

```
browser (React, Vite build) ──HTTP /api──▶ FastAPI (uvicorn, 127.0.0.1:8600)
                                            ├── api/        REST routers (auto-mounted)
                                            ├── jobs/       queue + single worker thread + scheduler thread
                                            ├── sources/    source framework + adapters/ (ALL network access)
                                            ├── analytics/  adjust, frames, indicators, rules, screens, fundamentals, score
                                            ├── alerts/     alert scanners (auto-discovered)
                                            ├── backtest/   engine, exits, costs, metrics
                                            ├── ai/         providers/ (claude_cli) + tasks/ (prompt builders)
                                            └── db.py       one SQLite file: data/stock.db
```

- One process. FastAPI starts two daemon threads on startup (skipped when `STOCK_NO_THREADS=1`, as in tests):
  - the **job worker**, which runs one job at a time
  - the **scheduler**, which enqueues due jobs every 30 s
- SQLite runs in WAL mode, with each thread using its own connection.
- In production FastAPI serves `frontend/dist`, and every path that is not `/api/*` falls back to `index.html`. In dev, Vite on 5173 proxies `/api` to 8600.
- All times are stored as **ISO-8601 strings in IST with offset** (`2026-11-09T19:30:00+05:30`). Trading dates are stored as `YYYY-MM-DD`.

### §2.1 Repo layout (fixed: do not rename or move)

```
nse-radar/
  AGENTS.md  CLAUDE.md  README.md  start.sh  .gitignore
  .claude/settings.json          # model: sonnet (workers)
  docs/SPEC.md  docs/DATA_SOURCES.md  docs/ADDING_A_SOURCE.md
  tickets/README.md  tickets/T0NN-*.md
  scripts/run-ticket.sh
  data/                          # gitignored: stock.db, secrets.json, raw/, backups/
  backend/
    pyproject.toml
    app/
      __init__.py  main.py  config.py  db.py  schema.sql  timeutil.py  plugins.py
      api/        __init__.py + one module per area (each defines `router`; auto-mounted under /api)
      jobs/       __init__.py  context.py  registry.py  runner.py  scheduler.py  defs/ (auto-imported)
      sources/    __init__.py  http.py  base.py  registry.py  store.py  jobs.py  secrets.py
                  adapters/ (auto-imported: nse_archives.py nse_bhav.py nse_api.py yfinance.py screener.py rss.py)
                  parsers/  (pure parsing helpers: bhavcopy.py actions.py xbrl.py screener_html.py)
      analytics/  __init__.py  adjust.py  frames.py  indicators.py  rules.py  explain.py
                  screens.py  fundamentals.py  score.py  custom_indicators.py
      alerts/     __init__.py  base.py  scanners/ (auto-imported)
      backtest/   __init__.py  costs.py  exits.py  engine.py  metrics.py
      ai/         __init__.py  base.py  providers/ (auto-imported: claude_cli.py)  tasks/ (auto-imported)
      presets/    screens.json  checklist.json  announcement_categories.json
    tests/        test_*.py, contract/, fixtures/ (fixtures/sources/<adapter>/ per adapter)
  frontend/
    package.json  vite.config.ts  tsconfig.json  index.html
    src/ main.tsx  App.tsx  routes.tsx  api/client.ts  api/types.ts  components/  pages/  lib/
  api/ vercel.json .github/      # cloud deployment (§17.10)
```

### §2.2 Tooling

- **Python 3.11.** Create a venv at `backend/.venv` with `python3 -m venv backend/.venv`, then install with `backend/.venv/bin/pip install -e "backend[dev]"`.
- Runtime dependencies: `fastapi`, `uvicorn[standard]`, `httpx`, `pandas`, `numpy`, `pydantic>=2`, `yfinance`, `beautifulsoup4`, `lxml`, `feedparser`.
- Dev dependencies: `pytest`, `ruff`.
- Do not add any other dependency unless a ticket allows it.
- Backend checks (run from `backend/`): `.venv/bin/pytest -q` and `.venv/bin/ruff check app tests`.
- **Frontend:** Node 22 and npm, with `react`, `react-dom`, `react-router-dom`, `lightweight-charts`, `typescript`, `vite`, `@vitejs/plugin-react`, `vitest`, `@testing-library/react` and `jsdom`. No UI library and no CSS framework. Use plain CSS (`src/styles.css`) with CSS variables, in light and dark themes.
- Frontend checks (run from `frontend/`): `npm run build` (`tsc --noEmit && vite build`) and `npm test` (`vitest run`).
- `start.sh` builds the frontend if `dist` is missing or older than `src`, then runs `backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8600` with cwd `backend/`.
  - `--background` runs it detached (`nohup`, log to `data/logs/app.log`, PID in `data/app.pid`). It does nothing if the app is already answering `/api/health`.
  - `--stop` stops it.
  - `--dev` runs uvicorn `--reload` + vite.
- **Auto-start (optional, the owner installs it):** `scripts/install-autostart.ps1` registers a Windows Task Scheduler task for the current user at logon, running `wsl.exe -d <distro> -- bash -lc "cd ~/ketul/claude_projects/stock-tools && ./start.sh --background"`. `scripts/uninstall-autostart.ps1` removes it. These are never run automatically.

### §2.3 Config (`app/config.py`)

```python
ROOT = Path(__file__).resolve().parents[2]           # stock-tools/
DATA_DIR = Path(os.environ.get("STOCK_DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "stock.db"
SECRETS_PATH = DATA_DIR / "secrets.json"
RAW_DIR = DATA_DIR / "raw"
TZ = ZoneInfo("Asia/Kolkata")
HISTORY_START = date(2010, 1, 1)
USER_AGENT = "stock-tools/0.1 (personal research; single user; low rate)"
```
Tests set `STOCK_DATA_DIR` to a tmp dir (fixture in `tests/conftest.py`).
`app/timeutil.py` provides `now() -> datetime` (aware, IST), `now_iso() -> str` and `today() -> date`. **Everything** that needs the current time calls these. Tests monkeypatch `app.timeutil.now`.

### §2.4 Extension points (the plug-in pattern)

**Auto-discovery (`app/plugins.py`):**
```python
def import_all(package: str) -> list[ModuleType]   # imports every non-underscore module in the package (pkgutil), sorted by name; returns them
```
- `main.py` lifespan calls these, in this order: `import_all("app.sources.adapters")`, `import_all("app.jobs.defs")`, `sources.jobs.register_source_jobs()`, `import_all("app.alerts.scanners")`, `import_all("app.ai.providers")`, `import_all("app.ai.tasks")`.
- `main.py` also mounts every `router` found by `import_all("app.api")` under `/api`, at app creation time, not in the lifespan.
- **So a ticket that adds a job, an adapter, an API module, a scanner, an AI provider or an AI task never edits `main.py` or any `__init__.py`.**

| Extension point | Where | Registry / contract | Add one by |
|---|---|---|---|
| Data source | `sources/adapters/*.py` | `BaseSource` + `sources.registry.register` (§3.2) | one adapter file + fixtures + contract cases (`docs/ADDING_A_SOURCE.md`) |
| Job | `jobs/defs/*.py` | `JobDef` + `jobs.registry.register` (§6.1) | one module |
| Source job | generated | `CapabilitySpec.jobs` (§3.4) | declare a `JobVariant` on the adapter |
| API area | `api/*.py` | module-level `router = APIRouter()` | one module |
| Indicator | `analytics/indicators.py`, or `custom_indicators` (AI, approved) | `IndicatorDef` (§8.1) | one `register(...)` call |
| Rule operator | `analytics/rules.py` `OPS` | `OpDef(name, words, fn)` (§8.2) | one dict entry |
| Fundamental field | `analytics/fundamentals.py` `FIELDS` | field dict (§9.4) | one entry; adapters may then fill it |
| Score component | `analytics/score.py` `COMPONENTS` | `ScoreComponent` (§10) | one entry + weight key |
| Alert kind | `alerts/scanners/*.py` | `AlertScanner` + `alerts.base.register` (§13.2) | one module |
| AI back-end | `ai/providers/*.py` | `AIProvider` (§11) | one module; pick it in Settings |
| AI task | `ai/tasks/*.py` | `AITask` (§11) | one module |
| Backtest exit | `backtest/exits.py` `EXITS` | `ExitDef` (§12.2) | one entry |
| Announcement category | `presets/announcement_categories.json` | keyword rules (§13.2) | edit JSON |
| Checklist question | `presets/checklist.json` | §13.1 | edit JSON |
| Screen preset | `presets/screens.json` | §10 | edit JSON |
| Frontend page | `frontend/src/routes.tsx` | `{path, label, nav, element}` array; nav is built from it | one entry + page file |

**Rule:** core code must never mention a specific source, provider or scanner by name. It asks the registry. The only exceptions are default settings values (§5).

---

## §3 Data sources

### §3.1 Network rules (all fetching goes through `sources/http.py`)

```python
class HttpPolicy(NamedTuple):
    min_interval_s: float   # minimum gap between requests to this host
    timeout_s: float
    retries: int            # on 429/5xx/timeouts: exponential backoff 2s, 4s, 8s…

POLICIES: dict[str, HttpPolicy] = {"*": HttpPolicy(1.0, 20, 2)}   # adapters add their hosts at registration (§3.2)
def add_policy(host: str, policy: HttpPolicy) -> None

class FetchError(Exception): ...            # .status (int|None), .url
def get(url: str, *, params: dict | None = None, headers: dict | None = None, accept: str = "*/*") -> bytes
def get_json(url: str, *, params: dict | None = None, headers: dict | None = None) -> Any
def set_transport(fn: Callable[[str, dict | None, dict], tuple[int, bytes]] | None) -> None   # tests: fn(url, params, headers) -> (status, body); None restores default
```
- Send `User-Agent: config.USER_AGENT`. **Do not impersonate a browser** or work around bot protection: no spoofed browser UA, no cookie harvesting from homepages and no headless browsers. `headers` exists for legitimate API keys only.
- A 401 or 403 is a refusal: raise `FetchError` with no retry.
- A 404 raises `FetchError(status=404)` with no retry.
- Rate limits are per host, process-wide and thread-safe.
- **Tests never touch the network.**

### §3.2 Source framework (`sources/base.py`, `sources/registry.py`)

**Normalized records.** Every adapter returns these, and nothing else leaves an adapter.
```python
Capability = Literal["universe","bars","actions","index","fundamentals","quarters","announcements","news","symbol_changes","events"]

@dataclass(frozen=True)
class SymbolRow:    symbol: str; name: str; industry: str | None = None; isin: str | None = None
@dataclass(frozen=True)
class Bar:          symbol: str; date: str; open: float; high: float; low: float; close: float
                    volume: float | None = None; value: float | None = None; trades: int | None = None
@dataclass(frozen=True)
class Action:       symbol: str; ex_date: str; subject: str
                    kind: Literal["split","bonus","demerger","rights","other","unparsed"]; factor: float | None   # multiplier for prices BEFORE ex_date; None for demerger/rights (§7.2a computes it)
@dataclass(frozen=True)
class IndexBar:     index_name: str; date: str; close: float
@dataclass(frozen=True)
class SymbolChange: old_symbol: str; new_symbol: str; effective_date: str; name: str | None = None   # ticker rename (T077)
@dataclass(frozen=True)
class Event:        symbol: str; date: str; purpose: str; description: str | None = None   # board meeting from the event calendar (T095)
@dataclass(frozen=True)
class FundSnapshot: symbol: str; fields: dict[str, float | str | None]   # keys = §9.4 field names ONLY, already in §9.4 units
                    detail: dict                                            # source-specific extras for the UI (tables), JSON-able
@dataclass(frozen=True)
class Quarter:      symbol: str; period_end: str; consolidated: bool; period_start: str | None = None
                    audited: bool | None = None; filing_date: str | None = None; url: str | None = None
                    revenue: float | None = None; other_income: float | None = None; total_expenses: float | None = None
                    pbt: float | None = None; net_profit: float | None = None; eps: float | None = None   # ₹ crore; eps ₹
                    parse_error: str | None = None
@dataclass(frozen=True)
class Announcement: symbol: str; ts: str; headline: str; body: str | None = None; url: str | None = None
                    category: str | None = None   # None -> core categorizer (§13.2)
@dataclass(frozen=True)
class NewsItem:     feed: str; ts: str; title: str; url: str; summary: str | None = None
```

**Errors adapters raise:**
```python
class SourceRefused(Exception): ...      # site refused us (401/403/429) -> the job stops and the source is paused
class NotFound(Exception): ...           # this key has no data (holiday, unlisted symbol, missing page) -> item 'skipped'
class SourceError(Exception): ...        # anything else (parse failure, timeout) -> item 'failed'
def from_fetch_error(e: FetchError) -> Exception   # 401/403/429 -> SourceRefused, 404 -> NotFound, else SourceError
```

**Adapter declaration:**
```python
@dataclass(frozen=True)
class JobVariant:
    suffix: str = ""                  # job name = f"{capability}.{source}" + (f".{suffix}" if suffix else "")
    title: str = ""                   # e.g. "daily", "backfill", "watchlist"
    scope: Literal["universe","watch","none"] = "universe"   # symbol set; none = source-wide call
    schedule: dict = field(default_factory=lambda: {"kind": "manual"})
    max_items: int = 200              # per run
    min_age_hours: float = 20         # skip keys fetched OK more recently than this
    params: dict = field(default_factory=dict)   # variant-specific, passed to the job runner (§3.4)
    refresh: bool = False             # included in "Refresh now" (§6.4): quick, user-visible freshness jobs only

@dataclass(frozen=True)
class CapabilitySpec:
    capability: Capability
    mode: Literal["by_symbol","by_date","whole"]
    jobs: tuple[JobVariant, ...]
    adjusted: bool | None = None      # bars only: True = prices already split/bonus adjusted by the source
    history_start: str | None = None  # by_date only: earliest date to backfill

class BaseSource:
    name: str              # stable id stored in DB `source` columns, e.g. "nse_bhav". Never rename.
    label: str             # "NSE bhavcopy"
    description: str       # one plain line
    homepage: str
    capabilities: tuple[CapabilitySpec, ...]
    http_policies: dict[str, HttpPolicy] = {}
    secrets: tuple[str, ...] = ()      # credential names this source needs (§3.6)
    default_enabled: bool = True
    # implement only the methods for declared capabilities (others raise NotImplementedError):
    def universe(self) -> list[SymbolRow]
    def bars_for_date(self, d: date) -> list[Bar]                                  # mode by_date
    def bars_for_symbol(self, symbol: str, start: date, end: date) -> list[Bar]    # mode by_symbol
    def actions(self, symbol: str) -> list[Action]
    def index_bars(self, index_name: str, start: date) -> list[IndexBar]           # index_name is always "NIFTY 500" in v1
    def fundamentals(self, symbol: str) -> FundSnapshot
    def quarters(self, symbol: str, known_periods: set[str]) -> list[Quarter]      # skip re-downloading known period_ends
    def announcements(self, symbol: str, since: date) -> list[Announcement]
    def news(self) -> list[NewsItem]
    def symbol_changes(self) -> list[SymbolChange]                                 # mode whole (T077)
    def events(self) -> list[Event]                                                # mode whole (T095)
    def secret(self, key: str) -> str | None        # helper -> sources.secrets.get(self.name, key)
```

**Registry (`sources/registry.py`):**
```python
def register(src: BaseSource) -> BaseSource      # also http.add_policy for its hosts; adapters call at import
def get(name: str) -> BaseSource
def all_sources() -> list[BaseSource]
def spec(name: str, capability: str) -> CapabilitySpec | None
def ordered(capability: str, conn=None) -> list[BaseSource]
    # enabled sources having the capability, in `source_priority[capability]` order, then any others by name
def is_enabled(name: str, conn=None) -> bool     # source_state.enabled (row created from default_enabled on first access)
```

### §3.3 Built-in adapters

These facts were verified live on 2026-11-09 unless marked *unverified*. Notes are in `docs/DATA_SOURCES.md`.

| adapter `name` | capabilities (mode) | endpoints / notes | jobs (variants) |
|---|---|---|---|
| `nse_archives` | universe (whole); index (whole); symbol_changes (whole) | Nifty 500 list `https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv`, with columns `Company Name,Industry,Symbol,Series,ISIN Code`. Index closes `…/content/indices/ind_close_all_{DDMMYYYY}.csv` (*unverified*). Ticker changes `https://nsearchives.nseindia.com/content/equities/symbolchange.csv`, columns `NAME OF THE COMPANY,OLD SYMBOL,NEW SYMBOL,EFFECTIVE DATE` (date `DD-MON-YYYY`; verified 2026-11-10, ≈1,080 rows, includes non-equity instruments). Host policy 1.0 s. | universe: weekly Mon 08:00, min_age 144 h, **refresh**. index: daily 20:00 weekdays, **refresh**. symbol_changes: weekly Mon 08:10, min_age 144 h |
| `nse_bhav` | bars (by_date, **adjusted=False**, history_start 2010-01-01) | UDiFF ≥ 2024-07-08: `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip`. Old: `…/content/historical/EQUITIES/{YYYY}/{MON}/cm{DD}{MON}{YYYY}bhav.csv.zip`. 404 = holiday. | `daily`: daily 19:30 weekdays, params `{"recent_days":30,"not_before":"18:30","weekends":true}`, **refresh**. `backfill`: interval 60, max_items 400, params `{"newest_first":true,"weekends":true}` |
| `nse_api` | actions (by_symbol); quarters (by_symbol); announcements (by_symbol); events (whole) | base `https://www.nseindia.com/api`: `corporates-corporateActions?index=equities&symbol=`, `corporates-financial-results?index=equities&period=Quarterly&symbol=` (with `xbrl` URL per item), `corporate-announcements?index=equities&symbol=` (date params `from_date/to_date=DD-MM-YYYY` *unverified*), `event-calendar` (T095; verified 2026-11-11: a list of `{symbol, company, purpose, bm_desc, date}` with date `DD-Mon-YYYY`, ≈600 upcoming board meetings about 3 weeks ahead, purpose e.g. "Financial Results", "Financial Results/Dividend", "Buyback"). Host policy 2.0 s for www.nseindia.com, 1.0 s for nsearchives. | actions: weekly Sat 09:00, min_age 144 h. quarters: interval 60, max 30, min_age 168 h. announcements `watch`: interval 90, scope watch, min_age 1 h, params `{"days":7}`, **refresh**; `all`: daily 22:30, scope universe, max 500, min_age 20 h, params `{"days":3}`. events: daily 08:30, min_age 20 h, **refresh** |
| `yfinance` | bars (by_symbol, **adjusted=True**); actions (by_symbol); index (whole); fundamentals (by_symbol) | `yfinance` library, tickers `{SYM}.NS`, index `^CRSLDX` (*unverified*). It doesn't use `http.py`, so it throttles itself to 1 call per second and wraps library errors into §3.2 errors. Yahoo lists bonuses as splits too. Yahoo invents flat, zero-volume bars on some NSE holidays (2014-04-24, 2014-10-15, 2026-01-15); `bars_for_symbol` drops rows with volume 0 and open = high = low = close (T082). | bars: daily 20:30 weekdays, **refresh**. actions: weekly Sat 10:00. index: daily 20:15 weekdays, **refresh**. fundamentals: weekly Sun 10:00 |
| `screener` | fundamentals (by_symbol) | `https://www.screener.in/company/{SYM}/consolidated/`, falling back to `/company/{SYM}/` if the quarters section is empty. Public pages only: no login, no export endpoints. Host policy 5.0 s. | fundamentals: interval 60, max 60, min_age 168 h |
| `rss` | news (whole) | feeds come from the `rss_feeds` setting (Moneycontrol was dropped in T040: its feed stopped updating in 2024; older databases keep it). If every feed fails, `news()` raises `SourceRefused` when all refused, else `SourceError`: ET Markets `https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms`, Business Standard `https://www.business-standard.com/rss/markets-106.rss` | news: interval 120, **refresh** |

**Usage pattern these schedules are built for:** the laptop isn't always on. The owner opens the app for about an hour most days, and the first load happens over a couple of days with the app left running. Overdue jobs run on startup in stage order (§6.1), and every job catches up gaps from what's stored (§3.4).

**Rough first-load budget with the app running:**
- bhavcopy backfill: ≈ 4,000 days at 400/h, about 10 h
- yfinance full history: 500 × 1 s, about 10 min
- quarters: 500 symbols at 30/h, about 17 h
- Screener: 500 at 60/h, about 9 h
- actions and announcements: about 20 min each

**Steady state** fits in about an hour a day.

### §3.4 Generated source jobs (`sources/jobs.py`)

```python
def register_source_jobs() -> None    # for every registered source × capability × JobVariant: jobs.registry.register(JobDef(...))
def run_source_job(ctx: JobContext, source: str, capability: str, variant: JobVariant) -> str
```
- Job name: `f"{capability}.{source}"`, plus `f".{suffix}"` when there's a suffix. Title: `f"{label}: {CAP_LABEL[capability]}"`, plus ` ({variant.title})` when there's a title. The description comes from the adapter and capability.
- **Before running:**
  - if the source is disabled, finish with "source disabled"
  - if a required secret is missing, finish with `failed` and "missing credentials: KEY"
- **Keys and freshness** come from the `source_fetch` table (§4): one row per (source, capability, key) holding the last status and time. They're never taken from job state, so every job is resumable.
- **Mode `by_symbol`:**
  - keys = symbols in `scope`: universe = `frames.universe()`; watch = watchlist ∪ open positions
  - order: never fetched first, then oldest `fetched_at`
  - skip keys with status `ok` or `not_found` fetched within `min_age_hours`
  - take at most `max_items`, or exactly `ctx.params["keys"]` on a retry
- **Mode `by_date`:** keys = weekdays (ISO dates). With variant param `"weekends": true` (T080), Saturdays and Sundays are keys too: NSE holds occasional weekend sessions (Budget day 2025-02-01, 2024-01-20, 2024-03-02, Muhurat 2016-10-30). A weekend with no session is a 404 → `not_found` and is never asked again. For `recent_days`, the window still spans the last N weekdays; with `weekends` the Saturdays and Sundays inside that span are added.
  - `recent_days` variant: the last N weekdays up to today, with today skipped before `not_before` IST, minus dates already `ok` or `not_found`.
  - `newest_first` variant: every weekday from `history_start` to yesterday with no `ok`/`not_found` row (or `failed` older than 1 day), newest first, capped at `max_items`.
- **Mode `whole`:** one key, `"all"`.
- **Calls per capability:**
  - bars by_symbol: `bars_for_symbol(sym, start=last stored date − 5 days or HISTORY_START, end=today)`. **Exception (T082):** for a source whose bars spec has `adjusted=True`, if `corp_actions` (any source) has a `split`/`bonus` row for the symbol with `ex_date` within the last 45 days, `start = HISTORY_START`: the source re-adjusts its whole history after a split, so the stored older rows must be replaced.
  - index: `index_bars("NIFTY 500", start=last stored − 5 days or HISTORY_START)`
  - quarters: `quarters(sym, known_periods={period_end with no parse_error})`
  - announcements: `announcements(sym, since=...)`, where `since` = (last `ok` fetched_at for this key − 1 day) if there is one, else today − `params.days`. It never goes earlier than today − 30 days, so a gap of days or weeks is caught up.
  - all others: their obvious method
- `recent_days` (by_date) covers **every** missing weekday in that window, so up to 30 days off are caught up by the daily job. Older gaps fall to the backfill variant.
- **Stage, lane and follow-ups** for generated jobs come from the capability (§6.1):

  | capability | stage | follow-ups (enqueued when the run stored ≥ 1 row) |
  |---|---|---|
  | universe | 0 | — |
  | symbol_changes | 0 | `price_checks`, `screens_run` |
  | bars | 1 | `event_factors`, `price_checks`, `screens_run` |
  | index | 1 | `screens_run` |
  | actions | 2 | `event_factors`, `price_checks` |
  | announcements, news | 3 | `alerts_scan` |
  | events | 3 | — |
  | fundamentals, quarters | 6 | `fundamentals_merge` |

  Lane is always `background`. The bhavcopy **backfill** variant uses stage 7, so history loading never delays fresh data.
- **Results** are saved through `sources/store.py`, one transaction per key. The `source_fetch` row is then written with the status (`ok`/`not_found`/`failed`) and row count.
- **Outcomes:**
  - `NotFound` → item `skipped` and fetch status `not_found`
  - `SourceError` / other exception → item `failed`, fetch status `failed`, and `source_state.last_error*` updated
  - `SourceRefused` → stop the run with "<label> refused (detail)". Then:
    - set `source_state.enabled=0` with `paused_reason`
    - `db.insert_alert("job_refused", …, dedupe_key=f"refused:{source}:{today}", severity="warn")`
    - the owner re-enables the source on the Sources page
- Call `ctx.check_stop()` between keys. On success, set `source_state.last_ok_at`.

### §3.5 Store and resolution (`sources/store.py`)

```python
def save(capability: str, source: str, records: list, *, key: str, conn) -> int   # dispatches to the writers below; returns row count
def save_universe(source, rows, conn)       # upsert symbols(name, industry, isin); if source is ordered("universe")[0]: set in_universe=1 for these, 0 for others
def save_bars(source, bars, conn)           # INSERT OR REPLACE into bars
def save_actions(source, actions, conn)     # upsert corp_actions
def save_index(source, bars, conn)          # upsert index_bars
def save_fundamentals(source, snap, conn)   # upsert fund_snapshots (fields + detail JSON); unknown field names dropped + logged
def save_quarters(source, quarters, conn)   # upsert quarters
def save_announcements(source, items, conn) # category = item.category or categorize(headline + body); INSERT OR IGNORE
# NSE announcement `desc` (stored as headline) is often generic ("Updates"); the UI shows the body's first line when it is.
# Other modules read category flags via the private `_categories()`; treat it as public (rename later if touched).
def save_news(source, items, conn)          # INSERT OR IGNORE news_items; link news_symbols via match_symbols (§13.3)
def save_symbol_changes(source, items, conn) # INSERT OR REPLACE symbol_changes; calls frames invalidate (T077)
def save_events(source, items, conn)        # one tx: DELETE this source's rows with date >= today (the calendar lists all upcoming
                                            # meetings; NSE reschedules), then INSERT OR REPLACE with fetched_at; past rows kept (T095)
def last_bar_date(source, symbol, conn) -> str | None
def last_index_date(source, conn) -> str | None
```

**Choosing which source to read (in `analytics/frames.py`):** per symbol, use **one** source for the whole series, never mixing sources inside a series. The chosen source is the first in `ordered("bars")` that has bars for the symbol, and the frame API reports it (`source`). Within that one source, a series follows the symbol's **ticker lineage** (§7.4): bars stored under the company's earlier tickers are joined on before the rename date (T077). The same applies to the index (`ordered("index")`), to actions (merged as described in §7.2), and to fundamentals (per field, §9.4).

### §3.6 Secrets (`sources/secrets.py`)

```python
def get(source: str, key: str) -> str | None
def set(source: str, key: str, value: str | None) -> None   # None deletes
def status(source: str) -> dict[str, bool]                   # key -> is set (never the value)
```
- Secrets are stored in `config.SECRETS_PATH` (JSON `{source: {key: value}}`, file mode 0600, gitignored with `data/`).
- **Values are never logged, never returned by any API, never included in AI prompts and never stored in SQLite.**

### §3.7 Adapter contract tests

- `tests/contract/test_adapters.py` is parametrized over `registry.all_sources()`. For each adapter it loads `tests/fixtures/sources/<name>/cases.json`:
  ```jsonc
  {"transport": {"<url or url-prefix>": {"status": 200, "file": "nifty500list.csv"}},   // served by http.set_transport
   "cases": [{"capability": "universe", "args": {}, "expect": {"min_rows": 400}},
             {"capability": "bars", "args": {"d": "2026-11-06"}, "expect": {"min_rows": 3, "symbols": ["TCS"]}},
             {"capability": "bars", "args": {"d": "2026-11-07"}, "expect": {"raises": "NotFound"}}],
   "refusal": {"capability": "bars", "args": {"d": "2026-11-06"}}}   // the suite serves 403 for everything and expects SourceRefused
  ```
- An adapter that doesn't use `http.py` (e.g. yfinance) provides `tests/fixtures/sources/<name>/fake.py` with `install(monkeypatch, fixtures_dir)`, which the suite calls instead of the transport map.
- **Generic assertions:**
  - the correct record types
  - ISO dates
  - finite numbers
  - uppercase symbols
  - bars with `low ≤ min(open, close)`, `max(open, close) ≤ high` and `volume ≥ 0`
  - actions with a factor in (0, 1] for split/bonus
  - `FundSnapshot.fields` keys ⊆ §9.4 fields
  - announcement and news timestamps carry an offset
- **An adapter with no `cases.json` fails the suite.** A source can't be added without passing.
- `docs/ADDING_A_SOURCE.md` (T012) is the recipe a worker follows for a new source.

---

## §4 Database

- `app/db.py`:
  ```python
  def connect() -> sqlite3.Connection   # row_factory=sqlite3.Row; PRAGMA foreign_keys=ON, journal_mode=WAL, busy_timeout=10000, synchronous=NORMAL, cache_size=-32768 (32 MB), journal_size_limit=64 MB. temp_store stays default (FILE): MEMORY makes VACUUM hold a whole DB copy in RAM
  def init_db() -> None                 # creates DATA_DIR/RAW_DIR/backups; applies schema.sql if user_version < SCHEMA_VERSION; VACUUMs after migrations that leave > 25% of the file empty (T121); seeds defaults
  @contextmanager
  def tx() -> Iterator[sqlite3.Connection]
  SCHEMA_VERSION = 12  # 2 = signal log tables (§16.1); 3 = symbol_changes (T077); 4 = corp_actions kinds + event_factors (T083/T084); 5 = instruments (T087a); 6 = event_factors method 'close' (T091); 7 = price_checks kind 'adjustment_jump' (T092); 8 = events (T095); 9 = backtests kind/parent_id/fingerprint (T113); 10 = drop redundant bars_symbol_date index (2026-11-23); 11 = compact bars: source_id + integer day (2026-11-23); 12 = bars: symbol ids, prices in paise, no day index (2026-11-23)
  def get_setting(key: str, conn=None) -> Any          # JSON-decoded; KeyError if unknown
  def set_setting(key: str, value: Any, conn=None) -> None
  def insert_alert(kind: str, message: str, *, dedupe_key: str, symbol: str | None = None,
                   link: str | None = None, severity: str = "info", conn=None) -> bool   # INSERT OR IGNORE; True if new
  ```
- `schema.sql` uses `CREATE TABLE IF NOT EXISTS`. Only tickets that say so may change it. A later schema change bumps `SCHEMA_VERSION` and adds an idempotent `migrations/NNN.sql` step. A step that can't be re-run safely starts with `-- skip-if-column: table.column` (skipped when that column already exists).
- **Migrations (T083):** `backend/app/migrations/NNN_name.sql`. `init_db` runs, in number order, every file with NNN > the DB's `user_version`, each in its own transaction, **before** re-running `schema.sql`, then sets `user_version = SCHEMA_VERSION`. A fresh DB (no tables yet) skips migrations: `schema.sql` already has the final shape. `004_corp_actions_kinds.sql` rebuilds `corp_actions` with the wider `kind` CHECK (SQLite cannot alter a CHECK): create `corp_actions_new`, copy all rows, drop the old table, rename.
- **Space after migrations (T121):** a migration that rewrites a big table (like 011/012) leaves the old pages as empty space inside the file, and nothing gives it back. So when at least one migration ran in this `init_db` call and `freelist_count / page_count > 0.25`, `init_db` runs `VACUUM` before returning (the app isn't serving yet), logging "Reclaiming N MB of empty space in the database (one-off, can take a few minutes)". VACUUM needs free disk of about 2× the live data (its temporary copy plus the WAL). With less, it skips, logs a warning and inserts a `db_space` alert (warn, dedupe `db_space:{date}`): "The database has N MB of empty space it couldn't reclaim. Free M MB of storage and restart the app." It runs with `temp_store` at its default (FILE); with MEMORY the whole copy sits in RAM (measured 2026-11-24: 202 MB peak for a 154 MB file, against 77 MB). Applies on the laptop and the phone.
- Every table is created in T002. **Each source-fed table has a `source` column**, so data from different sources sits side by side.

```sql
-- sources
CREATE TABLE IF NOT EXISTS source_state (
  source TEXT PRIMARY KEY, enabled INTEGER NOT NULL, paused_reason TEXT,
  last_ok_at TEXT, last_error_at TEXT, last_error TEXT);
CREATE TABLE IF NOT EXISTS source_fetch (
  source TEXT NOT NULL, capability TEXT NOT NULL, key TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','not_found','failed')),
  fetched_at TEXT NOT NULL, rows INTEGER, error TEXT,
  PRIMARY KEY (source, capability, key)) WITHOUT ROWID;

-- universe & prices
CREATE TABLE IF NOT EXISTS symbols (
  symbol TEXT PRIMARY KEY, name TEXT, industry TEXT, isin TEXT,
  in_universe INTEGER NOT NULL DEFAULT 0, updated_at TEXT);
-- bars is stored compactly (migrations 011/012, helpers in app/bardb.py): source and symbol as ids from bar_sources
-- and bar_symbols, the date as INTEGER YYYYMMDD, prices as paise (an INTEGER when whole, which every NSE price is;
-- else the exact float x100), volume an INTEGER, value INTEGER rupees. No secondary index: every lookup is a
-- primary-key seek (bardb.LAST_DAY_SQL for the newest day). Code keeps using source names, symbols, 'YYYY-MM-DD'
-- strings and float prices, converting at the SQL boundary (bardb.SRC_ID, SYM_ID, OHLCV_SQL, TRADED_SQL, day(),
-- iso(), paise(), MONTH_SQL). Never compare `day` with a text date.
CREATE TABLE IF NOT EXISTS bar_sources (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS bar_symbols (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS bars (
  source_id INTEGER NOT NULL, sym_id INTEGER NOT NULL, day INTEGER NOT NULL,
  open_p INTEGER, high_p INTEGER, low_p INTEGER, close_p INTEGER, volume INTEGER, value INTEGER, trades INTEGER,
  PRIMARY KEY (source_id, sym_id, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS corp_actions (
  source TEXT NOT NULL, symbol TEXT NOT NULL, ex_date TEXT NOT NULL, subject TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('split','bonus','demerger','rights','other','unparsed')), factor REAL,
  PRIMARY KEY (source, symbol, ex_date, subject));
CREATE TABLE IF NOT EXISTS instruments (              -- what each traded symbol is, from bhavcopy (T087a)
  symbol TEXT PRIMARY KEY, isin TEXT, series TEXT,       -- latest seen; isin 'INF…' = fund unit, series RR/IV = REIT/InvIT
  last_date TEXT NOT NULL, source TEXT NOT NULL);         -- upserted by save_bars only when the new date >= last_date
CREATE TABLE IF NOT EXISTS events (                   -- board meetings from the event calendar (T095)
  source TEXT NOT NULL, symbol TEXT NOT NULL, date TEXT NOT NULL, purpose TEXT NOT NULL, description TEXT,
  fetched_at TEXT NOT NULL, PRIMARY KEY (source, symbol, date, purpose));
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
CREATE TABLE IF NOT EXISTS event_factors (            -- derived demerger/rights factors (§7.2a, T084)
  symbol TEXT NOT NULL, ex_date TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('demerger','rights')),
  factor REAL, method TEXT NOT NULL CHECK (method IN ('reference','open','close','none')),   -- 'close' added in T091
  detail TEXT, computed_at TEXT NOT NULL, PRIMARY KEY (symbol, ex_date, kind)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS index_bars (
  source TEXT NOT NULL, index_name TEXT NOT NULL, date TEXT NOT NULL, close REAL NOT NULL,
  PRIMARY KEY (source, index_name, date)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS price_checks (
  id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, date TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('mismatch','unexplained_gap','adjustment_jump')),   -- 'adjustment_jump' added in T092
  primary_source TEXT, other_source TEXT, detail TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','ignored','fixed')),
  created_at TEXT, UNIQUE (symbol, date, kind));
CREATE TABLE IF NOT EXISTS manual_adjustments (
  symbol TEXT NOT NULL, ex_date TEXT NOT NULL, factor REAL NOT NULL, note TEXT, PRIMARY KEY (symbol, ex_date));
CREATE TABLE IF NOT EXISTS symbol_changes (          -- ticker renames (T077); source 'manual' = owner-added
  source TEXT NOT NULL, old_symbol TEXT NOT NULL, new_symbol TEXT NOT NULL, effective_date TEXT NOT NULL,
  name TEXT, note TEXT, PRIMARY KEY (source, old_symbol, new_symbol, effective_date)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS symbol_changes_new ON symbol_changes(new_symbol);

-- fundamentals
CREATE TABLE IF NOT EXISTS fund_snapshots (
  source TEXT NOT NULL, symbol TEXT NOT NULL, fetched_at TEXT NOT NULL,
  fields TEXT NOT NULL, detail TEXT NOT NULL, PRIMARY KEY (source, symbol));
CREATE TABLE IF NOT EXISTS quarters (
  source TEXT NOT NULL, symbol TEXT NOT NULL, period_end TEXT NOT NULL, consolidated INTEGER NOT NULL,
  period_start TEXT, audited INTEGER, filing_date TEXT, url TEXT,
  revenue REAL, other_income REAL, total_expenses REAL, pbt REAL, net_profit REAL, eps REAL, parse_error TEXT,
  PRIMARY KEY (source, symbol, period_end, consolidated));
CREATE TABLE IF NOT EXISTS fundamentals (          -- merged snapshot (§9.4)
  symbol TEXT PRIMARY KEY, updated_at TEXT NOT NULL, data TEXT NOT NULL, sources TEXT NOT NULL);

-- news
CREATE TABLE IF NOT EXISTS announcements (
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, symbol TEXT NOT NULL, ts TEXT NOT NULL, category TEXT NOT NULL,
  headline TEXT NOT NULL, body TEXT, url TEXT, UNIQUE (symbol, ts, headline));
CREATE TABLE IF NOT EXISTS news_items (
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, feed TEXT NOT NULL, ts TEXT NOT NULL,
  title TEXT NOT NULL, url TEXT NOT NULL UNIQUE, summary TEXT);
CREATE TABLE IF NOT EXISTS news_symbols (
  news_id INTEGER NOT NULL REFERENCES news_items(id) ON DELETE CASCADE, symbol TEXT NOT NULL,
  PRIMARY KEY (news_id, symbol));

-- owner data
CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, added_at TEXT NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checklists (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('entry','exit')), symbol TEXT NOT NULL,
  answers TEXT NOT NULL, ai_review TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, qty INTEGER NOT NULL CHECK (qty > 0),
  entry_date TEXT NOT NULL, entry_price REAL NOT NULL, stop REAL, target REAL, time_stop_date TEXT,
  entry_checklist_id INTEGER REFERENCES checklists(id),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  exit_date TEXT, exit_price REAL, exit_reason TEXT, exit_checklist_id INTEGER REFERENCES checklists(id),
  source_screen_id INTEGER, created_at TEXT NOT NULL);

-- screens, indicators, backtests
CREATE TABLE IF NOT EXISTS screens (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT, rule TEXT NOT NULL,
  is_preset INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL DEFAULT 'user' CHECK (created_by IN ('preset','user','ai')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS screen_results (
  screen_id INTEGER NOT NULL REFERENCES screens(id) ON DELETE CASCADE, symbol TEXT NOT NULL, as_of TEXT NOT NULL,
  values_json TEXT NOT NULL, first_seen TEXT NOT NULL, PRIMARY KEY (screen_id, symbol));
CREATE TABLE IF NOT EXISTS custom_indicators (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, params_schema TEXT NOT NULL, explain TEXT NOT NULL,
  code TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  created_at TEXT NOT NULL, approved_at TEXT);
CREATE TABLE IF NOT EXISTS backtests (
  id INTEGER PRIMARY KEY, name TEXT, config TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed','cancelled')),
  run_id INTEGER, metrics TEXT, equity TEXT, trades TEXT, warnings TEXT, created_at TEXT NOT NULL, finished_at TEXT,
  kind TEXT NOT NULL DEFAULT 'explore' CHECK (kind IN ('explore','final','legacy')),   -- T113, §12.6
  parent_id INTEGER, fingerprint TEXT);                                               -- T113: final -> its explore run

-- jobs
CREATE TABLE IF NOT EXISTS job_schedules (
  job TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('interval','daily','weekly','manual')),
  interval_min INTEGER, at_time TEXT, weekday INTEGER, weekdays_only INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1, next_run_at TEXT, last_run_id INTEGER);
CREATE TABLE IF NOT EXISTS job_runs (
  id INTEGER PRIMARY KEY, job TEXT NOT NULL, params TEXT NOT NULL DEFAULT '{}',
  trigger TEXT NOT NULL CHECK (trigger IN ('schedule','manual','retry','startup','system')),
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed','cancelled','interrupted')),
  queued_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  total INTEGER, done INTEGER NOT NULL DEFAULT 0, ok INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0, message TEXT, stop_requested INTEGER NOT NULL DEFAULT 0, retry_of INTEGER);
CREATE INDEX IF NOT EXISTS job_runs_job ON job_runs(job, id DESC);
CREATE TABLE IF NOT EXISTS job_items (
  run_id INTEGER NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE, key TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','skipped','failed')), detail TEXT, at TEXT NOT NULL,
  PRIMARY KEY (run_id, key));
CREATE TABLE IF NOT EXISTS job_logs (
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE,
  at TEXT NOT NULL, level TEXT NOT NULL CHECK (level IN ('info','warn','error')), msg TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS job_logs_run ON job_logs(run_id, id);

-- alerts & ai
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, symbol TEXT, message TEXT NOT NULL, link TEXT,
  severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warn','critical')),
  dedupe_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, seen_at TEXT);
CREATE TABLE IF NOT EXISTS ai_requests (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, symbol TEXT, payload TEXT, prompt TEXT NOT NULL, response TEXT,
  result TEXT,                                  -- JSON from the task's postprocess (§11)
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed','cancelled')),
  provider TEXT, model TEXT, run_id INTEGER, duration_s REAL, error TEXT, created_at TEXT NOT NULL);
```

---

## §5 Settings (key → JSON value; defaults seeded by `init_db`, in `db.DEFAULT_SETTINGS`)

| key | default | meaning |
|---|---|---|
| `capital_inr` | `500000` | capital for position sizing |
| `risk_per_trade_pct` | `1.0` | max % of capital lost if the stop is hit |
| `default_time_stop_weeks` | `8` | |
| `atr_stop_multiple` | `2.0` | suggested stop = entry − k×ATR(14) |
| `source_priority` | `{"universe":["nse_archives"],"bars":["nse_bhav","yfinance"],"actions":["nse_api","yfinance"],"index":["nse_archives","yfinance"],"fundamentals":["screener","yfinance"],"quarters":["nse_api"],"announcements":["nse_api"],"news":["rss"]}` | §3.2 `ordered()` |
| `fundamentals_field_priority` | `{"sales_growth_yoy_pct":["quarters","screener","yfinance"],"profit_growth_yoy_pct":["quarters","screener","yfinance"],"profit_positive_4q":["quarters","screener"]}` | per-field override (§9.4); `"quarters"` = derived from the quarters table |
| `ai_provider` | `"claude_cli"` | §11 |
| `ai_model` | `"sonnet"` | passed to the provider |
| `ai_timeout_s` | `240` | |
| `score_weights` | `{"rs":30,"trend":25,"fundamentals":30,"backtest":15}` | keys = §10 component names; a missing key means weight 0 |
| `rss_feeds` | list of `{name,url}` from §3.3 | |
| `jobs_paused` | `false` | global pause |
| `last_visit_at` | `null` | when the owner last left the Dashboard (§14 "Since you were away") |
| `signal_target_atr_multiple` | `4.0` | forward-test target = entry + k×ATR(14) (§16) |
| `position_exit_sma` | `100` | `trend_break` alert: warn when an open position closes below this many days' average; 0 = off, else 20–300 (T099) |
| `trail_atr_multiple` | `5.0` | `trail_hit` alert: highest close since entry − k×ATR14 at entry; 0 = off, else 1–15 (T099) |
| `holdout_start` | `"2022-01-01"` | default test-period start for new backtests (§12.6, T113) |
| `backtest_workers` | `3` | max worker processes for a `backtest_batch` job, clamped 1–6; 1 = never parallel (§12.2, T118) |
| `backup_every_days` | `7` | cloud (`actions` mode) only: make a backup only when the last successful one is at least this many days old; the runner keeps 1 file (§17.8, N011) |
| `cost_model` | `{"brokerage_pct":0.03,"brokerage_cap_inr":20,"stt_pct":0.1,"exchange_pct":0.00297,"sebi_pct":0.0001,"stamp_buy_pct":0.015,"gst_pct":18,"dp_charge_inr":15.93,"slippage_pct":0.10}` | §12.1 |

`GET /api/settings` returns all settings. `PUT /api/settings` takes a partial `{key: value}`, validates each key with a pydantic model, and returns all settings. Unknown keys get a 400. Source names in `source_priority` must be registered (400 otherwise).

---

## §6 Jobs framework

### §6.1 Interfaces

```python
# jobs/context.py
class StopRequested(Exception): ...
class JobContext:
    run_id: int
    params: dict
    def set_total(self, n: int) -> None
    def item(self, key: str, status: Literal["ok","skipped","failed"], detail: str | None = None) -> None
    def log(self, msg: str, level: Literal["info","warn","error"] = "info") -> None
    def check_stop(self) -> None          # re-reads job_runs.stop_requested at most once per second; raises StopRequested
    def stop_requested(self) -> bool

# jobs/registry.py
@dataclass(frozen=True)
class JobDef:
    name: str; title: str; description: str
    fn: Callable[[JobContext], str | None]      # returns final message
    default_schedule: dict                      # {"kind":"daily","at_time":"19:30","weekdays_only":1} etc.
    retryable: bool = True                      # honours params={"keys":[...]}
    group: str = "app"                          # "app" or "source:<name>" (UI groups jobs by this)
    stage: int = 5                              # lower runs first within a lane (§6.3); ties -> oldest queued first
    lane: Literal["background","interactive"] = "background"
    followups: tuple[str, ...] = ()             # job names enqueued (trigger "system") after a `done` run with ok > 0
def register(job: JobDef) -> JobDef             # duplicate name -> ValueError
def get(name: str) -> JobDef
def all_jobs() -> list[JobDef]

# jobs/runner.py
def enqueue(job: str, *, params: dict | None = None, trigger: str = "manual", retry_of: int | None = None) -> int
    # same job already queued/running with identical params (sorted-keys JSON) -> return that run id
def request_stop(run_id: int) -> None          # queued -> cancelled at once; running -> stop_requested=1
def run_one(lane: str = "background") -> int | None   # pick the queued run in this lane with lowest stage, then oldest; run it synchronously (tests call this)
def start_worker() -> None                     # idempotent: one daemon thread PER LANE looping run_one(lane); sleeps 1 s when idle
def status() -> dict                           # {"updating": bool, "background": {"running": RunSummary|None, "queued": n}, "interactive": {...}}
                                               # updating = any background run with stage <= 3 is queued or running
def recover_on_startup() -> None               # running -> 'interrupted' ("app restarted")
```
- Normal return gives `done`, `StopRequested` gives `cancelled`, and any other exception gives `failed` with the traceback logged.
- **One item failing never fails the run.**
- Resumable jobs work out their remaining work from data tables (`source_fetch` for source jobs).
- Retry: `POST /api/jobs/runs/{id}/retry` enqueues `params={"keys":[failed keys]}` with `trigger="retry"`.
- **Lanes:** `background` runs fetching and analysis one job at a time, which keeps requests to sites polite. `interactive` runs the things the owner clicked (`ai_request`, `backtest`), so they never wait behind downloads. Each lane runs one job at a time.
- **Follow-ups** make a pipeline. New prices → price checks + screens → alerts, and new fundamentals → merge → screens → alerts. Dedupe in `enqueue` stops repeats, and stage order makes follow-ups run after the fetches still queued.

### §6.2 Scheduler (`jobs/scheduler.py`)

```python
def compute_next_run(sched: dict, after: datetime) -> datetime | None   # pure, IST
def tick(now: datetime) -> list[int]   # one pass: if not jobs_paused, enqueue every enabled schedule with next_run_at <= now; set next from now
def start_scheduler() -> None          # daemon thread calling tick every 30 s
def ensure_schedules() -> None         # create missing job_schedules rows from default_schedule; fill null next_run_at
```
- Schedule kinds:
  - `interval`: `interval_min` after the run time
  - `daily`: the next `at_time`, skipping Sat/Sun if `weekdays_only`
  - `weekly`: `weekday` (0 = Mon) at `at_time`
  - `manual`: never runs on its own
- Missed runs are **not** replayed. A due job runs once after waking, and its next time is computed from now.
- **Startup catch-up:** `main.py` calls `tick(now())` once right after `ensure_schedules()`, then starts the thread. Every overdue job is queued immediately, and stage order turns the queue into a pipeline.
- Disabling a schedule doesn't touch a running job. `jobs_paused` stops scheduling, but "Run now" still works.
- A job whose source is disabled is shown with its schedule greyed out ("source off"). The scheduler still enqueues it, and it ends immediately with "source disabled". This keeps the scheduler source-agnostic.

### §6.3 Jobs

**App jobs** (in `jobs/defs/`):

| job | schedule | stage / lane | follow-ups | ticket |
|---|---|---|---|---|
| `housekeeping` | daily 03:00. Deletes runs/items/logs and `source_fetch` failures older than 90 days, and alerts seen more than 90 days ago. | 9 / background | — | T006 |
| `price_checks` | daily 21:00 weekdays_only | 4 / background | — | T019 |
| `price_checks_full` | weekly Sun 11:00. Same checks over the whole history (§7.3). | 4 / background | — | T079 |
| `event_factors` | manual (follow-up of bars and actions), §7.2a | 3 / background | — | T084 |
| `fundamentals_merge` | daily 23:30 | 6 / background | `screens_run` | T034 |
| `screens_run` | daily 21:30 weekdays_only | 7 / background | `signals_track` (was `alerts_scan` until T060) | T036 |
| `signals_track` | manual (follow-up of `screens_run`), §16.4 | 7 / background | `alerts_scan` | T060 |
| `alerts_scan` | interval 60 | 8 / background | — | T042 |
| `ai_request` | manual (enqueued by the AI API) | 0 / interactive | — | T044 |
| `backtest` | manual (enqueued by the backtest API) | 1 / interactive | — | T052 |
| `backtest_batch` | manual (enqueued by `POST /api/backtests/batch`); params `{"backtest_ids": [...]}`, explore rows only; progress is per config, §12.2 | 1 / interactive | — | T116 |
| `noop` | manual (tests and UI checks) | 5 / background | — | T005 |
| `backup` | daily 02:30. `VACUUM INTO` a `.tmp` copy, checked with `quick_check` and `user_version`, then gzip-compressed to `data/backups/stock-auto-YYYY-MM-DD.db.gz` (about half the size; restore with `gunzip -k`; since 2026-11-24). Keeps the newest 7 `stock-auto-*` (`.db.gz`, or older plain `.db`), never touches other files; skips if today's exists in either form; fails if free disk < 2× DB size; failure also inserts a `backup_failed` alert. Cloud: weekly, §17.8 | 9 / background | — | T094 |

Stage scale (background lane): 0 universe · 1 prices/index · 2 splits · 3 announcements/news · 4 price checks · 6 fundamentals fetch + merge · 7 screens and history backfill · 8 alerts · 9 housekeeping.

**Source jobs** are generated (§3.4) from the §3.3 table:
- `universe.nse_archives`, `index.nse_archives`, `symbol_changes.nse_archives`
- `bars.nse_bhav.daily`, `bars.nse_bhav.backfill`
- `actions.nse_api`, `quarters.nse_api`, `announcements.nse_api.watch`, `announcements.nse_api.all`, `events.nse_api`
- `bars.yfinance`, `actions.yfinance`, `index.yfinance`, `fundamentals.yfinance`
- `fundamentals.screener`
- `news.rss`

### §6.4 Jobs API

```
GET  /api/jobs                       -> {"paused": bool, "jobs": [{name,title,description,group,source_enabled|null,
                                         schedule:{kind,interval_min,at_time,weekday,weekdays_only,enabled,next_run_at},
                                         last_run: RunSummary|null, running: RunSummary|null}]}
PUT  /api/jobs/{name}/schedule       body partial schedule -> schedule (recomputes next_run_at; 400 on invalid)
POST /api/jobs/{name}/run            body {params?} -> {run_id}
POST /api/jobs/pause                 body {paused: bool} -> {paused}
GET  /api/jobs/runs?job=&status=&limit=50&before_id= -> [RunSummary]
GET  /api/jobs/runs/{id}             -> RunSummary + {items_failed:[{key,detail}]}
GET  /api/jobs/runs/{id}/items?status=&limit=200&offset= -> [{key,status,detail,at}]
GET  /api/jobs/runs/{id}/logs?after_id=0 -> [{id,at,level,msg}]
POST /api/jobs/runs/{id}/stop        -> RunSummary
POST /api/jobs/runs/{id}/retry       -> {run_id}   (400 if no failed items)
POST /api/jobs/refresh               -> {run_ids:[...]}   enqueue (trigger "manual") every registered job flagged refresh (JobVariant.refresh)
                                        for enabled sources; follow-ups do the rest. Works even when jobs_paused.
GET  /api/jobs/status                -> runner.status() + {"last_trading_date": ...}   (polled by the header indicator)
RunSummary = {id,job,trigger,status,queued_at,started_at,finished_at,duration_s,total,done,ok,skipped,failed,message,retry_of}
```
`source_enabled` is null for app jobs. For `group="source:<name>"` jobs, the job router looks it up through `sources.registry.is_enabled`. (The jobs API knows about the *registry*, never about specific sources.)

### §6.5 Sources API (`api/sources.py`)

```
GET /api/sources -> [{name,label,description,homepage,enabled,paused_reason,last_ok_at,last_error_at,last_error,
                      capabilities:[{capability,mode,adjusted,jobs:[job names]}], secrets:{key: is_set},
                      stats:{ok_7d, failed_7d, not_found_7d}}]        # stats from source_fetch
PUT /api/sources/{name}            body {enabled: bool} -> source        (enabling clears paused_reason)
PUT /api/sources/{name}/secrets    body {key: value|null} -> {key: is_set}   (400 for keys not in adapter.secrets)
GET /api/sources/priority          -> source_priority setting + {"capabilities": {cap: [all source names having it]}}
PUT /api/sources/priority          body {capability: [names]} -> priority     (validates names have the capability)
GET /api/sources/coverage?capability=bars -> [{source, symbols, first_date, last_date, rows}]   (bars/index/fundamentals/quarters)
```

---

## §7 Prices

### §7.1 NSE bhavcopy parsing (`sources/parsers/bhavcopy.py`, used by the `nse_bhav` adapter)

```python
UDIFF_START = date(2024, 7, 8)
def bhav_url(d: date) -> str
EQUITY_SERIES = ("EQ", "BE", "BZ", "RR", "IV")   # RR = REIT units, IV = InvIT units (T080)
def parse_bhav(content: bytes, d: date) -> list[Bar]   # zip or csv bytes; series in EQUITY_SERIES; format detected from header
```
- UDiFF format: filter `SctySrs in EQUITY_SERIES` and `FinInstrmTp == "STK"`, and map `TckrSymb, OpnPric, HghPric, LwPric, ClsPric, TtlTradgVol, TtlTrfVal, TtlNbOfTxsExctd`.
- Old format: filter `SERIES in EQUITY_SERIES`, and map `SYMBOL, OPEN, HIGH, LOW, CLOSE, TOTTRDQTY, TOTTRDVAL, TOTALTRADES`. The header has a trailing comma.
- **Why BE/BZ (T075):** a stock under exchange surveillance moves from EQ to the trade-for-trade series BE (or BZ) for weeks or years, then back. It is the same share and the same symbol. EQ-only parsing left holes of up to 600 trading days (80 universe stocks, 7,705 days) and turned each hole into a fake one-day jump.
- **Why RR/IV (T080):** NSE's Nifty 500 list includes REITs (BAGMANE, BIRET, EMBASSY in 2026). They trade as series RR; InvITs as IV. They are stored like shares.
- One bar per symbol per file: if a symbol appears in more than one of these series on the same day, keep the EQ row.
- The adapter stores **all symbols in these series** (≈ 2,000+ per day). Keep the non-universe rows: ticker lineage (§7.4) needs the bars of old tickers.

### §7.2 Adjustment (`analytics/adjust.py`)

```python
def adjustment_factors(symbol: str, conn) -> list[tuple[str, float]]
    # split/bonus actions, merged across sources: for each ex_date take the factor from the first source in
    # ordered("actions") that has a split/bonus row on that ex_date (±2 days counts as the same event);
    # manual_adjustments on an ex_date REPLACE source factors. Sorted by ex_date.
def adjusted_ohlcv(symbol: str, start: str | None = None, end: str | None = None, conn=None) -> tuple[pd.DataFrame, str]
    # (frame, source). Picks the bars source (§3.5). If that source's spec has adjusted=False: prices on dates < ex_date
    # are multiplied by the cumulative product of later factors, and volume divided by it. If adjusted=True: returned as is.
    # Frame: DatetimeIndex, float columns open, high, low, close, volume.
```
- Parsing action subjects into factors happens **inside adapters** (`sources/parsers/actions.py` for NSE). The rules (revised in T076):
  - Split "[from] Rs/Re A to Rs/Re B" after the word split / sub-division ("from" is optional; "Rs", "Re", "Rs." and "/-" all occur): factor = B / A
  - **Abbreviated wordings (T090)**, seen in NSE's older rows: "Fv Splt Frm Rs 10 To Rs 2", "Fv Spl-Rs10tors5", "Fv Spl Rs.5tors.2" (`splt`/`spl` after `fv` mean split, `frm` means from, and "to" may be glued to the amounts: `Rs10tors5`); "Bon-2:1", "Bon 1:1" (`bon` as a whole word means bonus). Combined forms like "Fv Spl-Rs10tors5/Bon-2:1" multiply as below (ENGINERSIN 2010-05-06 = 1/2 × 1/3 = 1/6).
  - Bonus "X:Y" (also "Bonus- X:Y", "Bonus - X:Y", "Bonus Shares In The Ratio Of X:Y", spaces around the colon): factor = Y / (X + Y)
  - **One subject can hold both** ("Bonus 1:1 / Face Value Split From Rs 10 To Rs 2"): factor = bonus factor × split factor, kind `split`. NSE never also lists the parts as separate rows for the same event (checked 2026-11-10), so multiplying within one subject never double counts. Separate rows on the same ex_date are multiplied by §7.2 merging as before.
  - Bonus **debentures**, **preference shares** and **NCRPS** are not equity bonuses: that part is ignored, and a subject with nothing else is `other`.
  - **Demergers (T083):** a subject with "demerger" or "scheme of arrangement" (incl. "composite scheme of arrangement") and no equity split/bonus becomes `demerger`, factor None. Bonus-debenture schemes stay `other`.
  - **Rights (T083):** a subject with "rights" (e.g. "Rights 19:67 @ Premium Rs 215 Per Share") becomes `rights`, factor None. The factor is not computed from the subject (the face value is missing, so the issue price is unknown); §7.2a derives it.
  - Dividends become `other` and are not adjusted (price-return, apart from demergers and rights)
  - A split/bonus keyword with no readable ratio becomes `unparsed`
- yfinance splits: `ratio` r means factor = 1 / r.
- `adjustment_factors` also includes `event_factors` rows with a non-NULL factor (§7.2a), for the symbol, after the split/bonus merge. A manual adjustment within ±2 days replaces them too.

### §7.2a Demerger and rights factors (`analytics/events.py` + job `event_factors`, T084)

Owner decision 2026-11-11: old prices are adjusted for demergers and rights issues, so these events stop looking like crashes. Adjustment happens **only on an ex-date the actions source lists** as `demerger` or `rights`; a price difference alone never creates one.
```python
def compute_event_factor(symbol: str, ex_date: str, kind: str, conn) -> tuple[float | None, str, dict]   # (factor, method, detail)
def refresh_event_factors(conn, symbols: list[str] | None = None) -> int                                   # upsert event_factors; returns rows written
```
- **Method `reference`:** the *reference source* = the first source after the primary in `ordered("bars")` whose spec has `adjusted=True` and that has bars for the symbol. Using the primary's series adjusted for splits/bonuses only (not for event factors) and the reference's closes on common dates: `before` = median(primary/reference) over the last 10 common dates before `ex_date`, `after` = the median over the first 10 common dates on or after it. `step = after / before`. Use it when `0.05 < step < 0.995` and both medians have ≥ 5 dates.
- **Method `open`** (demergers only, when `reference` gives nothing): `factor = open of the first primary bar on or after ex_date (within 5 days) / close of the bar before`. NSE's special pre-open session on a demerger day sets this price. Use it when `0.05 < factor ≤ 0.97`.
- **Sanity guard (T091, demergers only).** Yahoo's own demerger step is sometimes wrong (MOTHERSON 2022-01-14, ANANTRAJ 2020-10-06 and ADANIENT 2015/2018 left fake jumps of +11% to +220% on the ex-date). For a candidate factor f, with `prev_close` = the primary's last close before `ex_date` and the first primary bar on or after it (within 5 days) giving `ex_open`, `ex_close` (all split/bonus-adjusted, not event-adjusted): `open_move = ex_open / (prev_close·f) − 1`, `close_move = ex_close / (prev_close·f) − 1`. The candidate **passes** when `min(|open_move|, |close_move|) ≤ 0.10`. Order: `reference` (if it passes) → `open` (needs the existing range check **and** `|ex_close/ex_open − 1| ≤ 0.15`, because a bad pre-open print can sit far from the day's trading, e.g. ADANIENT 2015-06-03 opened at 573 and closed at 110) → **method `close`**: `factor = ex_close / prev_close` when `0.05 < factor ≤ 0.97`, **only when the open factor was in range but failed the open sanity check** (a bad open print). When the open factor is above 0.97 the demerger is small: leave it `none`, because the ex-day close then mostly measures the market's move → `none`. The `open` and `close` methods pass the guard by construction. A rejected reference keeps its numbers in `detail` plus `"rejected": "reference"` and the `open_move`/`close_move` it produced. Rights events skip the guard (their steps are small, and Yahoo applying them on the record date is a known 1–2 day offset).
- Otherwise `method='none'`, factor NULL: the event is listed but not adjusted (shown in the API so the owner can add a manual adjustment).
- `detail` JSON: `{"before":…, "after":…, "n_before":…, "n_after":…, "open":…, "prev_close":…, "reference": source name}` (keys present when computed).
- Events come from `corp_actions` rows of kind `demerger`/`rights` from **any** actions source, deduplicated per (symbol, kind) within ±2 days (earliest ex_date wins). `refresh_event_factors` recomputes all rows for the given symbols (default: `frames.universe()`), deleting rows whose event disappeared. Then `frames.invalidate()`.
- Job `event_factors`: stage 3, background, manual schedule; follow-up of bars and actions (§3.4). It ends with "N events: X adjusted (reference), Y adjusted (open), W adjusted (close), Z not adjusted" (the close count since T091).
- `GET /api/data/event-factors` -> `[{symbol, ex_date, kind, factor, method, detail}]` sorted by ex_date desc.

### §7.3 Cross-check (the `price_checks` job)

For each universe symbol with bars from at least 2 sources:
- **primary** = the source `adjusted_ohlcv` picks; **other** = the next source in `ordered("bars")` with data.
- Both are compared after adjustment (an `adjusted=True` source is used as is), over the last 400 common dates. The **full** variant (job `price_checks_full`, T078) compares every common date and scans gaps over the whole series, because old history is where missed splits hide.
- **`mismatch`:** `abs(primary/other − 1) > 0.02` holds for more than 3 consecutive days. That gives one row per streak, at its first date, with detail `{"ratio": median, "suggested_factor": round(median, 4)}`.
- **`unexplained_gap`:** the primary adjusted close moves more than 35% in a day with no split/bonus within ±3 days.
- **`adjustment_jump` (T092):** the gap check skips ex-dates, so a wrong factor there is invisible. This check looks only at ex-dates: every date in `adjustment_factors(symbol)` (split/bonus, event factors and manual adjustments, after the merge) for an unadjusted primary. Using the adjusted primary frame: `prev_close` = last close before the ex-date, the first bar on or after it within 5 days gives `ex_open`/`ex_close`. Flag when **both** `|ex_open/prev_close − 1| > 0.15` and `|ex_close/prev_close − 1| > 0.15`. Detail: `{"applied_factor": product of the factors within ±2 days, "open_move_pct", "close_move_pct", "suggested_factor"}` where `suggested_factor = round(applied_factor × ex_open/prev_close, 4)` (or `ex_close/prev_close` when `|ex_close/ex_open − 1| > 0.15`). The row's `date` is the ex-date. Applying it writes a manual adjustment, which replaces every factor within ±2 days (§7.2), so the suggestion is the whole factor for that day. Runs in both `price_checks` (last 400 days) and `price_checks_full`. `_close_resolved` closes these rows like the other kinds.
- The UI offers "apply suggested factor" (inserts a `manual_adjustments` row, marks the check `fixed`, calls `frames.invalidate()`) and "ignore".

### §7.4 Frames (`analytics/frames.py`)

```python
def load_frame(symbol: str, start: str | None = None) -> pd.DataFrame   # adjusted; frame.attrs["source"] = bars source; in-process LRU 600
    # frame.attrs["symbol"] = symbol upper-cased (T102), so DB-backed indicators know whose frame it is
def results_dates(symbol: str) -> list[pd.Timestamp]   # fundamentals.known_on_dates as Timestamps, cached until invalidate() (T102)
def industry_of(symbol: str) -> str | None             # symbols.industry (T103)
def load_industry_returns(n: int) -> pd.DataFrame      # per date × industry median return_pct(n), plus "__market__"; NaN under INDUSTRY_MIN_STOCKS = 3 (T103)
def bars_source(symbol: str, conn=None) -> str | None
def load_benchmark(start: str | None = None) -> pd.Series              # "NIFTY 500" from the first ordered("index") source with data
def universe(conn=None) -> list[str]        # symbols.in_universe=1 ∪ watchlist ∪ open positions, sorted
def last_trading_date(conn=None) -> str | None   # max(date) in bars for the primary bars source of the universe
def invalidate() -> None                    # call after any write that changes prices/actions/priorities
```
**Ticker lineage (T077, in `analytics/adjust.py`):**
```python
def lineage(symbol: str, conn) -> list[tuple[str, str | None, str | None]]
    # [(ticker, from_date, until_date)], oldest first, `symbol` last. from_date inclusive / until_date exclusive, None = open.
```
- Rows come from `symbol_changes` of every enabled source in `ordered("symbol_changes")` plus source `'manual'`; duplicates of the same (old, new, date) count once.
- Walk back from `symbol`: among rows with `new_symbol` = the current ticker and `effective_date` ≤ the current segment's start (any date for the first step), take the latest; its `old_symbol` becomes the previous segment, `until` = that effective_date. Stop when there is none, when a ticker repeats, or after 10 steps.
- The current symbol's segment starts at its latest rename date (`from_date`), so bars a recycled ticker had for an older company are never joined in. The oldest segment has `from_date=None`.
- `load_raw(symbol, source, conn)` reads every segment from that one source, keeps each segment's dates inside its window, concatenates them oldest first and drops duplicate dates (keeping the newer ticker's row). A symbol with no renames reads exactly as before.

**Raw price store (T117, `analytics/price_store.py`):** `<data dir>/cache/price_store.pkl` (pickle 5, written atomically by the `backtest` and `backtest_batch` jobs only) keeps each requested ticker's raw bars `raw[(source, symbol)] = (frame, count, max_date, checksum)` plus the completed months of the liquidity aggregate (§12.5). It records a format version and the `ordered("bars")` names it was built with; a mismatch or an unreadable file means an empty store (logged at info, never an error).
- `ensure_valid(conn)` runs once per process per data version: one `GROUP BY source, symbol` query gives (count, max date, checksum) for every symbol. Matching entries are kept; entries with newer bars get just the new rows appended (kept only if count and checksum then match); anything else (an old bar changed or deleted) is dropped and re-read. `frames.invalidate()` forces re-validation but leaves the file alone. A write that doesn't call `invalidate()` is not noticed until the next validation.
- The same validation reads `corp_actions`, `event_factors`, `manual_adjustments`, `symbol_changes` and the source orders once; `adjustment_factors`, `lineage`, `bars_source` and `load_raw` use them while the store is valid, so a warm `load_frame` cache hit makes no SQL query.
- `frame.attrs["cache_key"]` is a short hex digest of the cache key (source, newest date, count, checksum, factors, lineage), not a tuple.
- **Per source (T078a):** lineage only matters where the source actually stores bars under an older ticker. Drop the older segments with no bars in that source. If only the current symbol's segment is left, read it **without** a date window (the single-query path). Example: yfinance keeps TMPV.NS's full history under the new ticker and has no TATAMOTORS rows, so its TMPV series must not be cut at 2025-10-24.
- `adjustment_factors` is unchanged (it uses the current symbol's actions).
- The `load_frame` cache key includes the lineage.
`store.save_bars`, `save_actions` and `save_index`, plus any priority or manual-adjustment change, call `invalidate()`.

### §7.5 Prices API

```
GET /api/symbols/search?q=      -> [{symbol,name,industry,in_universe}] (max 20; prefix on symbol, substring on name)
GET /api/symbols/{sym}          -> {symbol,name,industry,in_universe,last_date,last_close,change_pct,bars_source,in_watchlist,open_position_id,series,trade_for_trade,next_results}
    # series: instruments.series (latest bhavcopy series, e.g. "EQ", "BE") or null; trade_for_trade: series in ("BE","BZ") (T093)
    # next_results: {date, days} from analytics/calendar.next_results or null (T095)
GET /api/prices/{sym}?start=&indicators=sma:50,sma:200,rsi:14
    -> {symbol, source, bars:[{t,o,h,l,c,v}], indicators:{"sma:50":[{t,v}],...}, actions:[{ex_date,subject,factor,source}]}
GET /api/data/health -> {last_trading_date, symbols, universe, checks_open, unparsed_actions,
                         bars:{source: {symbols, last_date}}, fundamentals:{source: n, merged: n}, quarters:{source: n},
                         news:{announcements_7d, news_7d}}
GET /api/data/checks?status=open -> [{id,symbol,date,kind,primary_source,other_source,detail,status}]
POST /api/data/checks/{id}      body {action:"ignore"|"apply_factor", factor?} -> check
GET /api/data/unparsed-actions  -> [{source,symbol,ex_date,subject}]
POST /api/data/manual-adjustment body {symbol, ex_date, factor, note?} -> row
GET /api/data/symbol-changes?symbol= -> {symbol, lineage:[{ticker,from_date,until_date}], rows:[{source,old_symbol,new_symbol,effective_date,name,note}]}
POST /api/data/symbol-change    body {old_symbol, new_symbol, effective_date, note?} -> row (source 'manual'; 400 if old == new or bad date)
```

---

## §8 Indicators and rules

### §8.1 Indicator registry (`analytics/indicators.py`)

```python
@dataclass(frozen=True)
class Param:  name: str; kind: Literal["int","float"]; default: float; min: float; max: float; label: str
@dataclass(frozen=True)
class IndicatorDef:
    name: str; label: str
    explain: str              # plain English, ≤ 140 chars, may use {n}/{k}
    params: tuple[Param, ...]
    fn: Callable[..., pd.Series]   # fn(frame, bench: Series | None, **params) -> Series aligned to frame.index
    pane: Literal["price","separate","none"]
    custom: bool = False
def register(d: IndicatorDef) -> None    # duplicate -> ValueError
def get(name: str) -> IndicatorDef
def catalogue() -> list[dict]            # JSON-able, used by the UI and AI tasks
def compute(name: str, frame, bench=None, **params) -> pd.Series   # fills defaults, validates ranges (ValueError)
```

Built-in v1 indicators. Windows are in trading days.

| name | params | definition |
|---|---|---|
| `close` `open` `high` `low` `volume` | — | the column |
| `sma` | n=20 [2–400] | rolling mean of close |
| `ema` | n=20 [2–400] | `close.ewm(span=n, adjust=False).mean()` |
| `rsi` | n=14 [2–50] | Wilder RSI (`ewm(alpha=1/n, adjust=False)` of gains/losses) |
| `atr` | n=14 [2–50] | Wilder ATR of true range |
| `atr_pct` | n=14 | atr / close × 100 |
| `return_pct` | n=63 [1–756] | (close / close.shift(n) − 1) × 100 |
| `rel_strength` | n=63 [5–756] | stock return_pct(n) − benchmark return_pct(n); NaN without bench |
| `pct_from_high` | n=252 [20–756] | (close / rolling max(high, n) − 1) × 100 |
| `pct_from_low` | n=252 | (close / rolling min(low, n) − 1) × 100 |
| `highest` | n=20 | `high.shift(1).rolling(n).max()` (excludes today) |
| `lowest` | n=20 | `low.shift(1).rolling(n).min()` |
| `volume_ratio` | n=20 | volume / volume.shift(1).rolling(n).mean() |
| `sma_slope` | n=50, k=20 | (sma(n) / sma(n).shift(k) − 1) × 100 |
| `range_pct` | n=63 | (rolling max high / rolling min low − 1) × 100 |
| `index_vs_sma` | n=200 [20–400] | market filter (T088): `(bench / bench.rolling(n).mean() − 1) × 100`, computed on the bench's own dates, then `reindex(frame.index, method="ffill")`; all-NaN without bench. `> 0` means the Nifty 500 is above its n-day average |
| `breadth_above_sma` | n=200 [20–400] | market breadth: `frames.load_breadth(n)` = % of today's `universe()` symbols whose adjusted close is above their own n-day average, per date (NaN where fewer than `BREADTH_MIN_STOCKS` = 20 stocks have an average), then `reindex(frame.index, method="ffill")`. Cached in `frames` until `invalidate()`. Catches broad bears the cap-weighted index misses (2018–19 read 25–35%). |
| `mom_smooth` | n=126 [20–504] | smooth momentum (T101): `return_pct(n) / (close.pct_change().rolling(n).std() × sqrt(n) × 100)`; NaN where std is 0/NaN |
| `adx` | n=14 [5–50] | Wilder ADX (T101); first 2n bars NaN |
| `efficiency` | n=20 [5–252] | `|close − close.shift(n)| / close.diff().abs().rolling(n).sum() × 100` (T101) |
| `days_since_high` | n=252 [20–756] | trading days since the highest high of the last n bars incl. today (T101) |
| `traded_value_cr` | n=20 [5–252] | `(close × volume).rolling(n).mean() / 1e7` (T101) |
| `results_move` | k=2 [1–10] | post-results reaction (T102): for each known-on date d (`_known_on`, §9.4), (close of the k-th bar on/after d ÷ last close before d − 1) × 100, shown from that bar until the next result; NaN 120 bars after the last one. Needs `frame.attrs["symbol"]`, else all-NaN |
| `days_since_results` | — | trading days since the latest known-on date (T102); needs the symbol attr |
| `industry_rs` | n=63 [5–252] | stock return_pct(n) − its industry's median (T103). Stocks without `symbols.industry` (e.g. delisted names in liquid500) are all-NaN |
| `industry_strength` | n=63 [5–252] | industry median return_pct(n) − market median (T103) |

### §8.2 Rule DSL (`analytics/rules.py`)

```jsonc
// Rule = Group
{"all": [Cond | Group, ...]}  |  {"any": [Cond | Group, ...]}  |  {"not": Cond | Group}
// Cond
{"left": Operand, "op": "<op name from OPS>", "right": Operand}
// Operand (exactly one form)
{"ind": "<indicator>", "params": {"n": 50}, "offset": 0}   // offset k = value k bars ago
{"fund": "<fundamental field>"}                              // latest merged snapshot; constant over time.
                                                             // In backtests the value may be a date-indexed pd.Series (T096): reindexed to the frame;
                                                             // missing only if all NaN
{"value": 15}
// optional on ind/fund operands: "times": 2.0 (multiplier)
// optional on ind operands: "rank": true -> the stock's percentile (0–100, 100 = best) among all stocks that date (T104);
//   offset/times apply after ranking; needs the caller to pass `ranks`, else the operand is missing ("rank: <label>")
```
```python
@dataclass(frozen=True)
class OpDef: name: str; words: str; fn: Callable[[pd.Series, pd.Series], pd.Series]   # words e.g. "is above"
OPS: dict[str, OpDef]   # v1: ">" is above, ">=" is at least, "<" is below, "<=" is at most,
                        #     "crosses_above" crosses above (l>r today and l<=r yesterday), "crosses_below"
class RuleError(ValueError): ...   # message includes the JSON path, e.g. "all[2].left.ind: unknown indicator 'smaa'"
def validate_rule(obj: dict) -> Rule            # max depth 4, max 20 conditions, no empty groups
def evaluate(rule, frame, bench, fund: dict | None, ranks: dict | None = None) -> pd.Series   # bool per bar; NaN -> False
def evaluate_latest(rule, frame, bench, fund, ranks=None) -> tuple[bool, dict]   # (pass on last bar, {operand label: value})
def describe(rule) -> str     # plain English: "Close is above the 200-day average AND ROCE % is at least 15"
def uses_fundamentals(rule) -> bool
def fund_fields(rule) -> set[str]   # fund field names used (T096)
def rank_operands(rule) -> list[Operand]        # unique ranked operands (T104)
def rank_key(o: Operand) -> tuple               # (ind, sorted params); keys of `ranks` = {rank_key: this symbol's percentile Series}
def cross_rank(values: pd.DataFrame) -> pd.DataFrame   # dates × symbols -> rank(axis=1, pct=True)×100; under RANK_MIN_STOCKS = 20 values a date is all-NaN
```
Ranks are built by the callers (T104): `screens.scan` ranks the last bar of every loaded, non-stale symbol; the engine ranks per date among symbols with a bar that are eligible (liquid500 mask).
A missing fundamental makes its Cond **False**, and `evaluate_latest` reports `"missing: roce_pct"`.

### §8.3 Custom indicators (AI-written, owner-approved; `analytics/custom_indicators.py`)

- Code shape: `def compute(frame, bench, **params): ...` returning a `pd.Series`. Only `pd`, `np` and `math` are available.
- **Static check** (`ast`, never executes anything): reject any `Import`, `ImportFrom`, `Global`, `Nonlocal`, any dunder name or attribute (`__x__`, and any name/attribute starting with `_`), and the names `open`, `exec`, `eval`, `compile`, `__import__`, `globals`, `locals`, `vars`, `dir`, `getattr`, `setattr`, `delattr`, `input`, `breakpoint`, `type`, `object`, `super`, `memoryview`. Also reject attribute names that reach files, the OS or code evaluation through pandas/numpy (planner addition, 2026-11-09): any attribute starting with `read_`, `to_` or `from` (e.g. `read_pickle`, `to_csv`, `fromfile`), and `load`, `loads`, `save`, `savez`, `savetxt`, `loadtxt`, `genfromtxt`, `tofile`, `memmap`, `eval`, `query`, `pipe`, `apply`, `applymap`, `map`, `agg`, `aggregate`, `transform`, `io`, `lib`, `os`, `sys`, `ctypes`, `testing`, `api`, `core`, `compat`, `plotting`, `options`, `set_option`, `system`. `compute` must be the only top-level statement (one `FunctionDef`). Code over 4,000 chars is rejected.
- Attribute **allowlist** `ALLOWED_ATTRS` (T048a), plus the denylist: every attribute name must be on the allowlist (checked by name, not receiver); `allowed_vocabulary()` lists it for the `indicator_code` prompt.
- **Trial run:** on a synthetic 300-bar frame, **only as part of approval** (the owner has read the code and clicked Approve). It runs in a child process (`multiprocessing`, spawn) with a 10 s timeout; on timeout the child is killed. The result must be a Series of the same length. If the trial fails, approval returns 400 and the row stays `pending` with the error shown.
- Execution: `exec` with `{"__builtins__": SAFE_BUILTINS, "pd": pd, "np": np, "math": math}`.
- Only `approved` rows are registered (`custom=True`), at startup and on approval. **Code never runs before the owner approves it after reading it.**

---

## §9 Fundamentals

Adapters do all source-specific parsing and unit conversion, so core code only sees §9.4 fields and `Quarter` rows.

### §9.1 NSE quarterly results (`nse_api` adapter, `quarters` capability; `sources/parsers/xbrl.py`)

```python
def parse_results_list(items: list[dict]) -> list[dict]   # {period_end, period_start, consolidated, audited, filing_date, xbrl_url}; de-dupe keeps latest filing
def parse_xbrl(content: bytes, period_start: str | None, period_end: str | None) -> dict   # revenue, other_income, total_expenses, pbt, net_profit, eps (₹ crore, eps ₹); XbrlError
```
- `quarters(symbol, known_periods)`:
  1. Fetch the list.
  2. For the newest 12 periods not in `known_periods`, fetch the XBRL and parse it.
  3. A failed parse yields a `Quarter` with `parse_error` set.
- XBRL matching:
  - elements are matched by **local name** with candidate lists, confirmed in T032 from a real file and recorded in `docs/DATA_SOURCES.md`
  - only the context matching the period is used
  - **Undeclared `OneD` (T081):** NSE files from 2021 to mid-2022 never declare the plain quarter context, yet their figures use `contextRef="OneD"` (verified on INFY Q1 FY22: revenue ₹27,896 cr). When no declared plain context matches the period and facts reference `OneD`, use `OneD`; the period comes from NSE's results list.
  - INR values are divided by 1e7 to give crore

### §9.2 Screener (`screener` adapter; `sources/parsers/screener_html.py`)

```python
def parse_company_page(html: bytes) -> dict   # {"ratios":{...}, "quarters":{periods, rows}, "profit_loss":{...}, "balance_sheet":{...},
                                              #  "ratios_hist":{...}, "shareholding":{...}, "growth":{"sales_cagr":{"10y","5y","3y","ttm"}, "profit_cagr":{...}, "roe":{...}}, "missing":[...]}
def to_fields(parsed: dict) -> dict           # §9.4 fields this source can fill (incl. D/E from balance sheet, YoY from its quarters, promoter change)
```
- `fundamentals(symbol)` returns `FundSnapshot(fields=to_fields(p), detail={quarters, profit_loss, shareholding, balance_sheet, ratios_hist, growth, variant})` (the last two tables added by T115).
- It never crashes on missing sections.

### §9.3 yfinance (`yfinance` adapter, `fundamentals` capability)

`fields` maps:
- `trailingPE` → `pe`
- `priceToBook` → `pb`
- `returnOnEquity`×100 → `roe_pct`
- `debtToEquity`/100 → `debt_to_equity`
- `marketCap`/1e7 → `market_cap_cr`
- `heldPercentInsiders`×100 → `promoter_pct`
- `sector`, `industry`

NaN becomes None.

### §9.4 Merged fundamentals (`analytics/fundamentals.py`)

```python
FIELDS: list[dict]   # {field, label, explain, unit, numeric}; the only legal field names anywhere
def from_quarters(symbol, conn) -> dict          # derived: sales/profit_growth_yoy_pct, profit_positive_4q from `quarters` (ordered("quarters"), consolidated preferred)
def merge(symbol, conn) -> tuple[dict, dict]     # (data, sources). Per field: order = fundamentals_field_priority[field] if set,
                                                 # else ordered("fundamentals") names; "quarters" = from_quarters(); first non-null wins
QUARTER_FIELDS = ("sales_growth_yoy_pct", "profit_growth_yoy_pct", "profit_positive_4q")
AVAILABLE_LAG_DAYS = 1
def pit_quarter_series(symbol, index, conn) -> dict[str, pd.Series]   # T096, backtests only: each QUARTER_FIELDS value as it was known
def pit_history_series(symbol, index, conn) -> dict[str, pd.Series]   # T115, backtests only: each HISTORY_FIELDS value (roce_pct, roe_pct, debt_to_equity, sales/profit_growth_3y_pct, promoter_pct, promoter_change_1y_pp) rebuilt from the stored Screener `detail`; a year counts from period end + 60 days, a shareholding quarter from + 21 days; NaN when stale (550 / 200 days) or no screener row
    # on each date. A quarter is known from filing_date + 1 day (null filing_date: period_end + 60 days); value = _derive(known quarters,
    # as_of=date), forward-filled; NaN before the first derivable value and while the latest known period_end is > MAX_QUARTER_AGE_DAYS old
```

| field | explain (UI) |
|---|---|
| `market_cap_cr` | Company size in ₹ crore. |
| `pe` | Price ÷ yearly profit per share: how expensive the stock is. |
| `pb` | Price ÷ book value per share. |
| `roce_pct` | Profit earned on all the capital the business uses. Above 15% is good. |
| `roe_pct` | Profit earned on shareholders' money. |
| `debt_to_equity` | Borrowings ÷ shareholders' money. Below 0.5 is comfortable. |
| `sales_growth_3y_pct` | Yearly sales growth, compounded over 3 years. |
| `profit_growth_3y_pct` | Yearly profit growth, compounded over 3 years. |
| `sales_growth_yoy_pct` | Latest quarter's sales vs the same quarter last year. |
| `profit_growth_yoy_pct` | Latest quarter's profit vs the same quarter last year. |
| `profit_positive_4q` | 1 if the company made a profit in each of the last 4 quarters. |
| `promoter_pct` | Share of the company owned by its promoters (founders/parent). |
| `promoter_change_1y_pp` | Change in promoter holding over the last year, in % points. |
| `dividend_yield_pct` | Yearly dividend as % of price. |
| `sector`, `industry` | text (not usable in numeric rules) |

API:
- `GET /api/fundamentals/fields` → FIELDS
- `GET /api/fundamentals/{sym}` → `{data, sources, updated_at, quarters:[rows], snapshots:{source:{fetched_at, detail}}}`

---

## §10 Screens, shortlist and score

- `analytics/screens.py`:
  ```python
  def run_screen(screen_id, ctx=None) -> list[dict]
  def preview(rule) -> dict
  ```
  - Rules are evaluated on the latest bar for every `universe()` symbol, computing each indicator once per run.
  - `run_screen` replaces `screen_results` but keeps `first_seen`. History lives in the append-only signal log (§16).
  - Staleness guard (T036): a symbol whose last bar is more than `STALE_DAYS` = 7 days older than the newest bar in the universe is skipped, so suspended or delisted stocks don't match on old prices.
  - `last_run_as_of`/`count` come from `screen_results`, so a run that matched nothing reads like a never-run screen (known limitation).
  - Presets can be edited (PUT) but not deleted.
  - `preview` stops after 20 s with a 400 "too slow".
- **Presets** (`presets/screens.json`, seeded by `init_db` by name, `is_preset=1`, not deletable). Numbers below are the original order. **Retired 2026-11-14** after grid search run1 (`data/grid/run1/summary.md`): 1, 4, 6, 12, struck through below. They are gone from `screens.json`, and `init_db` deletes them from existing databases by name (`db.RETIRED_SCREEN_PRESETS`). Rules that mention them still describe those conditions:
  1. ~~**Uptrend leaders**: close > sma 50, sma 50 > sma 200, rel_strength 126 > 10, pct_from_high 252 > −15~~ (retired)
  2. **Breakout on volume**: close crosses_above highest 63, volume_ratio 20 ≥ 2, close > sma 200
  3. **Quality in uptrend**: roce_pct ≥ 15, debt_to_equity ≤ 0.5, profit_growth_3y_pct ≥ 10, close > sma 200, rel_strength 63 > 0
  4. ~~**Pullback in strong trend**: close > sma 200, sma_slope 50,20 > 0, rsi 14 < 45, pct_from_high 252 > −20~~ (retired)
  5. **Tight base near highs**: range_pct 40 < 15, pct_from_high 252 > −10, volume_ratio 20 < 1
  6. ~~**Trend riders** (T089): Uptrend leaders + index_vs_sma 200 > 0~~ (retired)
  7. **Quality trend riders**: roce_pct ≥ 15, debt_to_equity ≤ 0.5, profit_growth_3y_pct ≥ 10, then the five Trend riders conditions, then breadth_above_sma 200 > 50. Fair-universe tests (2012–2026): about the same CAGR as Trend riders with half the volatility and drawdown; fundamentals are today's (look-ahead), so treat as optimistic.
  8. **Steady quality leaders**: roce_pct ≥ 15, debt_to_equity ≤ 0.5, close > sma 50, sma 50 > sma 200, rel_strength 126 > 20, pct_from_high 252 > −10, index_vs_sma 200 > 0, breadth_above_sma 200 > 50. Meant for 30 slots with Trend exits: smallest drawdown tested (−21%).
  9. **52-week high breakout** (T107): close crosses_above highest 252, volume_ratio 20 ≥ 1.5, index_vs_sma 200 > 0. Tests (liquid500 2012→, 20 slots, Position exits): 15.7% CAGR, −43% DD, 7.9% from 2022 (index 13.5% / 9.6%): no edge.
  10. **Promoters buying, in uptrend**: promoter_change_1y_pp > 0, close > sma 200, rel_strength 126 > 0 (today's fundamentals: look-ahead in backtests)
  11. **Breadth trend riders**: the four Uptrend leaders conditions, breadth_above_sma 200 > 50. Tests (Position exits): 17.7% CAGR, −36% DD, 15.7% from 2022.
  12. ~~**Smooth momentum leaders**: mom_smooth 126 rank ≥ 90, close > sma 100, traded_value_cr 20 ≥ 5, breadth_above_sma 200 > 50. Tests (Position exits): 12.6% CAGR, −46% DD, 10.4% from 2022: below the index.~~ (retired)
  13. **Results winners**: results_move 2 ≥ 5, days_since_results ≤ 40, close > sma 200, traded_value_cr 20 ≥ 5. Results data starts 2019; tests (Position exits) from 2022: 22.6% CAGR, −27% DD.
  14. **Leaders in leading industries**: industry_strength 63 > 0, industry_rs 63 > 0, rel_strength 126 rank ≥ 80, close > sma 50 (today's industries only: survivorship in backtests). Tests (Position exits) 28.8% CAGR, −32% DD, 23.0% from 2022, heavily flattered by that survivorship.
  15. **Short dip in uptrend**: rsi 2 < 10, close > sma 200, traded_value_cr 20 ≥ 5; pair with the "Short dip" exit set (rule_exit close > sma 5, time_stop 10, no stop). Tests: −1.0% CAGR, −65% DD (~14,600 short trades; costs eat the edge).
- **Score components** (`analytics/score.py`):
  ```python
  @dataclass(frozen=True)
  class ScoreComponent:
      name: str; label: str; explain: str
      compute: Callable[[pd.DataFrame], pd.Series]          # candidates frame (one row per symbol, precomputed columns) -> 0–100
      reasons: Callable[[pd.Series], list[tuple[float, str]]]  # one candidate row -> [(strength, text)]
  COMPONENTS: dict[str, ScoreComponent]
  def candidates_frame(conn) -> pd.DataFrame   # union of latest screen_results; columns: rs63, rs126, close, sma50, sma200, sma_slope,
                                               #   pct_from_high, fundamentals fields, best_screen_oos_excess, screens (list)
  def score_candidates(conn) -> list[dict]     # total = Σ w·c / Σ w over components with weight > 0; reasons = top 4 by strength
  ```
  - v1 components:
    - `rs`: mean percentile of rs63 and rs126
    - `trend`: mean of [close > sma50, close > sma200, sma50 > sma200] as 0/100 each, plus the sma_slope percentile
    - `fundamentals`: mean percentile of roce_pct, inverse D/E, profit_growth_3y_pct and profit_growth_yoy_pct. If none are available it's 50, with "fundamentals missing".
    - `backtest`: percentile of best_screen_oos_excess. If none it's 50, with "screen not backtested".
  - Percentiles are taken among candidates, via `rank(pct=True)×100`.
  - Example reasons: "Beat the Nifty 500 by 14 pts over 3 months", "ROCE 22%", "7% below its 52-week high", "Its screen beat the index by 6%/yr out-of-sample".
- **API:**
  ```
  GET  /api/screens -> [{id,name,description,rule,describe,is_preset,created_by,last_run_as_of,count}]
  POST /api/screens body {name,description,rule} -> screen (400 with RuleError message)
  PUT  /api/screens/{id}   DELETE /api/screens/{id} (400 if preset)
  POST /api/screens/{id}/run -> {run_id}                (screens_run with {"screen_ids":[id]})
  POST /api/screens/preview body {rule} -> {count, rows:[{symbol,values}]}
  GET  /api/screens/{id}/results -> [{symbol,name,values,first_seen,score,reasons}]
  GET  /api/shortlist?limit=20 -> [{symbol,name,score,components:{name: value},reasons,screens,last_close,next_results}]   # next_results {date,days}|null (T095)
  GET  /api/score/components -> [{name,label,explain,weight}]
  GET  /api/indicators -> catalogue()     POST /api/rules/describe body {rule} -> {text} (400 RuleError)
  GET  /api/rules/ops -> [{name, words}]
  ```

---

## §11 AI through the Pro plan (`ai/`)

```python
# ai/base.py
class AIError(Exception): ...
class AIProvider:
    name: str; label: str
    def available(self) -> tuple[bool, str]                       # (ok, version or reason)
    def ask(self, prompt: str, *, model: str, timeout_s: int, stop_check: Callable[[], bool] | None = None) -> str
def register_provider(p: AIProvider) -> AIProvider
def provider(name: str | None = None) -> AIProvider              # default = settings ai_provider

@dataclass(frozen=True)
class AITask:
    kind: str; label: str
    build_prompt: Callable[[dict], str]                 # payload -> prompt (payload may contain symbol, answers, text)
    postprocess: Callable[[str, dict], dict] | None = None   # (response, payload) -> result JSON; may raise AIError
    needs_symbol: bool = False
def register_task(t: AITask) -> AITask
def task(kind: str) -> AITask
def all_tasks() -> list[AITask]
```
- **`claude_cli` provider** (`ai/providers/claude_cli.py`):
  - runs `["claude", "-p", "--model", model, "--output-format", "json", <tool-disabling flags>]`
  - passes the prompt on **stdin**, with cwd set to an empty temp dir
  - builds the child env without `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_USE_BEDROCK` and `CLAUDE_CODE_USE_VERTEX`, so the call always uses the Pro login
  - parses the JSON `result` field
  - kills the process group on timeout or stop
  - T044 confirms the exact flags with `claude --help` and records them in `docs/DATA_SOURCES.md`
- **Flow:**
  1. `POST /api/ai/requests {kind, symbol?, payload?}` calls `task.build_prompt`, inserts an `ai_requests` row (prompt, provider, model), and enqueues `ai_request`.
  2. The job calls `provider.ask(...)` with `stop_check=ctx.stop_requested`, then `postprocess` (if any) → `result`.
  3. On `AIError` the status is `failed`.
- **Tasks** (one module each in `ai/tasks/`; context ≤ 25k chars, trimmed oldest-first):
  - `stock_brief` and `thesis_draft`: built on the shared `stock_context(symbol)` in `ai/tasks/_context.py`
  - `checklist_challenge`
  - `rule_from_text`: its postprocess validates the rule and returns `{"ok":true,"rule","name","description","describe"}`, `{"ok":true,"need_custom_indicator":{...}}` or `{"ok":false,"error"}`. On a RuleError it re-asks once through the provider, with the error appended.
  - `indicator_code` (T048a; `needs_symbol=False`): payload `{name, description}`; postprocess extracts the JSON, checks the name and `static_check`s the code (never executes it), re-asks once with the problems, and returns `{"ok":true,"name","explain","params_schema","code","problems":[]}` or `{"ok":false,"error"}`.
  - Wording rules for every task:
    - plain language
    - the reader holds for weeks to 4 months
    - **not financial advice**: no buy/sell calls, only facts, risks and things to verify
    - the data date is stated
- **Copy prompt:** `GET /api/ai/prompt?kind=&symbol=` (and `POST /api/ai/prompt {kind, payload}`) → `{prompt}`, for pasting into claude.ai. This works with no provider at all.
- **API:**
  ```
  GET  /api/ai/status -> {provider, available, detail, model, providers:[{name,label}]}
  GET  /api/ai/tasks  -> [{kind,label,needs_symbol}]
  POST /api/ai/requests body {kind, symbol?, payload?} -> {id, run_id}
  GET  /api/ai/requests/{id} -> {id,kind,status,response,result,error,duration_s,provider,model}
  GET  /api/ai/requests?symbol=&kind=&limit=20 -> [...]
  ```

---

## §12 Backtesting (`backtest/`)

### §12.1 Costs (`backtest/costs.py`)

```python
def trade_costs(side: Literal["buy","sell"], value_inr: float, model: dict) -> float
def fill_price(side: Literal["buy","sell"], open_price: float, model: dict) -> float   # buy ×(1+slip%), sell ×(1−slip%)
```
- Brokerage: `min(value×brokerage_pct/100, brokerage_cap_inr)`.
- STT: `stt_pct`, both sides.
- Exchange: `exchange_pct`.
- SEBI: `sebi_pct`.
- GST: `gst_pct`% of (brokerage + exchange + sebi).
- Stamp duty: `stamp_buy_pct`, buy side only.
- DP charge: `dp_charge_inr`, per sell.

### §12.2 Engine and exits (`backtest/exits.py`, `backtest/engine.py`)

```python
@dataclass(frozen=True)
class ExitDef:
    type: str; label: str; explain: str; params: tuple[Param, ...]
    when: Literal["intraday","close"]
    setup: Callable[[dict, dict], dict]            # (position at entry incl. entry_fill & atr14, params) -> state (e.g. stop level)
    check: Callable[[dict, pd.Series, dict], tuple[bool, float | None, str]]
        # (state, today's bar row, context{days_held, signals}) -> (exit?, fill price or None=next open, reason)
EXITS: dict[str, ExitDef]
# v1: stop_atr{k=2}, stop_pct{pct=8}, target_atr{k=4}, target_pct{pct=15}  (intraday: gap through -> open, else level)
#     stop_trail_atr{k=5}: level = max(level, highest close since entry − k·ATR14); today's close raises the level only for later bars; reason "trailing stop"
#     time_stop{days=40}, rule_exit{rule}  (close: exit next open)
# intraday order: all stop-type exits are checked before target-type exits (stop assumed first if both hit)

class BacktestConfig(BaseModel):
    entry_rule: dict
    exits: list[dict] = [{"type":"stop_atr","params":{"k":2}}, {"type":"target_atr","params":{"k":4}}, {"type":"time_stop","params":{"days":40}}]
    max_positions: int = 10
    sizing: Literal["equal","risk"] = "equal"; risk_pct: float = 0.5   # 1% never binds at 20 slots; 0.5% cut the worst drawdown in tests
    start: str = "2012-01-01"; end: str | None = None
    oos_start: str | None = None          # T113: test-period start; training = [start, oos_start). None -> setting holdout_start (§12.6)
    initial_capital: float = 1_000_000
    universe: Literal["current","liquid500"] = "liquid500"   # §12.5 (T087); "current" = today's in_universe list
    rank_by: dict = {"ind": "rel_strength", "params": {"n": 126}}   # T105: indicator operand (no rank flag); orders signals, higher first
    max_per_industry: int | None = None    # T105: 1–50; open + pending buys per frames.industry_of; unknown industry never capped
    regime_scale: dict | None = None       # T105: {"breadth_below": 50, "slots_pct": 50}; weak breadth shrinks slots for NEW entries only
    mode: Literal["signals","rotate_monthly"] = "signals"   # T106
    hold_buffer: float = 1.5               # T106: 1.0–3.0, rotate_monthly only
def run_backtest(cfg, ctx=None, frames=None, bench=None, fund=None, eligible=None, industries=None, breadth=None) -> dict   # industries/breadth: test overrides (T105)   # {equity:[{t,v,bench}], trades, metrics, warnings}
    # eligible: optional {symbol: DatetimeIndex-aligned bool Series} entry mask; built by the loader for liquid500 when frames is None
```
- **Signals use bar t's close. Fills use bar t+1's open. Nothing looks ahead.**
- When there are more signals than slots, the highest `rank_by` value goes first (default rel_strength 126; ties broken by symbol). With `max_per_industry`, a candidate whose industry is full is skipped. With `regime_scale`, on days when breadth_above_sma 200 < `breadth_below` the new-entry slot limit is floor(max_positions × slots_pct / 100); NaN breadth = no scaling. Warning when ≥ 10% of trades had no known industry under a cap.
- **Monthly rotation (T106).** In `rotate_monthly`, new entries are decided only on the last trading day of each month: candidates (rule passes, eligible, ranked by `rank_by`, industry cap applied) → held stocks outside the top ceil(max_positions × hold_buffer) get a pending sell, reason `"rotation"` → buy the best unheld candidates up to the (regime-scaled) slot count. Exits work as usual between rebalances; freed slots wait for the next rebalance.
- Equal sizing = equity / max_positions. Risk sizing = (equity×risk%) / (entry − stop), capped at equal weight. Whole shares only.
- **Fundamentals (T096).** When real data is loaded and a rule uses any `QUARTER_FIELDS`, those fields come from `pit_quarter_series` per symbol (replacing the snapshot value, never falling back to it). Warnings: quarter fields → "Quarterly growth fields use results as they were published (from the day after filing). They are only available from 2019, so the rule can't pass on earlier dates."; any `HISTORY_FIELDS` (T115: overlaid from `pit_history_series` the same way) → "Yearly figures (ROCE, ROE, debt, 3-year growth) and promoter holding use Screener.in's history as it was published: a year counts from 60 days after it ends, a shareholding quarter from 21 days after. Yearly history starts with FY2015 (3-year growth from mid-2018) and promoter holding covers only the last 3 years, so the rule can't pass before then. Only stocks in today's Nifty 500 have this history."; any other fund field (market cap, P/E, P/B, dividend yield) → the look-ahead warning ("…uses today's figures…") followed by " Fields: " and those fields' labels.
- **Delisted stocks (T085).** A symbol's *last bar* is its last non-NaN open in the frame. No entry signal is acted on at or after a symbol's last bar (there is no next open to fill at). On the first master date after a held symbol's last bar, it is sold at that last bar's close (sell slippage and costs apply as usual), reason `"delisted"`, and the slot frees the same day. A gap of missing bars that is followed by more bars (a suspension) is not a delisting: the position is held.
- **Batches and shared setup (T116).** `run_backtest(cfg, ctx, ..., shared=Shared)` takes frames, benchmark, fundamentals, eligibility masks, dropped count, industries and breadth from a `backtest/batch.py` `Shared` instead of loading them; results equal a standalone run. `run_batch(cfgs, ctx, on_result)` groups configs by `(universe, start)`, loads once per group (PIT fund fields = union over the group; industries only if some config has `max_per_industry`; breadth(200) only if some has `regime_scale`), and runs each config with `shared`. `on_result(i, result | Exception)` fires per config; a failing config doesn't stop the rest, `StopRequested` propagates. `Shared.memo` caches each rule condition's `(result, valid)` per symbol (`rules.evaluate(..., memo=)`, key = canonical JSON of the condition + symbol). `Shared.arrays` caches the price arrays (`open/high/low/close/last_t/atr/rank_val`, read-only in the day loop) by `(first date, last date, length, rank_by JSON)`, plus a forward-filled close (`close_ff`) that values positions, the date index by `(start, end)`, and the entry and exit-signal arrays by `(dates, entry rule + exit rules with their exit index)`; at most `engine.SIGNAL_CACHE` (8) signal sets are kept, least recently used dropped first. So configs that differ only in stop, target or time-stop numbers, slots, sizing, regime or mode reuse one signal build. Only explore rows are batched.
- **Parallel batches (T118, `backtest/parallel.py`).** `batch.signal_key(cfg)` = `(universe, start, end, canonical JSON of entry_rule, exit rules, rank_by)`. The `backtest_batch` job uses `workers = min(setting backtest_workers (1–6), distinct signal keys, cpu_count - 1)`; `<= 1` runs in-process as above. Otherwise configs are bundled by signal key (a bundle is never split), bundles dealt largest first over a `spawn` `ProcessPoolExecutor` (an empty worker is filled first, then a worker with the same `(universe, start)`). Workers register the plug-in packages, only read the DB, run `run_batch` on their share, save the price store and return `[(input_index, result | error text)]`. The parent is the single DB writer and finishes rows as each worker completes. A stop terminates the workers and marks unfinished rows `cancelled`; a crashed or raising worker fails only its own rows.

### §12.3 Metrics (`backtest/metrics.py`)

Computed for all, in-sample and out-of-sample:
- CAGR %
- benchmark CAGR % and excess
- max drawdown %
- volatility %
- trades
- win rate %
- avg win/loss %
- profit factor
- avg holding days
- exposure %
- best and worst trade

`warnings` always include:
- universe `current` only: "Survivorship bias: tested on today's Nifty 500 list; companies that dropped out are missing, so results look better than reality."
- universe `liquid500` only: "Universe: the 500 most-traded stocks each month (a stand-in for the Nifty 500 at the time), including companies that were later delisted." plus, when N > 0, "N stocks with price jumps that could not be explained were left out."
- "Price-only returns; dividends ignored."
- "Past results do not guarantee future returns."
- the fundamentals warning when it applies
- "Few trades (<30): results unreliable"
- "Trades last under 5 days on average: the entry and exit rules may contradict each other ..." (when `avg_days` < 5 and there are at least 30 trades; e.g. a pullback entry paired with a close-below-average exit churned at 4 days and lost money)
- "Out-of-sample result much worse than in-sample: likely overfit" (when OOS excess is more than 50% below in-sample excess)

### §12.4 API

```
POST /api/backtests body {name?, config} -> {id, run_id}          # always kind "explore" (T113)
POST /api/backtests/batch body {name?, configs:[config,...], names?:[str,...]} -> {ids:[...], run_id}
                                                                  # T119: optional names (same length as configs, else 400) are the row names instead of "<name> #<n>"
                                                                  # T116: 1-20 configs, each validated like POST /backtests (400 names the index,
                                                                  # nothing inserted); one explore row each ("<name> #<n>"), one backtest_batch job
POST /api/backtests/{id}/final -> {id, run_id, attempt}           # T113, §12.6
GET  /api/backtests -> [{id,name,status,kind,parent_id,created_at,finished_at,metrics:{is:{cagr,excess},oos:{cagr,excess}|null}}]
GET  /api/backtests/{id}   DELETE /api/backtests/{id}
POST /api/screens/{id}/backtest -> {id, run_id}
GET  /api/backtests/exits -> [{type,label,explain,params,when}]
```

### §12.6 Training and test periods (T113)

The test period must stay unseen while the owner tweaks a strategy, so the app never computes test-period numbers until asked.

- **Periods.** Training = `start` up to the day before `oos_start`. Test = `oos_start` to `end` (None = latest bar). `oos_start` None → resolved at create time to the `holdout_start` setting and stored in the config. Validation (400): `start < oos_start`, and `end` None or `end > oos_start`. The 70%-of-range default is gone.
- **Explore run** (`kind="explore"`, every `POST /backtests` and `POST /screens/{id}/backtest`): the engine runs with `end` = the day before `oos_start`, so no test-period bar is ever simulated. `metrics = {"is": compute_metrics(...whole run), "all": null, "oos": null, "oos_start": oos_start}`. Warnings as §12.3 minus the overfit check.
- **Final test** (`POST /backtests/{id}/final`): only for a `done` explore run (else 400). Creates a new row: same config, `kind="final"`, `parent_id=id`, name = parent name (or "Backtest {id}") + " (final)", and runs the full `start → end` with `split_metrics` as today. `attempt` = 1 + number of earlier `final` rows (any strategy, `legacy` excluded) whose test window overlaps this one's (a window is `[oos_start, end or today]`).
- **Fingerprint** = sha256 of the canonical JSON (sorted keys) of the config minus `start`, `oos_start`, `end`; stored on final rows. Same-fingerprint earlier finals = "this exact strategy was already tested".
- **Warnings on a final**, appended after §12.3's: when `attempt > 1`: "The test period has been looked at {attempt−1} time(s) before by other final tests. Each look makes it a weaker check." When an earlier final has the same fingerprint: "This exact strategy already had a final test (#{id}). Running it again does not make the result more reliable."
- **Batch UI (T119).** The backtest form has a closed-by-default "Run several at once" section: "Try several values" (one setting — max positions, starting money, or a numeric exit parameter — over 2–10 comma-separated values) or "Compare screens" (2–20 saved screens, same settings and exits). It posts to `/backtests/batch` with `names`, shows a toast and goes to the list. Helpers `varyOptions`, `parseValues`, `buildVariations`, `buildScreenBatch` live in `lib/backtests.ts`.
- **Explore count.** `GET /backtests/{id}` adds `explore_runs`: the number of explore rows created up to this one whose training window overlaps it. The UI shows it ("27 backtests have been run on this training period; the best of many always looks better than it really is").
- **Existing rows** become `kind="legacy"` (migration 009): shown as before (all/IS/OOS), never counted in `attempt`.
- **Score** (§10 `backtest` component) reads only `final` and `legacy` rows.

### §12.5 Point-in-time universe (`backtest/universe.py`, `backtest/history.py`; T086, T087)

Testing only today's Nifty 500 picks stocks *because* they later went up. `liquid500` approximates the index as it was at each date.

```python
# backtest/universe.py
def liquidity_ranks(conn=None) -> pd.DataFrame      # index 'YYYY-MM' (sorted), columns symbols, 1 = most traded
def eligible_mask(ranks, dates: pd.DatetimeIndex, symbol: str, top_n: int = 500) -> pd.Series   # bool aligned to dates
def candidate_symbols(ranks, start: str, top_n: int = 500) -> list[str]   # ever rank ≤ top_n in a month ≥ start−1 month, ∪ frames.universe()
# backtest/history.py
SPLIT_RATIOS = (1.25, 4/3, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 20, 25, 50, 100)
def repair_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame | None, int]   # (repaired copy or None = unrepairable, fixes applied)
```
- **Traded value** per raw bar = `value` if not NULL, else `close × volume`. Per symbol use its bars source (`frames.bars_source`, i.e. the first source in `ordered("bars")` that has rows for it), done in SQL by source, not per-symbol queries. Monthly figure = mean daily traded value in the calendar month. Rank input = rolling mean of the last 6 monthly figures (`min_periods=3`). Rank descending across symbols per month (`method="min"`); missing → NaN (never eligible).
- **Stored month sums (T117):** the price store (§7.4) keeps, per source, `(symbol, month, sum of traded value, count of non-null values)` for completed months (every month before the source's newest bar month). A rank run recomputes only months from the last stored completed month on, plus every month of symbols whose old bars changed; the monthly mean is `sum / count`, equal to the SQL `AVG`.
- **Not companies (T087a):** symbols whose `instruments.isin` starts with `INF` (ETFs and other fund units) or whose `instruments.series` is `RR` or `IV` (REIT/InvIT units) are left out of the ranks entirely. Symbols with no `instruments` row are kept.
- **Eligibility** of a signal on date d uses the rank of the calendar month *before* d's month (no look-ahead).
- **repair_frame** (applied only to candidate symbols that are not in `frames.universe()`; today's universe already has audited factors): up to 6 passes; find the first date where `close / prev close` is `> 1.45` or `< 0.55`. If it is a drop and `prev close / close` is within ±8% of a ratio k in `SPLIT_RATIOS` (smallest matching k), divide open/high/low/close before that date by k and multiply volume by k, then continue. Any rise > 45%, any unmatched drop, or a 7th jump → return `(None, fixes)`. Never mutates the input.
- The loader (`engine._load_real`, universe `liquid500`, frames not passed): ranks → candidates → `load_frame` each → `repair_frame` for non-universe ones (dropped ones are counted for the warning) → `eligible` masks. When frames are passed in (tests), the engine uses the `eligible` argument if given, else no mask.
- `_Data` ANDs the entry matrix with the eligible masks; exit signals are never masked.

---

## §13 Positions, checklists, journal, alerts and news matching

### §13.1 Checklist (`presets/checklist.json`)

Entry questions:

| id | label | type | required |
|---|---|---|---|
| `thesis` | Why will this go up in the next 1–4 months? | text | yes |
| `wrong_if` | What would prove me wrong? | text | yes |
| `catalyst` | Is there a catalyst or event coming up? | text | no |
| `source` | Where did the idea come from? | text | no |
| `entry_price` | Entry price | number | yes |
| `stop` | Stop-loss price | number | yes |
| `target` | Target price | number | yes |
| `time_stop_weeks` | Exit if nothing happens in N weeks | number | yes |
| `risk_pct` | Risk % of capital | number | yes |
| `read_announcements` | I have read the last 3 months of announcements | bool | must be true |
| `checked_results` | I have checked the latest quarterly results | bool | must be true |
| `emotion` | How am I feeling? (calm / FOMO / revenge / bored) | choice | yes |

Entry checklist (T095): when `next_results.date` ≤ entry date + `time_stop_weeks`, a warning callout says "Results on {D Mon} fall inside your {N}-week holding window. Decide now whether you'll hold through them." It never blocks submitting.

Exit questions: `exit_price`, `exit_reason` (stop / target / time stop / thesis broken / better opportunity / other), `thesis_right` (yes / partly / no) and `lesson`.

```
suggest(symbol, entry?, stop?) -> {last_close, atr14, suggested_stop, suggested_target, risk_per_share, qty, capital, risk_pct, rr}
   # stop = entry − atr_stop_multiple×ATR14; target = entry + 2×(entry − stop); qty = floor(capital×risk%/(entry−stop)), 0 if entry ≤ stop
GET  /api/positions/checklist/questions      GET /api/positions/suggest?symbol=&entry=&stop=   # response also has next_results {date,days}|null (T095)
POST /api/positions body {symbol, qty, entry_date, answers, ai_review?}
GET  /api/positions?status=open|closed -> [{...position, last_close, pnl_inr, pnl_pct, r_multiple, to_stop_pct, to_target_pct, days_held, days_to_time_stop, next_results}]
POST /api/positions/{id}/close body {exit_date, answers}     PUT /api/positions/{id} body {stop?, target?, time_stop_date?}
GET  /api/positions/{id}/checklists
GET  /api/journal/stats -> {closed, win_rate, avg_r, avg_win_pct, avg_loss_pct, thesis_right_pct, by_exit_reason, by_emotion}
GET  /api/watchlist   POST /api/watchlist {symbol, note?}   DELETE /api/watchlist/{symbol}
```

### §13.2 Alerts (`alerts/`)

```python
@dataclass(frozen=True)
class AlertDraft: kind: str; message: str; dedupe_key: str; symbol: str | None = None; link: str | None = None; severity: str = "info"
@dataclass(frozen=True)
class AlertScanner: kind: str; label: str; fn: Callable[[sqlite3.Connection, datetime], list[AlertDraft]]
def register(s: AlertScanner) -> AlertScanner
def all_scanners() -> list[AlertScanner]
# job alerts_scan runs every scanner; one failing scanner logs an error and the others still run
```

v1 scanners, one module each in `alerts/scanners/`:

| kind | when | severity | dedupe_key |
|---|---|---|---|
| `stop_near` | open position's last close within 3% above its stop | warn | `stop_near:{pos}:{date}` |
| `stop_hit` | **any** bar strictly after the entry date with low ≤ stop (the entry day's low may predate the fill). The message names the first such date and its low ("Stop hit on Tue 4 Nov, low ₹3,310"), so gaps while the app was closed aren't missed. | critical | `stop_hit:{pos}` |
| `target_hit` | **any** bar strictly after the entry date with high ≥ target (first date named) | info | `target_hit:{pos}` |
| `time_stop` | today ≥ time_stop_date and still open | warn | `time_stop:{pos}` |
| `announcement` | new announcement in an alerting category for a watchlist or open-position symbol, newer than when it was added | info (pledge → warn) | `ann:{id}` |
| `screen_new` | rows whose `first_seen` is today (one alert per screen per day; message = count + up to 5 symbols; a screen's first run also raises one) | info | `screen_new:{screen}:{date}` |
| `data_stale` | last_trading_date more than 2 weekdays (Mon–Fri; NSE holidays unknown) old **and** `runner.status()["updating"]` is false (no false alarms during catch-up) | warn | `stale:{last_trading_date}` |
| `results_due` | watchlist or open-position symbol with `calendar.next_results` days ≤ 7 (T098) | warn if held, else info | `results_due:{sym}:{date}` |
| `market_regime` | latest Nifty 500 crossing of its 200-day average, or breadth_above_sma 200 crossing 50, within the last 10 bars (T098) | down warn, up info | `regime:index:{date}` / `regime:breadth:{date}` |
| `trend_break` | open position's close crossed below sma(`position_exit_sma`) after entry (T099) | warn | `trend_break:{pos}:{crossing date}` |
| `trail_hit` | first bar after entry with low ≤ highest close since entry − `trail_atr_multiple`×ATR14 at entry (T099) | critical | `trail_hit:{pos}` |
| `screen_left` | open position's `source_screen_id` screen ran after entry and no longer contains it (T100) | info | `screen_left:{pos}:{screen}` |
| `catalyst` | announcement in order_win / credit_rating / block_deal / results / other_important in the last 5 days, reaction bar ≥ +3% on ≥ 2× 20-day volume, any universe symbol (T100) | info | `catalyst:{ann id}` |

`job_refused` alerts come from §3.4 directly.

Scanners get a read-only `db.connect()` and run outside any write transaction (they may call `frames.load_frame`); `alerts_scan` inserts all drafts afterwards in one transaction.

**Announcement categories** (`presets/announcement_categories.json`):
```jsonc
[{"category":"results","alert":true,"keywords":["financial result","results for the quarter"]},
 {"category":"pledge","alert":true,"severity":"warn","keywords":["pledge","encumbrance"]},
 {"category":"block_deal","alert":true,"keywords":["bulk deal","block deal"]},
 {"category":"order_win","alert":true,"keywords":["order","contract","letter of award","loa"]},
 {"category":"board_meeting","alert":true,"keywords":["board meeting"]},
 {"category":"credit_rating","alert":true,"keywords":["credit rating"]},
 {"category":"dividend","alert":false,"keywords":["dividend"]},
 {"category":"insider","alert":false,"keywords":["sast","insider trading","reg 7(2)"]},
 {"category":"routine","alert":false,"hidden":true,"keywords":["trading window","newspaper publication","loss of share certificate","duplicate share","compliance certificate"]},
 {"category":"other_important","alert":true,"keywords":["acquisition","merger","resignation","fire"]}]
```
- Categories are matched case-insensitively, first match wins. No match → `other` (no alert).
- `categorize(text) -> str` lives in `sources/store.py` and reads this JSON (cached).
- API:
  - `GET /api/alerts?unseen=1&kind=&limit=100`
  - `GET /api/alerts/count` → `{unseen}`
  - `POST /api/alerts/seen {ids?}`
  - `GET /api/alerts/kinds`

### §13.3 News symbol matching (`sources/store.py: match_symbols(text) -> set[str]`)

- The index is built from `symbols`: for each symbol, take the company name with suffixes ("Ltd", "Limited", "Ltd.", "India", "Industries", "Corporation", "Company", "& Co") stripped, if the result is at least 2 words or at least 6 characters.
- The symbol itself also counts, but only as an uppercase whole word in the title with at least 4 letters.
- Matching is case-insensitive and word-bounded, on the title + summary.

News API:
- `GET /api/news/announcements?symbol=&category=&include_hidden=0&limit=50`
- `GET /api/news/items?symbol=&limit=50`
- `GET /api/news/categories` → the preset

---

## §14 Frontend

The routes are registered in `src/routes.tsx` (§2.4). The sidebar nav order is listed below. On widths under 900 px it collapses into a top bar.

1. `/`: **Dashboard**
   - a **"Since you were away"** strip (since `last_visit_at`):
     - alerts raised
     - stocks newly in screens
     - each open position's move since the last visit
     - key watchlist announcements
     - hidden when there's nothing new
     - leaving the Dashboard calls `POST /api/dashboard/visit`, which sets `last_visit_at`
   - a **Refresh now** button (`POST /api/jobs/refresh`)
   - shortlist top 10 (score bar, reasons), marked "updating…" while `updating` is true
   - unseen alerts
   - data freshness
   - open positions summary
2. `/screener`: **Screener**
   - screen list and results table
   - **rule builder** (dropdowns grouped as Price / Indicators / Fundamentals / Number, params with min/max, `explain` tooltips, all/any groups, op words from `/api/rules/ops`)
   - Preview / Save / Run / Backtest this
   - a "Describe a screen in words" box (AI)
3. `/stock/:symbol`: **Stock** (not in the nav)
   - header, showing the data source as a small tag
   - chart (candles, volume, overlays, RSI pane, action markers)
   - fundamentals panel with a per-field source tag
   - quarterly table
   - announcements and news
   - Ask Claude
   - Start checklist
4. `/positions`: **Portfolio**
5. `/journal`: **Journal**
6. `/backtests` (+ `/backtests/:id`): **Backtests**
   - the form builds exits from `/api/backtests/exits`
   - equity vs Nifty 500 yardstick, IS/OOS marker, metric cards, an always-visible warnings box, trades
   - T114: `/backtests/new` (`?screen=ID` preselects that screen, `?from=ID` copies a backtest's config) is the only way to start one; the Screener's "Backtest this" opens it. Period section: Train from / Test from / Test until. Explore result: training metrics only, a locked test-period card with "Run final test" (inline confirm) and "Tweak and rerun". Final result: all/IS/OOS + "Final test · attempt N" badge + parent link. Settings: `holdout_start`
6a. `/track-record`: **Track record** (§16.6)
7. `/jobs`: **Jobs**
   - Pause all
   - jobs grouped by `group`: "App", then one group per source
   - schedule editor, toggles, run now
   - run history and a run drawer (live progress, failed items with Retry failed, log tail, Stop)
   - a "Data checks" tab
8. `/sources`: **Sources**
   - one card per source: label, description, homepage, enabled switch (shows `paused_reason`), capabilities (with an "already adjusted" badge for bars), its jobs (links), 7-day ok/failed/not-found stats, last error
   - a secrets form for sources that need keys (shows set / not set, never the value)
   - a **Priority** panel: for each capability, a drag-to-reorder list (up/down buttons are fine) of the sources that have it
   - a **Coverage** panel per capability
9. `/alerts`: **Alerts**
10. `/settings`: **Settings**
    - money and risk, score weights (sliders built from `/api/score/components`), RSS feeds
    - AI provider and model (from `/api/ai/status`), costs, appearance
    - custom indicators
    - backup (`POST /api/backup`)

**Shared:**
- `api/client.ts`: `api.get/post/put/del<T>()`, throwing `ApiError{status,message}`
- `api/types.ts`
- Ctrl+K symbol search
- an alert badge, polled every 60 s
- a **header status indicator**, polling `/api/jobs/status` every 5 s while updating and every 60 s otherwise. While updating it shows "Updating: <job title> 3/5…" with a link to Jobs; otherwise "Data as of Fri 6 Nov". Pages that show analysis (Stock, Screener, Dashboard) repeat "data as of <date>" near their numbers.
- `<Explain text>`
- `<Num value kind="pct|inr|cr|plain">` (Indian grouping: `₹1,23,456`)
- light/dark themes, following `prefers-color-scheme`, with a toggle

---

## §15 Definition of done (every ticket)

1. Only the files the ticket lists are created or changed, plus their tests.
2. All of the following pass:
   - `cd backend && .venv/bin/pytest -q`
   - `cd backend && .venv/bin/ruff check app tests`
   - for frontend tickets: `cd frontend && npm run build && npm test`
3. **No network access in tests.**
4. The ticket's status is set to `done` in `tickets/README.md`.
5. One commit: `T0NN: <ticket title>`.

---

## §16 Signal log and forward test (`signals/`)

**Why:** `screen_results` is replaced on every run and the shortlist is never stored, so the app cannot prove its ideas work on data it had not seen. The signal log is an **append-only** record of every new idea at the moment it appeared. A nightly step then measures what happened next, using the same exit rules and costs as the backtester. Nothing here is a trade; it is a paper record.

### §16.1 Tables (added to `schema.sql`; `SCHEMA_VERSION = 2`)

```sql
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL CHECK (source IN ('screen','shortlist')),
  screen_id INTEGER NOT NULL DEFAULT 0,          -- 0 for shortlist rows; NO foreign key (history outlives screens)
  screen_name TEXT,                              -- copied at log time; NULL for shortlist rows
  symbol TEXT NOT NULL,
  as_of TEXT NOT NULL,                           -- the bar date the signal fired on (YYYY-MM-DD)
  rank INTEGER,                                  -- shortlist rank 1..10; NULL for screen rows
  score REAL, components TEXT,                   -- score and {component: value} JSON at log time (NULL if unscored)
  reasons TEXT NOT NULL DEFAULT '[]',            -- JSON list of strings
  planned_entry REAL NOT NULL,                   -- close on as_of (adjusted as of log time; audit only)
  atr14 REAL NOT NULL,                           -- ATR(14) on as_of, same basis as planned_entry
  planned_stop REAL NOT NULL, planned_target REAL NOT NULL,
  exit_config TEXT NOT NULL,                     -- JSON, frozen: {"exits":[...], "notional_inr":100000}
  rule_hash TEXT,                                -- sha1 of score.canonical(rule) for screen rows; NULL for shortlist
  score_weights TEXT NOT NULL,                   -- JSON of the score_weights setting at log time
  app_version TEXT NOT NULL,                     -- `git rev-parse --short HEAD` of the repo, or "unknown"
  bars_as_of TEXT NOT NULL,                      -- frames.last_trading_date() at log time
  created_at TEXT NOT NULL,
  UNIQUE (source, screen_id, symbol, as_of));
CREATE INDEX IF NOT EXISTS signals_as_of ON signals(as_of);
CREATE TRIGGER IF NOT EXISTS signals_no_update BEFORE UPDATE ON signals
  BEGIN SELECT RAISE(ABORT, 'signals is append-only'); END;
CREATE TRIGGER IF NOT EXISTS signals_no_delete BEFORE DELETE ON signals
  BEGIN SELECT RAISE(ABORT, 'signals is append-only'); END;

CREATE TABLE IF NOT EXISTS signal_outcomes (     -- 1:1 with signals; freely recomputed
  signal_id INTEGER PRIMARY KEY REFERENCES signals(id),
  status TEXT NOT NULL CHECK (status IN ('pending','open','closed','no_data')),
  entry_date TEXT, entry_fill REAL, gap_pct REAL,          -- gap_pct = (next open / as_of close - 1) * 100
  stop_level REAL, target_level REAL,                       -- re-anchored to entry_fill
  exit_date TEXT, exit_fill REAL, exit_reason TEXT,         -- reason as the backtester: stop|target|time stop|exit rule
  days_held INTEGER,
  return_pct REAL,                                          -- net of costs on notional_inr; unrealised for 'open'
  r_multiple REAL,                                          -- (exit_or_last - entry_fill) / (entry_fill - stop_level), price-only
  mfe_r REAL, mae_r REAL,                                   -- best high / worst low since entry, in R
  stock_cc_pct REAL, nifty_cc_pct REAL, excess_pct REAL,    -- close-basis: entry_date close -> exit_date (or last) close
  last_bar TEXT, updated_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS signal_days (         -- coverage: one row per bar date the logger ran for
  as_of TEXT PRIMARY KEY, logged INTEGER NOT NULL, run_at TEXT NOT NULL);
```

- Deleting a screen never touches `signals` (no FK, no cascade). `screen_name` keeps it readable.
- `init_db` already re-runs `schema.sql` when `user_version < SCHEMA_VERSION`; the DDL above is idempotent, so bumping `SCHEMA_VERSION` to 2 is the whole migration.
- New setting (§5): `signal_target_atr_multiple`, default `4.0`, range 0.5–20.

### §16.2 Logging (`signals/log.py`)

```python
def exit_config(conn=None) -> dict
    # {"exits":[{"type":"stop_atr","params":{"k":atr_stop_multiple}},
    #           {"type":"target_atr","params":{"k":signal_target_atr_multiple}},
    #           {"type":"time_stop","params":{"days":default_time_stop_weeks*5}}],
    #  "notional_inr":100000}
def log_signals(shortlist: list[dict] | None = None) -> dict   # -> {"as_of", "screen": n, "shortlist": n}
```

- **Screen rows:** every `screen_results` row with `first_seen == timeutil.today()` → one `signals` row (`source='screen'`, `as_of` = that row's `as_of`).
- **Shortlist rows:** `shortlist` = `score.score_candidates()` (computed by the caller once and passed in; `None` → compute it). Take the top 10. A symbol is logged only if it was **not** in the top 10 stored under the internal setting `signal_last_top10` (a JSON list of symbols). After logging, the current top 10 replaces that setting. If the setting does not exist yet (first ever run) the top 10 is stored and **nothing** is logged. `as_of` = the symbol's newest `screen_results.as_of`.
- Every row (both sources) carries the symbol's `score`, `components` and `reasons` from the shortlist if it is in it (any rank), else NULL / `[]`.
- `planned_entry` = close on `as_of`; `atr14` = `indicators.compute("atr", frame, bench, n=14)` on `as_of`; `planned_stop`/`planned_target` from `exit_config` k values. A symbol with no frame or NaN ATR is skipped (logged as a warning), never written with NULLs.
- Insert with `INSERT OR IGNORE` (the UNIQUE key makes repeats harmless: a manual "Run now" and the nightly run cannot double-log).
- Upsert `signal_days(as_of = frames.last_trading_date(), logged = rows inserted this call)`.
- **No seeding:** existing screen members have older `first_seen`, so day one logs nothing from screens.
- Load frames **outside** any write transaction (§ gotcha: never call `load_frame` inside `db.tx()`).

### §16.3 Outcomes (`signals/outcome.py`)

```python
def compute_outcome(signal: dict, frame: pd.DataFrame, bench: pd.Series, model: dict,
                    newest_bar: str) -> dict   # pure: returns the signal_outcomes columns (no signal_id/updated_at)
def update_outcomes(ctx=None) -> dict         # -> {"pending","open","closed","no_data"} counts after the pass
```

- `compute_outcome` reuses `backtest.exits` (`EXITS[type].setup` / `.check`, `resolve_params`) and `backtest.costs` (`fill_price`, `trade_costs`). **No second copy of exit logic.** Exit order is the engine's: intraday exits with stops before targets, then close exits; a "next open" fill (`None`) exits on the following bar's open.
- The frame is the **current adjusted** frame (`frames.load_frame`). Levels are rebuilt from it: `atr14` = ATR(14) of this frame on `as_of`; the setup position is `{"entry_fill": fill_price("buy", open on the first bar after as_of, model), "atr14": atr14}`. Stored `planned_*` values are never used for the maths (they may be on a pre-split basis).
- `days_held` counts bars from the entry bar (entry bar = 0), as the engine does.
- Status:
  - `pending`: no bar after `as_of` yet
  - `open`: entered, no exit yet; return/R/MFE/MAE/close-basis use the last close (unrealised)
  - `closed`: an exit fired
  - `no_data`: not closed and the symbol's last bar is more than 14 calendar days older than `newest_bar`
- `return_pct`: qty = floor(notional_inr / entry_fill) (min 1); `(sell value − sell cost − buy value − buy cost) / (buy value + buy cost) × 100`, with `fill_price("sell", …)` on the exit. For `open`, the sell is valued at the last close with the same costs.
- `r_multiple`, `mfe_r`, `mae_r` are price-only (no costs), relative to `entry_fill` and risk `entry_fill − stop_level`. MFE/MAE scan bars from the entry bar to the exit bar inclusive (high/low).
- Close-basis: `stock_cc_pct` = close(exit_date or last bar) / close(entry_date) − 1; `nifty_cc_pct` the same over the benchmark (nearest benchmark date on or before); `excess_pct` = difference. All × 100.
- `update_outcomes` recomputes every signal whose outcome is missing or not `closed`, plus `closed` rows whose `last_bar` is older than the newest bar of that symbol (catches late data). It loads frames outside the write transaction and upserts rows. Gap-proof: it always replays from the entry bar.

### §16.4 Job

| job | schedule | stage / lane | follow-ups |
|---|---|---|---|
| `signals_track` | manual (follow-up only) | 7 / background | `alerts_scan` |

- `screens_run`'s follow-ups become `("signals_track",)`; `signals_track` follows up with `alerts_scan`. Chain: `screens_run → signals_track → alerts_scan`.
- Run: compute the shortlist once, `log_signals(shortlist)`, then `update_outcomes(ctx)`. Message: `"logged N new (S screen, L shortlist); open O, closed C"`.

### §16.5 API (`api/signals.py`)

```
GET /api/signals?source=&screen_id=&status=&symbol=&limit=200&offset=0
    -> {total, rows:[{id,source,screen_id,screen_name,symbol,name,as_of,rank,score,reasons,
                      planned_entry,planned_stop,planned_target,app_version,
                      outcome:{status,entry_date,entry_fill,gap_pct,exit_date,exit_fill,exit_reason,
                               days_held,return_pct,r_multiple,mfe_r,mae_r,excess_pct} | null}]}   newest as_of first
GET /api/signals/ideas?status=&source=&screen_id=&q=&since=&limit=50&offset=0        (T111, §16.7)
    -> {total, counts:{open,pending,closed,no_data},
        rows:[{id, symbol, name, first_as_of, last_as_of, score, reasons,
               planned_entry, planned_stop, planned_target, current_price,
               seen:[{signal_id, as_of, source, screen_id, screen_name, rank, score}],   oldest first
               outcome:{…same fields as /signals…} | null}]}
GET /api/signals/summary
    -> {groups:[{key,label,kind,n_closed,n_open,n_pending,hit_rate_pct,avg_return_pct,avg_r,
                 avg_excess_pct,avg_days,enough}],
        coverage:{first_day,last_day,days_logged,trading_days},
        min_closed: 30, n_signals, n_ideas}
```

- `/signals` stays the raw, ungrouped log (audit and debugging). The UI uses `/signals/ideas`.
- `/signals/ideas`: `id` = the anchor's signal id. `status` matches the idea's outcome status (`pending` also matches a missing outcome). `source`/`screen_id` match when **any** entry in `seen` matches. `q` is a case-insensitive substring of the symbol or company name. `since` (YYYY-MM-DD) keeps ideas with `last_as_of >= since`. `counts` apply every filter except `status`. Sorting: when `status=closed`, by `exit_date` descending; otherwise by `first_as_of` descending; then by `id` descending.
- **Summary counts ideas, not loggings (T111):** every stat below is over ideas (§16.7). An idea counts once in each screen group that any of its loggings came from. Rank groups use the idea's best shortlist rank, and score bands the idea's score.
- Groups, in this order: one per screen (`kind="screen"`, key `screen:<id>`, label = latest `screen_name`); `shortlist:rank1-3`, `shortlist:rank4-10` (`kind="rank"`); score bands over **all** signals with a score: `band:75+`, `band:60-75`, `band:<60` (`kind="band"`; 60 ≤ s < 75 is the middle band).
- Stats use **closed** signals only: `hit_rate_pct` = share with `return_pct > 0`; averages are means over closed; `enough` = `n_closed >= 30`. Null averages when `n_closed == 0`.
- `coverage.trading_days` = count of distinct benchmark dates from `first_day` to `last_day`.

### §16.6 UI (`/track-record`: **Track record**, nav after Backtests)

- A short plain-English intro: "Every new idea is recorded the day it appears, then followed with your stop, target and time stop. This is the honest test: none of it was known when the idea was logged."
- Coverage line: "Logging since <first_day>: <days_logged> of <trading_days> trading days" with an `<Explain>` that days the app was off can't be logged.
- Summary table, one row per group: Signals closed / open, Win rate, Avg return, Avg R, Beat Nifty by, Avg days. Rows with `enough=false` show a "too early" badge and greyed numbers. Every column header has an `<Explain>`.
- Under the summary card: "<n_signals> loggings grouped into <n_ideas> ideas" with an `<Explain>`.
- **Every logged idea** (T112; replaces the old 13-column signals table): lists ideas from `/signals/ideas`. Tabs: Open · Pending entry · Closed · All, with counts. Filters: stock search, source, screen, and a 7 / 30 / 90 days / All time range (default 90 days). Filters live in the URL. Slim table: Stock, Logged, From, Status, Stop to target (Ended on the Closed tab), Return, R. 50 rows per page. Selecting a row opens a sticky detail panel with the plan, the result, the "Picked N times" timeline and the reasons. Keys: `j`/`k` move, `/` searches, `Esc` clears. T112 has the full detail.

### §16.7 Ideas (`signals/ideas.py`, T111)

```python
def group_ideas(sigs: list[dict]) -> list[dict]
    # sigs: logging rows with signal + outcome columns, any order.
    # -> ideas, each {"anchor": <logging dict>, "members": [<logging dicts>, oldest first]}
```

- An **idea** is one stock's loggings, grouped while the first is being followed. Process each symbol's loggings in `(as_of, id)` order. A logging joins the symbol's current idea when the idea's anchor is not `closed`, or when the logging's `as_of` < the anchor's `exit_date`. Otherwise it starts a new idea and becomes its anchor.
- The idea's plan, outcome and `id` are the anchor's. `score` = the highest member score (null if none). `reasons` = all members' reasons merged in first-seen order without duplicates. `first_as_of`/`last_as_of` = the anchor's and the last member's `as_of`.
- Later members are context only (the "seen again" timeline). They don't change the outcome. A trade is graded once, from the first day the app saw it.
- Derived on every read; nothing is stored, and `signals` stays append-only.

---

## §17 Cloud deployment (nse-radar)

Owner decision, 2026-11-24: nse-radar is a **copy of stock-tools that runs in the cloud on free tiers**, so it opens from the phone or any browser without the laptop. The laptop app (`~/ketul/claude_projects/stock-tools`) stays exactly as it is, and the two never sync. nse-radar's price history is seeded **once** from a read-only copy of the laptop DB (§17.6). After that nse-radar fetches its own data.

Where this section and older sections disagree, **§17 wins**. Older sections still describe what the code does: the engine, data model, rules and UI are unchanged except where §17 says otherwise.

### §17.1 The three pieces

```
phone / laptop browser
   │  HTTPS (password cookie, §17.5)
   ▼
Vercel Hobby ── static React build (frontend/dist)
   │            + one Python function: the FastAPI app (api/index.py), light routes only
   │  libsql over HTTPS (remote)                      POST workflow_dispatch (§17.4)
   ▼                                                        │
Turso (free) ── the database (same schema as §4) ◄──────── GitHub Actions (public repo)
                                                  embedded   drain.yml / daily.yml: runs jobs —
                                                  replica    fetches, screens, alerts, signals,
                                                             backtests, Screener, backup
```

| Piece | Free-tier limits that shape the design (checked 2026-11-24) |
|---|---|
| **Vercel Hobby** | Python bundle ≤ 500 MB unzipped; a function gets 2 GB / 1 vCPU and at most 300 s (fluid compute); 4 active-CPU hours and 1M invocations a month; crons at most daily (we use GitHub's cron instead). Non-commercial use only. |
| **Turso free** | 5 GB storage, **500M rows read** and **10M rows written** a month, 1-day point-in-time restore. The seeded DB is ~370 MB, of which bars ≈ 8.9M rows. A full read of `bars` costs ~2% of the monthly read allowance, so **nothing on Vercel may scan `bars` broadly**, and bulk work reads from the Actions replica (§17.3). Turso announced on 2026-10-02 that Supabase is acquiring it; re-check the limits if the plans change. |
| **GitHub Actions (public repo)** | Unlimited free minutes on standard runners (4 vCPU, 16 GB RAM, ~14 GB disk); 6 h per job; cache 10 GB per repo; scheduled workflows may start up to ~an hour late and are **disabled after 60 days without repo activity** (§17.4 keep-alive). Logs, artifacts and the code are public (§17.8). |

### §17.2 Runtime modes (`app/config.py`)

```python
# app/config.py additions (N002)
RUNTIME = os.environ.get("STOCK_RUNTIME", "local")     # "local" | "vercel" | "actions"
TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")    # libsql://<db>-<org>.turso.io ; empty -> local SQLite file
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
REPLICA_PATH = os.environ.get("STOCK_REPLICA_PATH", "") # actions only: embedded replica file
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")         # "owner/nse-radar" (Vercel: to dispatch workflows)
```

| | `local` (dev, tests) | `vercel` | `actions` |
|---|---|---|---|
| Database | SQLite file `DB_PATH` (or Turso if `TURSO_DATABASE_URL` is set: dev against the live DB, like reel-radar) | Turso **remote** (every query is an HTTPS round trip) | Turso **embedded replica** at `REPLICA_PATH`: reads are local, writes go to Turso, `db.sync()` pulls |
| Worker + scheduler threads | yes, as on the laptop | **never** | never (the drain CLI runs jobs in the foreground, §17.3) |
| `init_db()` / migrations | at startup | **never** (reads `user_version`; if it's behind `SCHEMA_VERSION`, `/api/health` says `"schema": "update pending"`) | first step of every drain |
| Enqueued job | picked up by the local worker | `runner.enqueue` + `dispatch.kick()` after commit (§17.4) | picked up by the same drain |
| In-memory caches (`frames`, `indicators`, price store) | as on the laptop | price store **off**; frame cache entries live at most `VERCEL_CACHE_TTL_S` = 300 s | as on the laptop, price store cached between runs (§17.3) |
| Custom indicators (§8) | loaded | **never loaded or executed** | loaded (approved code runs only here) |
| AI provider | `claude_cli` if present | copy-prompt only (§17.7) | none |

Tests run in `local` mode on SQLite, as today. Nothing in tests touches Turso, GitHub or the network.

### §17.3 Jobs without threads: the drain (GitHub Actions)

`python -m app.jobs.drain [--tick] [--budget-min N] [--lane background|interactive|all]` (N004), run with cwd `backend/`:

1. `db.sync()` (replica), `db.init_db()` (migrations, defaults), `bootstrap.load_plugins()`, `scheduler.ensure_schedules()` (needs the registered jobs), `runner.recover_on_startup()`.
2. With `--tick`: `scheduler.tick(now)`, so every due job, including the startup catch-up (§6.2), is enqueued.
3. Loop: `runner.run_one("interactive")`, else `runner.run_one("background")`, until nothing is queued or the budget (default 100 min) runs out.
4. **Budget reached:** the running job is asked to stop (`request_stop`, which every job already honours, §6), ends `cancelled` with `stop_requested=1` (the runner's way of recording a stop), and is enqueued again with the same params and trigger `system` (the `job_runs.trigger` CHECK has no `resume`; decided after N004). Source jobs are gap-proof and item-based (`job_items`), so the next drain continues where this one stopped. The drain exits 0.
5. Exit: `db.sync()`, then print a summary of **counts only** (jobs run, ok/failed, rows written, minutes). See §17.8 on what may be logged.

**Replica and price store between runs:** the workflow restores `data/replica.db` and `data/cache/price_store.pkl` from `actions/cache` (key `replica-<run_id>`, restore-key `replica-`), and saves them at the end. A cache miss means a full replica sync (~9M rows read, fine a few times a month). Writes made by Vercel since the last run arrive with `db.sync()`.

**Backtests** run in the drain like any job (`backtest`, `backtest_batch`), with `backtest_workers` = 3 on the 4-vCPU runner (§12, T118). They never run on Vercel.

### §17.4 Workflows and dispatch (`.github/workflows/`, `app/cloud/dispatch.py`)

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | push, pull_request | backend `pytest -q` + `ruff check app tests`; frontend `npm run build` + `npm test`. No secrets. |
| `drain.yml` | `workflow_dispatch` (input `reason`), `workflow_call` | the drain (§17.3) with `--lane all`. `concurrency: {group: drain, cancel-in-progress: false}`, so one runs at a time and at most one waits. Timeout 150 min. Secrets: `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `BACKUP_PASSPHRASE`. |
| `daily.yml` | `schedule`: `15 13 * * 1-5` (18:45 IST, after the bhavcopy is out) and `30 2 * * *` (08:00 IST catch-up) | calls `drain.yml` with `--tick`. |

**Dispatch from Vercel (N005):** `dispatch.kick(reason: str) -> bool` POSTs `https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/drain.yml/dispatches` with `{"ref": "main", "inputs": {"reason": reason}}` and `Authorization: Bearer $GITHUB_DISPATCH_TOKEN` (a fine-grained token: this repo only, Actions read/write). It is called through `db.after_commit` from `runner.enqueue` when `RUNTIME == "vercel"`. It is debounced with settings key `last_dispatch_at`: no new dispatch within 60 s of the last one, because the waiting drain will pick up every queued job anyway. Failures are logged and return False. The job stays queued and the next dispatch or schedule runs it. The UI shows queued jobs as "waiting for the cloud worker (usually 1–2 min to start)".

**Keep-alive:** GitHub disables scheduled workflows after 60 days without repo activity. (1) Every `daily.yml` run first calls `gh workflow enable daily.yml` with the job's `GITHUB_TOKEN` (`permissions: actions: write`), the same approach as the common keep-alive actions. (2) Belt and braces: on any `/api/cloud/status` call, at most once every 7 days (settings key `last_keepalive_at`), Vercel calls `PUT /repos/{GITHUB_REPO}/actions/workflows/daily.yml/enable`, which is harmless when the workflow is already enabled.

### §17.5 Vercel app and the password gate

- `api/index.py` (repo root) puts `backend/` on `sys.path`, sets `STOCK_RUNTIME=vercel` if unset, and exposes `app` from `app.main`. `vercel.json`:
  - `buildCommand`: `cd frontend && npm ci && npm run build`; `outputDirectory`: `frontend/dist`
  - rewrites: `/api/(.*)` → `/api/index`; everything else → `/index.html` (SPA)
  - `regions`: `["iad1"]` (next to the Turso DB in aws-us-east-1, §17.11)
  - `functions["api/index.py"]`: `maxDuration` 60, `excludeFiles` for `backend/tests/**`, `frontend/**`, `docs/**`, `tickets/**`
  - `ignoreCommand`: skip deploys when only `*.md`, `tickets/`, `docs/`, `backend/tests/` or `.github/` changed (keeps Vercel usage low)
- Python deps for Vercel: root `requirements.txt`, the runtime deps of §2.2 plus `libsql`, minus `uvicorn` and `yfinance` (adapters whose library is missing are skipped, `plugins.import_all`). Vercel never fetches from data sources.
- **Light routes only:** a Vercel request may make at most ~50 SQL statements and must never call `frames.load_frame` for more than a few symbols, `price_store`, or anything that loops over `bar_symbols`. Heavy work is a job (§17.3) whose results the UI reads. N009 audits every route against this rule and records the result in `docs/CLOUD_ROUTES.md`.
- **Password gate (N008):** if env `APP_PASSWORD` is set, every `/api/*` path except `/api/health` and `/api/login` needs the cookie `nr_session` = `<expiry>.<hmac_sha256(APP_SECRET, expiry)>` (HttpOnly, Secure, SameSite=Lax, 90 days). `POST /api/login {"password"}` → 204 + cookie, or 401 after a constant-time compare. `POST /api/logout` clears it. Otherwise → 401 `{"detail": "login required"}`, and the frontend shows `/login`. With `APP_PASSWORD` unset (local dev) the gate is off.

Vercel env: `STOCK_RUNTIME=vercel`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `APP_PASSWORD`, `APP_SECRET`, `GITHUB_REPO`, `GITHUB_DISPATCH_TOKEN`.

### §17.6 Seeding from the laptop (one time)

`scripts/make_seed.py --from ~/ketul/claude_projects/stock-tools/data/stock.db --out data/seed.db` (N003):
- Opens the laptop DB **read-only** (`file:…?mode=ro` URI) and `VACUUM INTO` the output. The laptop app may keep running; nothing in stock-tools is written.
- On the copy only: deletes `job_runs`, `job_items` and `ai_requests` history and the laptop backup alerts. Sets `ai_provider` = `"copy_prompt"`, `backtest_workers` = 3, `jobs_paused` = false. Drops the laptop-only `backup*` settings rows so defaults apply. Sets `journal_mode=WAL` (Turso import needs it). Runs `quick_check`, prints the row counts per table and the file size.
- Prints the owner's next command: `turso db create nse-radar --group us --from-file data/seed.db` (§17.11). A file import doesn't count against the 10M monthly row writes; inserting 8.9M rows through SQL would use most of them.

### §17.7 AI in the cloud

There is no `claude` CLI on Vercel or Actions, and no API key (§1). The provider `copy_prompt` (N010): `available()` → `(True, "copy the prompt into Claude, then paste the answer back")`. When it's the provider, the AI buttons open a dialog with the full prompt (Copy button) and a "Paste Claude's answer" box. Saving stores the answer in `ai_requests` as if a provider had returned it, so the existing result views, JSON parsing (`tasks/_json.py`) and follow-ups work unchanged.

### §17.8 Public repo: what must never be public

The code, Actions logs and artifacts are world-readable.
- **Never print private data in jobs:** no rows from `positions`, `journal`, `watchlist` notes, `ai_requests`, `checklists` or settings values. Drain output is counts only. In `actions` mode the root log level is WARNING, `app.jobs.drain` logs at INFO, and job messages stay in `job_runs` (Turso).
- **Backups (N011):** the weekly `backup` job in `actions` mode writes `data/backups/nse-radar-YYYY-MM-DD.db.gz`. A workflow step encrypts it with `openssl enc -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE` and uploads it as an artifact with 90-day retention. An unencrypted backup never leaves the runner. `docs/CLOUD_SETUP.md` shows how to decrypt.
- Repo setting (owner): Actions → "Require approval for all external contributors", so a fork's pull request can't run a modified workflow that reads the replica cache.
- Secrets live only in GitHub Actions secrets, Vercel env and the gitignored `.env.local`.

### §17.9 Phone layouts (frontend)

The app is opened from the phone, so every page works below 768 px. This is unchanged from the stock-tools phase-19 design:
- **Phone = viewport under 768 px**, from `lib/useIsPhone.ts` (`matchMedia("(max-width: 767px)")`, live). At 768 px and wider nothing changes: the laptop UI stays exactly as it is.
- **Shell:** no sidebar on a phone. A top bar shows the page title, a search button (opens the command palette full-screen), the status dot and the alert badge. A **bottom tab bar** has 5 items: Dashboard, Screener, Watchlist, Portfolio, More. "More" opens a sheet with every other nav route grouped as in the sidebar, plus the theme toggle. `AppRoute` gains `phoneTab?: number` (1–4) to place the four tabs.
- **Lists:** `DataTable` on a phone renders each row as a card. Columns opt in with `meta.phone`: `"title"` (one; defaults to the first column), `"subtitle"`, `"hide"`, or default (a label–value pair in a 2-column grid, at most 6 shown, the rest behind "More"). Sorting moves into a "Sort by" select above the cards. Row click and `renderExpanded` work as before.
- **Forms and dialogs** are full-screen sheets on a phone. Touch targets are at least 40 px. Hover-only `<Explain>` tooltips also open on tap.
- **Charts** use the container width, a height of 60% of the viewport width (min 220 px), and touch pan/zoom (lightweight-charts' own handling).
- Tests use a `matchMedia` stub (`src/__tests__/phone.ts` helper `setPhone(true|false)`).

### §17.10 Repo additions

```
api/index.py  vercel.json  requirements.txt  .env.example
.github/workflows/  ci.yml  drain.yml  daily.yml  (spike.yml, N001 only)
backend/app/cloud/  __init__.py  dispatch.py  auth.py
backend/app/jobs/drain.py
scripts/make_seed.py  scripts/spike_cloud.py
docs/CLOUD_SETUP.md  docs/CLOUD_SPIKE.md  docs/CLOUD_ROUTES.md
```
New dependency: `libsql` (Python, the Turso driver). Nothing else unless a ticket allows it.

### §17.11 Spike findings that are now contracts (N001, `docs/CLOUD_SPIKE.md`)
- The Turso DB lives in group `us`, **aws-us-east-1**, next to GitHub's runners and Vercel `iad1`. A remote statement costs 3–4 round trips, so distance dominates.
- libsql rows are tuples and its errors are `ValueError`s: `db.connect()` in Turso mode returns the N002 wrapper, never a raw libsql connection.
- `executemany` is batched by the wrapper. Job code that writes in a per-row loop is slow remotely (~20 ms+ per statement even in-region); when a drain shows a slow job, batch its writes with `executemany`.
- Turso's free plan also caps **embedded syncs at 3 GB/month**, so keep the replica in the Actions cache.
- Turso refuses `PRAGMA user_version=N`. The schema version is `db.schema_version(conn)`: `user_version`, or the one-row `schema_meta` table when the PRAGMA was refused. Never read `PRAGMA user_version` directly in new code.
- DDL run through Turso gets keyword column names uppercased (`key`, `rows`, `explain`, `trigger` → `KEY`…). The wrapper lowercases all-caps column names in results. Never use an all-caps column alias.

### §17.12 Contract changes from the route audit (N009, `docs/CLOUD_ROUTES.md`)
These override §8.3 and §10 where they differ.
- `POST /api/screens/preview` → `{"run_id": int}` (job `screen_preview`). The matches are the run's `ok` `job_items` (key = symbol, detail = the values as JSON).
- `POST /api/custom-indicators/{id}/approve` → the still-pending indicator plus `run_id` (job `indicator_approve`). `sample` is no longer in the response; the 5 sample values are in the run's message.
- Precomputed results that Vercel reads: settings `score_prices` (written by `screens_run`) and `bars_coverage` (written by `housekeeping`).

