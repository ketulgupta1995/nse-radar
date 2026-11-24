"""A pass-through task: the payload's prompt is sent as is. Used for testing."""

from app.ai.base import AITask, register_task

register_task(AITask(kind="raw", label="Raw prompt", build_prompt=lambda p: str(p.get("prompt", ""))))
