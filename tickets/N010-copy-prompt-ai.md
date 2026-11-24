# N010: AI by copy-prompt in the cloud
Cloud · Depends on: N007 · Model: sonnet

## Goal
Every AI button works in the cloud. It shows the prompt to copy into the Claude app and accepts the pasted answer, which is then handled exactly like a provider's answer (SPEC §17.7).

## Read first
SPEC §11, §17.7, `backend/app/ai/base.py`, `backend/app/ai/providers/claude_cli.py`, `backend/app/api/ai.py`, `backend/app/jobs/defs/ai_request.py`, `frontend/src/components/ai/*`

## Files
- `backend/app/ai/providers/copy_prompt.py` (new, auto-discovered): `available()` as §17.7. `run()` raises a clear error, because it's never run by a job.
- `backend/app/api/ai.py`: `POST /api/ai/requests/{id}/answer {"text": str}`. It stores the answer, parses it through the task like a provider result, and sets the request `done`. When the provider is `copy_prompt`, `POST /api/ai/requests` creates the request in state `awaiting_answer` without enqueueing a job.
- Frontend AI components: when the provider is `copy_prompt`, show a dialog with the prompt, a Copy button, "Open Claude" (`https://claude.ai/new`, new tab) and a paste box + Save. The result view is unchanged.
- Tests: the backend answer endpoint for a JSON task and a plain task, and no job enqueued; the frontend dialog copy/paste/save flow.

## Notes for the planner
- `schema.sql` CHECKs `ai_requests.status IN ('queued','running','done','failed','cancelled')`, so `awaiting_answer` can't be stored without a schema change (and a Turso migration). The row is stored as `queued` with `run_id` NULL and a manual provider; the API reports it as `awaiting_answer` (`_awaiting` in `api/ai.py`). Add the status to the schema later if you prefer.
- The API doesn't name `copy_prompt`: the provider has a class attribute `manual_answer = True` and the API checks it with `getattr`. Consider making `manual_answer: bool = False` part of `AIProvider` in `ai/base.py` (§11).
- The ticket says `run()`; the provider interface method is `ask()`, so `CopyPrompt.ask()` raises `AIError`.
- With copy_prompt, `POST /api/ai/requests` returns `{id, run_id: null, status: "awaiting_answer", prompt}`. The two extra fields save a second round trip and make sure the dialog shows the stored prompt. `AiCreated` is in `types.ts`.
- `rule_from_text` / `indicator_code` re-ask through the provider when the first answer is invalid. With copy_prompt that re-ask raises, so the result is `{"ok": false, "error": "... retry failed: ..."}`. The owner can paste a corrected answer: `/answer` may be called again on the same request, which overwrites the old answer.
- `DescribeScreen.tsx` (Make screen / Review code) is in `components/screens/`, not `components/ai/`, but it is an AI button. It now uses the same `PasteAnswerDialog`.
- In copy_prompt mode the "Claude isn't set up yet. Install Claude Code…" hint in `AskClaude` never shows, because `available()` is always true. Settings may want an explanation of the copy_prompt option.
