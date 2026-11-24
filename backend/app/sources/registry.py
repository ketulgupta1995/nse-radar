"""Registry of data sources (SPEC §3.2). Core code asks this, never names a source."""

import re
import sqlite3

from app import db
from app.sources import http
from app.sources.base import BaseSource, CapabilitySpec

_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_sources: dict[str, BaseSource] = {}


def register(src: BaseSource) -> BaseSource:
    if not _NAME.match(src.name):
        raise ValueError(f"invalid source name: {src.name!r}")
    if src.name in _sources:
        raise ValueError(f"source already registered: {src.name}")
    for host, policy in src.http_policies.items():
        http.add_policy(host, policy)
    _sources[src.name] = src
    return src


def get(name: str) -> BaseSource:
    return _sources[name]


def all_sources() -> list[BaseSource]:
    return sorted(_sources.values(), key=lambda s: s.name)


def spec(name: str, capability: str) -> CapabilitySpec | None:
    src = _sources.get(name)
    if src is None:
        return None
    return next((c for c in src.capabilities if c.capability == capability), None)


def _run(conn: sqlite3.Connection | None, fn):
    if conn is not None:
        return fn(conn)
    with db.tx() as c:
        return fn(c)


def is_enabled(name: str, conn: sqlite3.Connection | None = None) -> bool:
    default = 1 if _sources[name].default_enabled else 0

    def go(c: sqlite3.Connection) -> bool:
        c.execute("INSERT OR IGNORE INTO source_state(source, enabled) VALUES (?, ?)", (name, default))
        return bool(c.execute("SELECT enabled FROM source_state WHERE source=?", (name,)).fetchone()[0])

    return _run(conn, go)


def set_enabled(
    name: str, enabled: bool, reason: str | None = None, conn: sqlite3.Connection | None = None
) -> None:
    if name not in _sources:
        raise KeyError(name)

    def go(c: sqlite3.Connection) -> None:
        c.execute(
            "INSERT INTO source_state(source, enabled, paused_reason) VALUES (?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET enabled=excluded.enabled, "
            "paused_reason=excluded.paused_reason",
            (name, int(enabled), None if enabled else reason),
        )

    _run(conn, go)


def ordered(capability: str, conn: sqlite3.Connection | None = None) -> list[BaseSource]:
    def go(c: sqlite3.Connection) -> list[BaseSource]:
        try:
            priority = db.get_setting("source_priority", c).get(capability, [])
        except KeyError:
            priority = []
        has = {n for n in _sources if spec(n, capability) is not None and is_enabled(n, c)}
        first = [n for n in dict.fromkeys(priority) if n in has]
        rest = sorted(has - set(first))
        return [_sources[n] for n in [*first, *rest]]

    return _run(conn, go)


def clear() -> None:
    """Tests only."""
    _sources.clear()
