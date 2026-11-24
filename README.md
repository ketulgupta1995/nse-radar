# nse-radar


> Cloud copy of stock-tools (Vercel + Turso + GitHub Actions). See `docs/SPEC.md` §17 and `tickets/README.md`. To put it online, follow **[docs/CLOUD_SETUP.md](docs/CLOUD_SETUP.md)**.

A **single-user research app** for Indian stocks (NSE). It runs in the cloud and opens in any browser, including on your phone.

**Purpose:** stay informed and get **data-backed, tested** stock ideas for holding periods of a few weeks to 3–4 months, using daily prices. There is no buying, no selling and no broker link.

> **This is not financial advice.** It shows ideas to research and how a rule would have done on past prices. Past results do not guarantee future returns. Check the checklist and make your own decisions.

## Local dev

Needs Python 3.13, Node 22 and npm. From this folder:

```bash
./start.sh --dev
```

This runs the auto-reloading API plus the vite dev server against a local SQLite file (`data/stock.db`); Ctrl+C stops both. The first run creates the Python environment and installs the packages.

The cloud deployment (Vercel for the app, Turso for the database, GitHub Actions for the background jobs) is set up once by following [docs/CLOUD_SETUP.md](docs/CLOUD_SETUP.md).

## Daily use

Open the **Dashboard** first. It shows what changed since you last looked, the alerts that need attention, today's ranked shortlist and your positions. **Refresh now** fetches the latest data. The line in the sidebar always shows how fresh the data is.

## The first full load

On a fresh install the Dashboard shows a **first-run panel** with two buttons: load the stock list, then load recent prices. After that the rest fills in by itself:

| What | Roughly how long |
|---|---|
| Price history (NSE bhavcopy backfill) | about 10 hours |
| Quarterly results | about 17 hours |
| Screener.in fundamentals | about 9 hours |
| Price history from the second source, corporate actions, announcements | about 10–20 minutes each |

**Leave the laptop and the app running for 1–2 days** for the first load. The jobs are deliberately slow and polite to the websites. Watch them on the **Jobs** page. Afterwards, about an hour a day keeps everything fresh, and the app catches up on any gaps by itself when it starts.

**Keep the laptop awake** during those days: Windows Settings → System → Power → set "Screen and sleep" to *Never* while plugged in. You can set it back afterwards.

## What the background jobs do

Jobs run in stages, in this order. Each can be paused, stopped or run on demand from the Jobs page, which also shows the full history.

- **Stock list** (`universe.*`): the Nifty 500 list, weekly.
- **Prices** (`bars.*`): daily prices after the market closes, plus a backfill of the history.
- **Index** (`index.*`): the Nifty 500 closes, used as the yardstick in backtests.
- **Corporate actions** (`actions.*`): splits, bonuses and dividends, so past prices are adjusted correctly.
- **Announcements and news** (`announcements.*`, `news.*`): company filings and market headlines.
- **Price checks**: compares two price sources and flags disagreements on the Dashboard and Jobs page.
- **Fundamentals** (`quarters.*`, `fundamentals.*`): quarterly results and ratios, merged into one view per stock.
- **Screens**: runs your saved screens daily and records which stocks match.
- **Alerts**: checks your positions, stops, targets and announcements, in-app only.
- **Housekeeping**: deletes old run history and seen alerts after 90 days.
- **Ask Claude / Backtest**: run only when you click.

## Backup and restore

- **Backup:** Settings → *Back up now* (or `POST /api/backup`). It writes a safe copy of the database to `data/backups/stock-YYYYMMDD-HHMM.db`, even while the app is running.
- **Restore:** stop the app (`./start.sh --stop`), copy the backup over `data/stock.db`, delete `data/stock.db-wal` and `data/stock.db-shm` if they exist, then start the app again.
- Your API keys or logins for sources live in `data/secrets.json`. Back that up separately; the database backup does not include it. The whole `data/` folder is ignored by git.

## AI features (your Claude Pro plan)

The AI helpers (describe a screen in words, challenge a checklist, brief a stock, review custom indicators) use the **`claude` command-line tool on this laptop**, signed in to your Pro plan. There is no API key. They run **only when you click**, never in the background, and every one has a "copy the prompt" fallback you can paste into claude.ai yourself. Code the AI writes for a custom indicator never runs until you approve it. Heavy use counts against your plan's usage limits.

## Backtests: how to read them

A backtest replays a rule on past prices with realistic Indian trading costs and no look-ahead. The last 30% of history is kept as a hidden **out-of-sample** test; trust results that also hold up there. Every result carries warnings (for example: tested on today's Nifty 500 list, so companies that dropped out are missing).

## Development

Checks: `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app tests`, and `cd frontend && npm run build && npm test`.

The plan lives in `docs/SPEC.md` and `tickets/` (see [tickets/README.md](tickets/README.md)). To add a data source, follow `docs/ADDING_A_SOURCE.md`.
