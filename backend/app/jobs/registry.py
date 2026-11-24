from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.jobs.context import JobContext


@dataclass(frozen=True)
class JobDef:
    name: str
    title: str
    description: str
    fn: "Callable[[JobContext], str | None]"
    default_schedule: dict
    retryable: bool = True
    group: str = "app"
    stage: int = 5
    lane: Literal["background", "interactive"] = "background"
    followups: tuple[str, ...] = ()
    refresh: bool = False  # included in "Refresh now" (§6.4)


_JOBS: dict[str, JobDef] = {}


def register(job: JobDef) -> JobDef:
    if job.name in _JOBS:
        raise ValueError(f"duplicate job name: {job.name}")
    _JOBS[job.name] = job
    return job


def get(name: str) -> JobDef:
    return _JOBS[name]


def all_jobs() -> list[JobDef]:
    return list(_JOBS.values())
