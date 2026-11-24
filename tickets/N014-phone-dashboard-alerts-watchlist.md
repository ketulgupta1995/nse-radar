# N014: Dashboard, Alerts and Watchlist on a phone
Cloud · phone layouts · Depends on: N013 · Model: sonnet

## Goal
The three pages the owner checks most should read well at 360–430 px wide.

## Read first
SPEC §17.9, §14 items 1 and 9 and the Watchlist (T110) paragraph, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/Alerts.tsx`, `frontend/src/pages/Watchlist.tsx`, the components they use, and their tests

## Files
`frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/Alerts.tsx`, `frontend/src/pages/Watchlist.tsx`, any component under `frontend/src/components/` that only these pages use, and their tests (`Dashboard.test.tsx`, `Alerts.test.tsx`, `Watchlist.test.tsx`: add phone cases)

## Requirements
- All sections stack in one column on a phone, in this order: "Since you were away", shortlist, unseen alerts, open positions summary, data freshness. Refresh now sits in the page header as an icon button with a label for screen readers.
- Shortlist rows: symbol as title, company as subtitle, then score bar and the top 2 reasons ("+N more" expands). Tap opens the stock page.
- Alerts: set `meta.phone` so each card shows the alert text first, then the symbol and time. Mark-seen actions are reachable without a hover.
- Watchlist: symbol/name title, price and day change visible, other columns behind More.
- No horizontal scrolling anywhere on these pages at 360 px (test: no element wider than the viewport. In jsdom, check that no fixed `min-w-[...]` above 360 px is present in phone mode, or assert the phone branch is used).
- Laptop unchanged.

## Tests
Phone cases for each page with the API mocked as the existing tests do: key sections render in the stated order, a shortlist card navigates, and alerts can be marked seen. `npm run build && npm test` pass.


## Notes for the planner
- Watchlist "day change": `WatchItem` (`GET /api/watchlist`) has no day-change field, only `last_close` and `added_close`. The phone card shows Last close and "Change since added" instead. A real day change needs `change_pct` added to the watchlist API and type (contract change, so not done here).
- Alerts didn't use `DataTable` before this ticket. On a phone it now renders through `DataTable` with `meta.phone` (message = title, symbol · time · type = subtitle, a "Mark seen" button as the one pair). The laptop list is unchanged.
- The Dashboard phone layout leaves out the laptop KPI strip. Its numbers are covered by the positions summary and the Data freshness card.
