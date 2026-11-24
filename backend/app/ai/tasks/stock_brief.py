"""One-page plain-language brief on a stock (SPEC §11)."""

from app.ai.base import AITask, register_task
from app.ai.tasks._context import AUDIENCE, stock_context


def build_prompt(payload: dict) -> str:
    return (
        "You are helping an Indian-market retail investor understand a stock.\n"
        + AUDIENCE
        + "\n\nTask: write a brief of at most 250 words with these parts: what the company does (only if the "
        "data says so), how the price has behaved, what the numbers say about the business, what the recent "
        "announcements and news mean, the main risks, and 3 things to verify before acting. "
        "Mention how old the data is.\n\n"
        + stock_context(payload["symbol"])
    )


register_task(AITask(kind="stock_brief", label="Stock brief", build_prompt=build_prompt, needs_symbol=True))
