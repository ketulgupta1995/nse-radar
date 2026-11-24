# N015: Stock page on a phone
Cloud · phone layouts · Depends on: N013 · Model: sonnet

## Goal
The stock page (SPEC §14 item 3) works on a phone. The chart is usable by touch, and the panels are reachable without endless scrolling.

## Read first
SPEC §17.9 ("Charts"), §14 item 3, `frontend/src/pages/Stock.tsx`, `frontend/src/components/chart/PriceChart.tsx`, `frontend/src/components/chart/IndicatorPicker.tsx`, `frontend/src/components/stock/*`, `frontend/src/components/ai/AskClaude.tsx`, `frontend/src/components/checklist/*`, `frontend/src/__tests__/StockPage.test.tsx`, `frontend/src/__tests__/Chart.test.tsx`

## Files
The files above (no new pages), plus their tests.

## Requirements
- Phone header: symbol, price, day change, watchlist star and source tag in at most 2 lines. Actions (Start checklist, Ask Claude, add position) go in a row of icon buttons or a "⋯" menu.
- The chart takes the full width, with height `max(220px, 60vw)`, and a `ResizeObserver` keeps it sized on rotation. Keep lightweight-charts' touch scroll/zoom enabled. The indicator picker opens as a sheet. The RSI pane stays but is shorter.
- Below the chart, `Tabs`: Overview (fundamentals panel + shareholding), Quarterly, News (announcements + news), AI. The quarterly table scrolls horizontally inside its own container, with the first column sticky.
- Ask Claude on the phone: when `/api/ai/status` says the CLI isn't available (it isn't on Android), show "Copy prompt" as the main button with a one-line explanation. Nothing else changes.
- Laptop unchanged.

## Tests
Phone: tabs render and switch, the chart container gets a phone height, and AskClaude with AI unavailable shows Copy prompt first. Existing laptop tests pass. `npm run build && npm test` pass.


## Notes for the planner
