# N013: DataTable shows rows as cards on a phone
Cloud · phone layouts · Depends on: N012 · Model: sonnet

## Goal
Most pages are lists. Give `DataTable` the phone mode from SPEC §17.9 "Lists", so every list becomes usable on a phone at once. Later tickets then only tune `meta.phone` per column.

## Read first
SPEC §17.9, `frontend/src/components/ui/data-table.tsx`, `frontend/src/__tests__/DataTable.test.tsx`, `frontend/src/lib/useIsPhone.ts`, `frontend/src/__tests__/phone.ts`

## Files
- `frontend/src/components/ui/data-table.tsx`: phone branch. Extend the TanStack `ColumnMeta` type with `phone?: "title" | "subtitle" | "hide"`.
- Tests: `frontend/src/__tests__/DataTable.test.tsx` (extend)

## Requirements
- Phone card layout:
  - **Title** row: the `"title"` column, or the first visible column. The `"subtitle"` column sits muted under it.
  - Below that, a 2-column grid of label (the column header as text) and value (the same cell renderer as the table), up to 6.
  - Further columns sit behind a "More" toggle on each card.
  - `"hide"` columns never show on a phone.
- Headers that are components, not strings, use `meta.label` (add `label?: string` to the meta type) or the column id.
- A "Sort by" `Select` above the cards lists the sortable columns plus an ascending/descending toggle, wired to the same sorting state (controlled or not, as today).
- `onRowClick` makes the whole card tappable. `renderExpanded` shows under the card. `rowClassName` applies to the card. Loading shows 3 skeleton cards; empty shows the same `EmptyState`. Density toggle hidden on a phone.
- Laptop rendering is unchanged (no DOM change at all at ≥768 px).

## Tests
- Phone: 3 rows render 3 cards. Title/subtitle/hide respected. Only 6 pairs are visible until More is tapped. Sort by select reorders. Card click calls `onRowClick`. Empty state shows.
- Laptop: the existing tests pass untouched.
- `npm run build && npm test` pass.


## Notes for the planner
