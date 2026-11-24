# N016: Screener and rule builder on a phone
Cloud · phone layouts · Depends on: N013 · Model: sonnet

## Goal
Running saved screens and building or editing a rule both work on a phone.

## Read first
SPEC §17.9, §14 item 2, `frontend/src/pages/Screener.tsx`, `frontend/src/components/rules/*`, `frontend/src/components/screens/*`, `frontend/src/__tests__/Screener.test.tsx`, `frontend/src/__tests__/RuleBuilder.test.tsx`

## Files
The files above, plus their tests.

## Requirements
- Phone page: a screen picker (`Select`) at the top instead of the side list, then Run, then results as cards (symbol title, name subtitle, score and the screen's key numbers visible).
- Edit opens the rule builder as a full-screen sheet. Each condition is a stacked card: operand, op word, operand, each full width, with a delete button. "Add condition" and "Add group" are full-width buttons. Groups are shown by an indented left border, not nested boxes wider than the screen. Param inputs use `inputMode="decimal"`.
- Preview / Save / Backtest this stay reachable in a sticky footer of the sheet. "Describe a screen in words" works (copy-prompt fallback on the phone).
- Laptop unchanged.

## Tests
Phone: pick a screen and run it (results as cards), open the editor, add a condition, save (the mocked API receives the rule). Existing tests pass. `npm run build && npm test` pass.


## Notes for the planner
