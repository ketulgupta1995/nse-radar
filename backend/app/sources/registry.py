"""Registry of data sources (SPEC §3.2). Core code asks this, never names a source."""

import re
import sqlite3
import time

from app import config, db
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


def _enabled_map(names: list[str], c: sqlite3.Connection) -> dict[str, bool]:
    """`is_enabled` for many sources in one query (plus one insert for sources without a row yet),
    so a request on Vercel doesn't spend two statements per source (SPEC §17.5)."""
    if not names:
        return {}
    marks = ",".join("?" * len(names))
    q = f"SELECT source, enabled FROM source_state WHERE source IN ({marks})"
    found = {r[0]: bool(r[1]) for r in c.execute(q, names)}
    missing = [n for n in names if n not in found]
    if missing:
        c.executemany(
            "INSERT OR IGNORE INTO source_state(source, enabled) VALUES (?, ?)",
            [(n, 1 if _sources[n].default_enabled else 0) for n in missing],
        )
        found |= {r[0]: bool(r[1]) for r in c.execute(q, names)}
    return found


# Vercel only (SPEC §17.2): {capability: (monotonic time, source names)}. A request asks for the same
# order several times; each ask is two Turso round trips. Cleared by `frames.invalidate()` (which every
# priority or on/off change calls) and after `frames.VERCEL_CACHE_TTL_S`.
ordered_cache: dict[str, tuple[float, list[str]]] = {}


def ordered(capability: str, conn: sqlite3.Connection | None = None) -> list[BaseSource]:
    cache = config.RUNTIME == "vercel"
    if cache and capability in ordered_cache:
        from app.analytics.frames import VERCEL_CACHE_TTL_S  # lazy: frames imports this module

        at, names = ordered_cache[capability]
        if time.monotonic() - at <= VERCEL_CACHE_TTL_S:
            return [_sources[n] for n in names if n in _sources]

    def go(c: sqlite3.Connection) -> list[BaseSource]:
        try:
            priority = db.get_setting("source_priority", c).get(capability, [])
        except KeyError:
            priority = []
        on = _enabled_map([n for n in _sources if spec(n, capability) is not None], c)
        has = {n for n, enabled in on.items() if enabled}
        first = [n for n in dict.fromkeys(priority) if n in has]
        rest = sorted(has - set(first))
        return [_sources[n] for n in [*first, *rest]]

    out = _run(conn, go)
    if cache:
        ordered_cache[capability] = (time.monotonic(), [s.name for s in out])
    return out


def clear() -> None:
    """Tests only."""
    _sources.clear()
    ordered_cache.clear()
