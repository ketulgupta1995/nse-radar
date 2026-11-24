"""AI provider and task registries (SPEC §11). Core code asks these, never a named provider."""

from collections.abc import Callable
from dataclasses import dataclass

from app import db


class AIError(Exception):
    pass


class AIProvider:
    name: str = ""
    label: str = ""

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def ask(
        self, prompt: str, *, model: str, timeout_s: int, stop_check: Callable[[], bool] | None = None
    ) -> str:
        raise NotImplementedError


_PROVIDERS: dict[str, AIProvider] = {}
_TASKS: dict[str, "AITask"] = {}


def register_provider(p: AIProvider) -> AIProvider:
    _PROVIDERS[p.name] = p
    return p


def providers() -> list[AIProvider]:
    return sorted(_PROVIDERS.values(), key=lambda p: p.name)


def provider(name: str | None = None) -> AIProvider:
    name = name or db.get_setting("ai_provider")
    if name not in _PROVIDERS:
        raise AIError(f"unknown provider: {name}")
    return _PROVIDERS[name]


@dataclass(frozen=True)
class AITask:
    kind: str
    label: str
    build_prompt: Callable[[dict], str]
    postprocess: Callable[[str, dict], dict] | None = None
    needs_symbol: bool = False


def register_task(t: AITask) -> AITask:
    if t.kind in _TASKS:
        raise ValueError(f"duplicate AI task: {t.kind}")
    _TASKS[t.kind] = t
    return t


def task(kind: str) -> AITask:
    if kind not in _TASKS:
        raise KeyError(kind)
    return _TASKS[kind]


def all_tasks() -> list[AITask]:
    return sorted(_TASKS.values(), key=lambda t: t.kind)
