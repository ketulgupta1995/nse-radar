# N019: Jobs, Sources and Settings on a phone, plus a "Cloud" section
Cloud · phone layouts · Depends on: N013, N005, N008 · Model: sonnet

## Goal
The system pages work on a phone, and Settings shows what the cloud is doing.

## Read first
SPEC §17.4, §17.9, §14 items 7, 8 and 10, `frontend/src/pages/Jobs.tsx`, `frontend/src/pages/Sources.tsx`, `frontend/src/pages/Settings.tsx`, `frontend/src/components/jobs/*`, `frontend/src/components/sources/*`, `frontend/src/components/SettingsSection.tsx`, `frontend/src/lib/cloud.ts` (from N018), `frontend/src/__tests__/SystemPages.test.tsx`, `frontend/src/__tests__/Settings.test.tsx`, `frontend/src/__tests__/ScheduleEditor.test.tsx`, `frontend/src/__tests__/PriorityPanel.test.tsx`

## Files
The files above plus their tests. No backend changes.

## Requirements
- Jobs: job rows as cards (title, last run status chip, next run, Run now, toggle). The run drawer becomes a full-screen sheet with the log tail scrolling inside. The schedule editor stacks. Data checks as cards. In vercel mode, the page header says: "Jobs run in the cloud worker (GitHub Actions), twice a day on schedule and within a couple of minutes when you press Run now."
- Sources: one card per source stacked. Priority panel uses up/down buttons (no drag on a phone). Secrets form full width.
- Settings: sections stack, and sliders are full width with the value shown.
- **Cloud** section, shown only when `useCloud().runtime === "vercel"`: queued and running counts, the oldest queued time ("waiting 3 min"), the last dispatch time, a warning chip when `dispatch_configured` is false ("Run now can't start the worker: the dispatch token is missing; jobs wait for the next schedule"), and the Log out button from N008 moved here.
- Laptop width unchanged.

## Tests
Phone: job cards with Run now, a source card, the Cloud section only for vercel, and the missing-token warning. Existing tests pass. `npm run build && npm test` pass.

## Notes for the planner
