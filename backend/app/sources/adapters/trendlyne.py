"""Buy and Sell calls from Trendlyne's public research-report list (see docs/DATA_SOURCES.md).

Only the newest pages are read, once a day: no history backfill. Report PDFs need a login and are
never fetched.
"""

import logging

from app.sources import http, proxies, registry
from app.sources.base import (
    BaseSource,
    CapabilitySpec,
    FetchError,
    JobVariant,
    ResearchReport,
    SourceError,
    from_fetch_error,
)
from app.sources.http import HttpPolicy
from app.sources.parsers.trendlyne import parse_research_page

log = logging.getLogger(__name__)

URL = "https://trendlyne.com/research-reports/all/"
PAGES = 5  # about a week of reports, so a few missed runs leave no gap
MAX_PROXIES = 40  # working proxies to try before giving up on a run (about 1 in 9 gets past Trendlyne)
PROXY_POLICY = HttpPolicy(3.0, 15, 0)  # through a proxy: no retries, a slow one is skipped


class Trendlyne(BaseSource):
    name = "trendlyne"
    label = "Trendlyne research reports"
    description = "Brokers' Buy and Sell calls from Trendlyne's public research-report list."
    homepage = "https://trendlyne.com/research-reports/all/"
    http_policies = {"trendlyne.com": HttpPolicy(3.0, 30, 1)}
    capabilities = (
        CapabilitySpec(
            "research",
            "whole",
            (JobVariant(schedule={"kind": "daily", "at_time": "21:30"}, min_age_hours=6),),
        ),
    )

    def research(self) -> list[ResearchReport]:
        options: list[str | None] = [*proxies.candidates()] or [None]  # no list: try a direct request
        if options == [None]:
            log.info("no proxies available; requesting trendlyne directly")
        pool = proxies.Rotation(options, MAX_PROXIES)
        found: dict[str, ResearchReport] = {}
        for page in range(1, PAGES + 1):
            rows, reports = self._read_page(page, pool)
            if not rows:
                if page == 1:
                    raise SourceError("research table was empty")
                break
            # New reports push old ones onto the next page while we read, so de-duplicate by id.
            found.update({r.report_id: r for r in reports})
        return list(found.values())

    def _read_page(self, page: int, pool: proxies.Rotation):
        """Fetch and parse one page. A failed fetch, or a page we can't parse (often a block page
        served to that proxy), moves on to the next proxy. The last error is what the run reports."""
        params = {"page": page} if page > 1 else None
        while True:
            try:
                body = http.get(
                    URL,
                    params=params,
                    accept="text/html",
                    proxy=pool.current,
                    policy=PROXY_POLICY if pool.current else None,
                )
                return parse_research_page(body)
            except (FetchError, ValueError) as e:
                log.info("trendlyne page %d failed through a proxy: %s", page, type(e).__name__)
                if not pool.advance():
                    if pool.current_is_proxy:
                        # Free proxies are often blocked: that says nothing about our own IP, so it is a
                        # failed run to retry, not a refusal that pauses the source.
                        raise SourceError(f"no proxy got through to trendlyne: {e}") from e
                    if isinstance(e, FetchError):
                        raise from_fetch_error(e) from e
                    raise SourceError(str(e)) from e


registry.register(Trendlyne())
