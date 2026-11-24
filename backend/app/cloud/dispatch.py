"""Start the cloud worker from Vercel and keep its schedule alive (SPEC §17.4).

This talks to GitHub's API, not a data source, so it uses httpx directly with its own
injectable transport. The token is never logged.
"""

import logging
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from app import config, db, timeutil

log = logging.getLogger(__name__)

API = "https://api.github.com"
DEBOUNCE = timedelta(seconds=60)
KEEPALIVE_EVERY = timedelta(days=7)
TIMEOUT_S = 10.0

# (method, url, headers, json body or None) -> HTTP status
Transport = Callable[[str, str, dict, Any], int]
_transport: Transport | None = None


def set_transport(fn: Transport | None) -> None:
    global _transport
    _transport = fn


def _default_send(method: str, url: str, headers: dict, body: Any) -> int:
    with httpx.Client(timeout=TIMEOUT_S) as client:
        return client.request(method, url, headers=headers, json=body).status_code


def _token() -> str:
    return os.environ.get("GITHUB_DISPATCH_TOKEN", "")


def configured() -> bool:
    return bool(config.GITHUB_REPO and _token())


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": config.USER_AGENT,
    }


def _send(method: str, path: str, body: Any = None) -> bool:
    send = _transport or _default_send
    try:
        status = send(method, f"{API}/repos/{config.GITHUB_REPO}{path}", _headers(), body)
    except Exception as e:  # network trouble: record and move on, never raise into a request
        log.warning("GitHub %s %s failed: %s", method, path, type(e).__name__)
        return False
    if not 200 <= status < 300:
        log.warning("GitHub %s %s returned HTTP %s", method, path, status)
        return False
    return True


def _since(key: str) -> timedelta | None:
    try:
        value = db.get_setting(key)
    except KeyError:
        return None
    if not value:
        return None
    return timeutil.now() - datetime.fromisoformat(value)


def last_dispatch_at() -> str | None:
    try:
        return db.get_setting("last_dispatch_at")
    except KeyError:
        return None


def kick(reason: str) -> bool:
    """Ask GitHub to start drain.yml. Debounced: one dispatch per 60 s is enough."""
    if not configured():
        log.info("dispatch not configured; job waits for the next schedule")
        return False
    since = _since("last_dispatch_at")
    if since is not None and since < DEBOUNCE:
        return True  # a drain was asked for moments ago; it picks up every queued job
    body = {"ref": "main", "inputs": {"reason": reason}}
    if not _send("POST", "/actions/workflows/drain.yml/dispatches", body):
        return False
    db.set_setting("last_dispatch_at", timeutil.now_iso())
    return True


def keepalive() -> bool:
    """Re-enable daily.yml at most once every 7 days, so GitHub never auto-disables it."""
    if not configured():
        return False
    since = _since("last_keepalive_at")
    if since is not None and since < KEEPALIVE_EVERY:
        return False
    db.set_setting("last_keepalive_at", timeutil.now_iso())  # recorded even on failure: no hammering
    return _send("PUT", "/actions/workflows/daily.yml/enable")
