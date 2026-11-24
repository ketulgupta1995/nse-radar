# N017: Portfolio, Journal and Track record on a phone
Cloud · phone layouts · Depends on: N013 · Model: sonnet

## Goal
The money and validate pages work on a phone, including adding and closing a position and writing a journal entry.

## Read first
SPEC §17.9, §13, §16.6, `frontend/src/pages/Portfolio.tsx`, `frontend/src/pages/Journal.tsx`, `frontend/src/pages/TrackRecord.tsx`, `frontend/src/components/positions/*`, `frontend/src/components/track/*`, `frontend/src/__tests__/MoneyPages.test.tsx`, `frontend/src/__tests__/Journal.test.tsx`, `frontend/src/pages/TrackRecord.test.tsx`

## Files
The files above, plus their tests.

## Requirements
- Portfolio: a summary card on top (value, today's change, total P&L, using `pos`/`neg` only for P&L), then positions as cards (symbol, qty × avg, current, P&L, the trailing-exit level if any). Add/close position forms open as full-screen sheets, with numeric `inputMode`.
- Journal: entries as cards, newest first. The new-entry form is a full-screen sheet.
- Track record: summary metrics in a 2-column grid of cards, each keeping its `<Explain>`. The "Every logged idea" table uses the card mode with the outcome visible, and the "seen again" timeline inside More/expanded.
- Laptop unchanged.

## Tests
Phone: the portfolio summary shows above the cards, the add-position sheet posts the right body, journal entries render as cards, and track-record metrics render. Existing tests pass. `npm run build && npm test` pass.


## Notes for the planner
- `Position` has no previous-close or trailing-exit field, so the phone summary omits "today's change" and the cards omit the trailing-exit level. Needs a backend field (outside this ticket).
- The Journal has no "new entry" form (it lists closed trades); the full-screen sheets are the add-position (`EntryChecklist`) and close-position (`ExitChecklist`) forms, via `checklist/Modal.tsx`, which now also makes `CustomIndicatorReview` a full-screen sheet on a phone.
