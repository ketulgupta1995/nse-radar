"""The only way any code touches the network (SPEC §3.1)."""

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, NamedTuple
from urllib.parse import urlparse

import httpx

from app import config

log = logging.getLogger(__name__)


class HttpPolicy(NamedTuple):
    min_interval_s: float  # minimum gap between requests to this host
    timeout_s: float
    retries: int  # on 429/5xx/timeouts: exponential backoff 2s, 4s, 8s...


POLICIES: dict[str, HttpPolicy] = {"*": HttpPolicy(1.0, 20, 2)}

_NO_RETRY = {401, 403, 404}

Transport = Callable[[str, dict | None, dict], tuple[int, bytes]]
_transport: Transport | None = None

_guard = threading.Lock()
_host_locks: dict[str, threading.Lock] = {}
_last_request: dict[str, float] = {}


class FetchError(Exception):
    def __init__(self, message: str, *, status: int | None = None, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url


def add_policy(host: str, policy: HttpPolicy) -> None:
    POLICIES[host] = policy


def set_transport(fn: Transport | None) -> None:
    global _transport
    _transport = fn


def _policy(host: str) -> HttpPolicy:
    return POLICIES.get(host, POLICIES["*"])


def _default_transport(timeout: float) -> Transport:
    def send(url: str, params: dict | None, headers: dict) -> tuple[int, bytes]:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            r = client.get(url, params=params, headers=headers)
            return r.status_code, r.content

    return send


def _wait_turn(host: str, policy: HttpPolicy) -> None:
    """Called with the host lock held: sleep so requests are min_interval_s apart."""
    last = _last_request.get(host)
    if last is not None:
        gap = policy.min_interval_s - (time.monotonic() - last)
        if gap > 0:
            time.sleep(gap)


def _attempt(
    url: str, params: dict | None, headers: dict, host: str, policy: HttpPolicy
) -> tuple[int, bytes]:
    send = _transport or _default_transport(policy.timeout_s)
    with _guard:
        lock = _host_locks.setdefault(host, threading.Lock())
    with lock:
        _wait_turn(host, policy)
        started = time.monotonic()
        try:
            return send(url, params, headers)
        finally:
            _last_request[host] = time.monotonic()
            log.debug("GET %s %s (%.0f ms)", host, urlparse(url).path, (time.monotonic() - started) * 1000)


def get(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    accept: str = "*/*",
) -> bytes:
    host = urlparse(url).hostname or ""
    policy = _policy(host)
    hdrs = {"User-Agent": config.USER_AGENT, "Accept": accept, **(headers or {})}
    path = urlparse(url).path
    last_err: FetchError | None = None
    for attempt in range(policy.retries + 1):
        if attempt:
            time.sleep(2 ** attempt)  # 2s, 4s, 8s...
        try:
            status, body = _attempt(url, params, hdrs, host, policy)
        except (httpx.TimeoutException, TimeoutError) as e:
            last_err = FetchError(f"timeout fetching {url}", url=url)
            log.debug("GET %s %s -> timeout (%s)", host, path, e)
            continue
        except httpx.HTTPError as e:
            raise FetchError(f"network error fetching {url}: {e}", url=url) from e
        log.debug("GET %s %s -> %s (%d bytes)", host, path, status, len(body))
        if status < 400:
            return body
        last_err = FetchError(f"HTTP {status} for {url}", status=status, url=url)
        if status in _NO_RETRY or not (status == 429 or status >= 500):
            raise last_err
    assert last_err is not None
    raise last_err


def get_json(url: str, *, params: dict | None = None, headers: dict | None = None) -> Any:
    body = get(url, params=params, headers=headers, accept="application/json")
    try:
        return json.loads(body)
    except ValueError as e:
        raise FetchError(f"invalid JSON from {url}", url=url) from e
