# Ticket board (nse-radar)

nse-radar is the cloud copy of stock-tools (SPEC §17). The plan is written by Opus. **Sonnet implements one ticket per fresh session, one at a time, in number order** (number order satisfies the dependencies). Tickets marked **Opus + owner** are done interactively, not headless.

## How to run a ticket

```bash
cd ~/ketul/claude_projects/nse-radar
scripts/run-ticket.sh N002            # headless Sonnet; log in logs/
# or interactively: claude, then "Implement tickets/N002-....md. Follow AGENTS.md."
```
If a ticket goes wrong, `git revert HEAD` undoes its single commit, and an Opus session reviews the "Notes for the planner".

Status values: `todo` · `done` · `blocked` (add a reason).

| Ticket | Title | Depends on | Who | Status |
|---|---|---|---|---|
| N001 | Cloud spike: Turso driver and data sources from GitHub Actions | — | Opus + owner | done |
| N002 | Runtime modes and the Turso driver behind `db.connect()` | N001 | sonnet | done |
| N003 | Seed script and the owner's setup guide | N002 | sonnet | done |
| N004 | Thread-free job drain | N002 | sonnet | done |
| N005 | Kick the cloud worker, keep-alive, `/api/cloud/status` | N004 | sonnet | done |
| N006 | GitHub Actions workflows: ci, drain, daily | N005 | sonnet | done |
| N007 | Vercel entry point and config | N004 | sonnet | done |
| N008 | Password gate | N007 | sonnet | done |
| N009 | Make every Vercel route light | N007 | opus | done |
| N010 | AI by copy-prompt in the cloud | N007 | sonnet | done |
| N011 | Weekly encrypted backup from the cloud worker | N006 | sonnet | done |
| N012 | Phone shell: top bar, bottom tabs, More sheet, search | — | sonnet | done |
| N013 | DataTable shows rows as cards on a phone | N012 | sonnet | done |
| N014 | Dashboard, Alerts and Watchlist on a phone | N013 | sonnet | done |
| N015 | Stock page on a phone | N013 | sonnet | done |
| N016 | Screener and rule builder on a phone | N013 | sonnet | todo |
| N017 | Portfolio, Journal and Track record on a phone | N013 | sonnet | todo |
| N018 | Backtests on a phone | N013, N005 | sonnet | todo |
| N019 | Jobs, Sources and Settings on a phone, plus "Cloud" | N013, N005, N008 | sonnet | todo |
| N020 | Go live | N001–N011, N021 | Opus + owner | todo |
| N021 | Cloud gaps found by the route audit | N009, N005 | opus | done |

N012–N017 don't depend on the cloud tickets and can run while N001 waits on the owner.
