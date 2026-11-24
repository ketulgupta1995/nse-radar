"""NSE bhavcopy: official end-of-day prices for every EQ symbol."""

from datetime import date

from app.sources import http, registry
from app.sources.base import (
    Bar,
    BaseSource,
    CapabilitySpec,
    FetchError,
    JobVariant,
    from_fetch_error,
)
from app.sources.http import HttpPolicy
from app.sources.parsers.bhavcopy import bhav_url, parse_bhav


class NseBhav(BaseSource):
    name = "nse_bhav"
    label = "NSE bhavcopy"
    description = (
        "NSE's official daily price files (unadjusted): "
        "every EQ, BE, BZ stock and REIT/InvIT unit since 2010."
    )
    homepage = "https://www.nseindia.com/all-reports"
    http_policies = {"nsearchives.nseindia.com": HttpPolicy(1.0, 30, 3)}
    capabilities = (
        CapabilitySpec(
            "bars",
            "by_date",
            (
                JobVariant(
                    suffix="daily",
                    title="daily",
                    schedule={"kind": "daily", "at_time": "19:30", "weekdays_only": 1},
                    params={"recent_days": 30, "not_before": "18:30", "weekends": True},
                    refresh=True,
                ),
                JobVariant(
                    suffix="backfill",
                    title="backfill",
                    schedule={"kind": "interval", "interval_min": 60},
                    max_items=400,
                    params={"newest_first": True, "weekends": True},
                ),
            ),
            adjusted=False,
            history_start="2010-01-01",
        ),
    )

    def bars_for_date(self, d: date) -> list[Bar]:
        try:
            body = http.get(bhav_url(d))
        except FetchError as e:
            raise from_fetch_error(e) from e  # 404 = market holiday -> NotFound
        return parse_bhav(body, d)


registry.register(NseBhav())
