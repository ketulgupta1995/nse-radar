"""Help the owner draft an investment thesis (SPEC §11)."""

from app.ai.base import AITask, register_task
from app.ai.tasks._context import AUDIENCE, stock_context


def build_prompt(payload: dict) -> str:
    return (
        "You are helping an Indian-market retail investor write down their own reasoning for a stock.\n"
        + AUDIENCE
        + "\n\nTask: draft a thesis of at most 300 words with these headings: 'What could go right' (facts "
        "from the data that support holding for 1-4 months), 'What could go wrong', 'What would prove this "
        "wrong' (specific, checkable signals), and 'Upcoming events to watch' (only if the data mentions "
        "any). Do not recommend buying or selling. Mention how old the data is.\n\n"
        + stock_context(payload["symbol"])
    )


register_task(AITask(kind="thesis_draft", label="Thesis draft", build_prompt=build_prompt, needs_symbol=True))
