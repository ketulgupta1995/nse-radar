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
