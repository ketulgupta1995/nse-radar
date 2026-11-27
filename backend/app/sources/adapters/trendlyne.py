"""Buy and Sell calls from Trendlyne's public research-report list (see docs/DATA_SOURCES.md).

Only the newest pages are read, once a day: no history backfill. Report PDFs need a login and are
never fetched.
"""

from app.sources import http, registry
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

URL = "https://trendlyne.com/research-reports/all/"
PAGES = 5  # about a week of reports, so a few missed runs leave no gap


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
        found: dict[str, ResearchReport] = {}
        for page in range(1, PAGES + 1):
            try:
                body = http.get(URL, params={"page": page} if page > 1 else None, accept="text/html")
            except FetchError as e:
                raise from_fetch_error(e) from e
            try:
                rows, reports = parse_research_page(body)
            except ValueError as e:
                raise SourceError(str(e)) from e
            if not rows:
                if page == 1:
                    raise SourceError("research table was empty")
                break
            # New reports push old ones onto the next page while we read, so de-duplicate by id.
            found.update({r.report_id: r for r in reports})
        return list(found.values())


registry.register(Trendlyne())
