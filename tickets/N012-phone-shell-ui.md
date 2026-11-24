# N012: Phone shell: top bar, bottom tabs, More sheet, full-screen search
Cloud · phone layouts · Depends on: none (UI tickets can be checked in a laptop browser at phone width) · Model: sonnet

## Goal
Below 768 px the app gets a phone shell (SPEC §17.9 "Shell"). At 768 px and wider the laptop layout must look and behave exactly as today.

## Read first
SPEC §17.9, §14 "Shared", AGENTS.md "UI conventions", `frontend/src/components/Layout.tsx`, `frontend/src/routes.tsx`, `frontend/src/components/CommandPalette.tsx`, `frontend/src/components/StatusIndicator.tsx`, `frontend/src/components/AlertBadge.tsx`, `frontend/src/components/ui/toaster.tsx`, `frontend/src/__tests__/Layout.test.tsx`

## Files
- `frontend/src/lib/useIsPhone.ts` (new): `useIsPhone(): boolean`, live via `matchMedia("(max-width: 767px)")`, false when `matchMedia` is missing
- `frontend/src/__tests__/phone.ts` (new): `setPhone(on: boolean)` stubs `window.matchMedia` and fires change events. Later tickets reuse it.
- `frontend/src/routes.tsx`: `phoneTab?: number` on `AppRoute`. Dashboard 1, Screener 2, Watchlist 3, Portfolio 4.
- `frontend/src/components/Layout.tsx`: branches on `useIsPhone()`. Phone: sticky top bar (page title from the matching route, search button, compact `StatusIndicator` as a dot plus short text, `AlertBadge`), content with bottom padding, and a fixed bottom tab bar (4 phone tabs + More), all honouring `env(safe-area-inset-*)`.
- `frontend/src/components/MoreSheet.tsx` (new): bottom sheet (use the existing `dialog.tsx`), with nav routes not in the tab bar grouped by `NAV_GROUPS` and the theme toggle. Closes on navigate.
- `frontend/src/components/CommandPalette.tsx`: full-screen on a phone, input autofocused
- `frontend/src/components/StatusIndicator.tsx`: `compact` prop
- `frontend/src/components/ui/toaster.tsx`: on a phone, toasts sit above the tab bar
- `frontend/index.html`: `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">` (check what's there)
- `AGENTS.md`: replace "Laptop only (1280px and wider): no phone or tablet layouts." with "Laptop (768 px+) layout unchanged; phones (<768 px) get phone layouts per SPEC §17.9. Use `useIsPhone()` and test both with `setPhone()`."
- Tests: `frontend/src/__tests__/Layout.test.tsx` (extend), `frontend/src/__tests__/useIsPhone.test.ts` (new)

## Requirements
- No new dependencies. Tailwind classes. Touch targets at least 40 px. Icons from the routes' own `icon`.
- The active tab is highlighted (the More tab is active when the current route isn't one of the 4).

## Tests
- Phone: no sidebar, 5 tab buttons, More opens a sheet listing Alerts, Backtests, Jobs, Sources, Settings, Journal, Track record. Tapping one navigates and closes the sheet. The search button opens the palette.
- Laptop: sidebar present, no tab bar (the existing Layout tests still pass unchanged).
- `useIsPhone` flips when the stubbed media query changes.
- `npm run build && npm test` pass.


## Notes for the planner
- `AlertBadge` isn't in this ticket's file list, so on a phone its "No new alerts" text is hidden with `[&_.badge-text]:hidden` on a wrapper in `Layout.tsx`. A `compact` prop on `AlertBadge` would be cleaner.
- `useTheme()` keeps its own state each time it's called, so `Layout` passes `theme`/`onToggleTheme` to `MoreSheet` as props.
