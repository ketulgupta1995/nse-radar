"""Challenge the owner's entry-checklist answers (SPEC §11)."""

from app.ai.base import AITask, register_task
from app.ai.tasks._context import AUDIENCE, stock_context


def _answers(payload: dict) -> str:
    answers = payload.get("answers") or {}
    if not isinstance(answers, dict) or not answers:
        return "(no answers given)"
    return "\n".join(f"- {k}: {v}" for k, v in answers.items())


def build_prompt(payload: dict) -> str:
    return (
        "You are a sceptical reviewer for an Indian-market retail investor who is about to buy a stock.\n"
        + AUDIENCE
        + "\n\nTask: read the investor's checklist answers and the data below. Ask exactly 3 challenging "
        "questions that test the answers against the data, each followed by exactly 1 line explaining why "
        "you ask it. Give no other text, and do not say whether to buy or sell. "
        "If an answer contradicts the data, say so in the question.\n\n"
        "## Investor's checklist answers\n"
        + _answers(payload)
        + "\n\n"
        + stock_context(payload["symbol"])
    )


register_task(
    AITask(
        kind="checklist_challenge",
        label="Challenge my checklist",
        build_prompt=build_prompt,
        needs_symbol=True,
    )
)
