# Rules for implementation sessions

This repo is **nse-radar**, the cloud copy of stock-tools (Vercel + Turso + GitHub Actions). SPEC §17 overrides older laptop-only statements.

You are implementing **one ticket** from `tickets/`. The plan was written in advance and is final.

## Before you start
1. Read the ticket file in full.
2. Read the `SPEC §` sections it names in `docs/SPEC.md`. Read nothing else from the spec unless you need it.
3. Check `tickets/README.md` to confirm every ticket in "Depends on" is `done`. If one isn't, **stop and tell the user**.
4. Look at the existing code you will plug into: the modules the ticket names. Don't explore the whole repo.

## While working
- **Stay inside the ticket.** Create or change only the files it lists, plus their tests. If something outside them seems wrong or missing, don't fix it. Write it under "Notes for the planner" at the bottom of the ticket file and carry on.
- **Contracts are fixed.** Function signatures, table columns, API paths and JSON shapes in the SPEC are exact. Don't rename, reorder or "improve" them. If a contract is impossible to meet, stop and tell the user why.
- **Plug-ins, not edits (SPEC §2.4).** New jobs, API modules, data sources, alert scanners, AI providers and AI tasks are new files that the app discovers automatically. Don't register them by editing `main.py` or an `__init__.py`. Core code must never name a specific data source or AI provider; ask the registry instead (`sources.registry.ordered(...)`, `ai.base.provider()`).
- **Never change `schema.sql`** unless the ticket says so.
- **No new dependencies** beyond SPEC §2.2 unless the ticket allows them.
- **Tests never use the network.** Use `backend/tests/fixtures/` or `http.set_transport` fakes (§3.1). Freeze time by monkeypatching `app.timeutil.now`.
- **Network etiquette (§3.1):** honest User-Agent, no browser impersonation, no bot-protection workarounds, and respect the per-host rate limits. If a site refuses, record the failure; don't try to get around it.
- Python: type hints, small functions, no classes where a function will do, `logging` rather than `print`. Wrap SQL in `with db.tx() as conn:`.
- TypeScript: strict mode, function components, no `any`, API calls only through `src/api/client.ts`, types in `src/api/types.ts`.
- **Cloud rules (§17):** the repo, Actions logs and artifacts are **public**, so never print or log private data (positions, journal, watchlist notes, AI requests, settings values) or secrets, and never commit `.env*` or `data/`. Vercel routes stay light (§17.5): no broad `bars` scans or many-symbol `load_frame` on a request path; heavy work is a job. Tests never touch Turso or GitHub; they run on local SQLite.
- **Plain language in the UI.** The owner isn't a maths person. Every number shown needs a label, and every indicator or metric gets an `<Explain>` tooltip.

## Finishing
1. Run the checks:
   - `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app tests`
   - for frontend tickets: `cd frontend && npm run build && npm test`
   - everything must pass, including the older tests
2. In `tickets/README.md`, set this ticket's status to `done`.
3. Commit with the message `N0NN: <ticket title>`, staging only this ticket's files. Don't push.
4. Reply with a summary of 5 lines or fewer: what was built, how to see it (URL or command), and any notes for the planner.

## If you get stuck
After two failed attempts at the same problem, stop. Write what you tried under "Notes for the planner" in the ticket and tell the user. Don't hack around it.

## UI conventions (frontend)
- **Stack:** Tailwind 4 + shadcn-style components in `frontend/src/components/ui/` (Button, Card, Badge / StatusChip, Tabs, Tooltip, Skeleton, Input, Select, Progress, EmptyState, DataTable, Toaster). Icons from `lucide-react`. Laptop only (1280px and wider): no phone or tablet layouts.
- **Add a page:** one entry in `routes.tsx` with `group` (Research / Money / Validate / System) and a lucide `icon`. It appears in the sidebar and the Ctrl+K palette automatically.
- **Lists are `DataTable`** (sorting, density toggle, sticky header, empty state, skeleton rows). Right-align numbers with `meta: { right: true }`. Put sections in `Card`. Show waiting with `Skeleton`, empty lists with `EmptyState`, and success with `toast.success(...)` from `components/ui/toaster`.
- **Colours are tokens** in `src/index.css` (`bg-card`, `text-muted-foreground`, `border-border`, `text-accent`, `success` / `danger` / `warning` / `info`). `pos` / `neg` (green / red) are only for profit and loss or price direction, never for status or decoration. The chart reads the same tokens through `lib/chartTheme.ts`.
- **Numbers:** always through `<Num>`; every metric still needs an `<Explain>`.
- Prefer Tailwind classes in new code. `index.css` has a small `legacy` layer with older shared rules (`.card`, `.chip`, `table`, `.log`, ...). It sits below utilities, so a utility class always wins. Don't add to it.
- Tests that need cmdk, Radix tooltips or tables stub `ResizeObserver` (jsdom lacks it). Charts are tested with `lightweight-charts` mocked.
