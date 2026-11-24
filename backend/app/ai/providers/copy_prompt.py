"""The owner copies the prompt into the Claude app and pastes the answer back (SPEC §17.7).

No job ever runs this provider: `POST /api/ai/requests` leaves the request waiting for the
answer, and `POST /api/ai/requests/{id}/answer` stores it.
"""

from collections.abc import Callable

from app.ai.base import AIError, AIProvider, register_provider

NAME = "copy_prompt"


class CopyPrompt(AIProvider):
    name = NAME
    label = "Copy the prompt into Claude yourself (works anywhere)"
    manual_answer = True  # the API waits for a pasted answer instead of enqueueing a job

    def available(self) -> tuple[bool, str]:
        return True, "copy the prompt into Claude, then paste the answer back"

    def ask(
        self, prompt: str, *, model: str, timeout_s: int, stop_check: Callable[[], bool] | None = None
    ) -> str:
        raise AIError(
            "the copy-prompt mode can't ask Claude by itself; copy the prompt into Claude "
            "and paste the answer back"
        )


register_provider(CopyPrompt())
