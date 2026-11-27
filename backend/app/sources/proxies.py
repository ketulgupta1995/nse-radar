"""Free proxies from Dahono-com/free-proxy-list, for sources that refuse cloud IPs.

The list is re-published every 3 hours and sorted fastest first. We fetch it fresh (cached for an hour
in this process), then probe the top few hundred in parallel and keep the ones that work: only about 1 in
100 does. Free proxies can see the request (not the HTTPS content: TLS still verifies the site).
"""

import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.sources import http
from app.sources.http import FetchError, HttpPolicy

log = logging.getLogger(__name__)

LIST_URLS = (
    "https://raw.githubusercontent.com/Dahono-com/free-proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/Dahono-com/free-proxy-list/main/proxies/https.txt",
)
POOL = 400  # probe this many from the top of the list
WANT = 40  # stop probing once this many proxies work
WORKERS = 50
PROBE_URL = "https://www.google.com/generate_204"  # tiny HTTPS page: also proves the TLS chain is genuine
PROBE_POLICY = HttpPolicy(0.0, 8, 0)  # a dead proxy costs at most 8 s, never retried
CACHE_S = 3600
_IP_PORT = re.compile(r"^(\d{1,3}\.){3}\d{1,3}:\d{2,5}$")

_cache: tuple[float, list[str]] | None = None


def parse_list(text: str) -> list[str]:
    """One `ip:port` per line; anything else is ignored."""
    return [line.strip() for line in text.splitlines() if _IP_PORT.match(line.strip())]


def _fetch_lists() -> list[str]:
    merged: dict[str, None] = {}  # dict keeps order and drops duplicates
    for url in LIST_URLS:
        try:
            body = http.get(url, accept="text/plain").decode("utf-8", "replace")
        except FetchError as e:
            log.info("proxy list unavailable: %s", url)
            log.debug("proxy list error: %s", e)
            continue
        merged.update(dict.fromkeys(parse_list(body)))
    return list(merged)


def _alive(proxy: str) -> bool:
    """True if the proxy completes an HTTPS request with a valid certificate. Free proxies mostly don't:
    many are dead and some re-sign TLS, which httpx rejects (verification stays on)."""
    try:
        http.get(PROBE_URL, proxy=proxy, policy=PROBE_POLICY)
    except FetchError:
        return False
    return True


def candidates(want: int = WANT) -> list[str]:
    """Working proxy URLs (`http://ip:port`), found by probing the fastest few hundred in parallel.
    Empty if the list could not be fetched or nothing on it works."""
    global _cache
    now = time.monotonic()
    if _cache is None or now - _cache[0] > CACHE_S:
        _cache = (now, _fetch_lists())
    pool = _cache[1][:POOL]
    random.shuffle(pool)
    found: list[str] = []
    with ThreadPoolExecutor(WORKERS) as ex:
        futures = {ex.submit(_alive, f"http://{p}"): p for p in pool}
        for fut in as_completed(futures):
            if fut.result():
                found.append(f"http://{futures[fut]}")
                if len(found) >= want:
                    for f in futures:
                        f.cancel()  # not yet started: skip
                    break
    log.info("proxies: %d working of %d probed", len(found), len(pool))
    return found


class Rotation:
    """Sticky choice: keep using one proxy until it fails, then move to the next."""

    def __init__(self, options: list[str | None], limit: int) -> None:
        self._options = options
        self._limit = min(limit, len(options))
        self._i = 0

    @property
    def current(self) -> str | None:
        return self._options[self._i]

    @property
    def current_is_proxy(self) -> bool:
        """True while the rotation holds proxies (not the direct fallback). Valid after advance() is False."""
        return self._options[0] is not None

    def advance(self) -> bool:
        """Move to the next proxy. False when none are left."""
        self._i += 1
        return self._i < self._limit
