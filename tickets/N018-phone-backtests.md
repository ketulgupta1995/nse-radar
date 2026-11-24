# N018: Backtests on a phone
Cloud · phone layouts · Depends on: N013, N005 · Model: sonnet

## Goal
Listing, reading and starting backtests all work on a phone, and the page says honestly that backtests run in the cloud worker and take a minute or two to start.

## Read first
SPEC §17.4 (`/api/cloud/status`), §17.9, §12.4, §12.6, `frontend/src/pages/Backtests.tsx`, `frontend/src/components/backtests/*`, `frontend/src/lib/backtests.ts`, `frontend/src/__tests__/Backtests.test.tsx`, `frontend/src/__tests__/backtestsBatch.test.ts`

## Files
The files above, `frontend/src/lib/cloud.ts` (new: `useCloud()` fetching `/api/cloud/status` once per page view; defaults to `{runtime: "local"}` on error), plus their tests.

## Requirements
- List: cards with the name as title, kind badge (explore/final), then CAGR, max drawdown and trades, and status while running. A queued run shows "Waiting for the cloud worker (usually 1–2 min)".
- Detail: the equity chart is full width with the phone height (§17.9). Metric cards go in a 2-column grid. The warnings box always shows. Trades use the card mode. The locked test-period card and "Run final test" (inline confirm) still work.
- Form (`/backtests/new`): sections stack and the exit editor rows stack. "Run several at once" works. When `useCloud().runtime === "vercel"`, show a muted line under the run button: "Backtests run in the cloud worker. It starts in a minute or two, and you can leave this page."
- Laptop width unchanged. The new line never shows in local mode.

## Tests
Phone: list cards, the detail metric grid, and the form shows the cloud line when the mocked `/api/cloud/status` says `runtime: "vercel"` and hides it for `local`. Existing tests pass. `npm run build && npm test` pass.

## Notes for the planner
