"""NSE archives: the Nifty 500 list (the stock universe)."""

from datetime import date, timedelta

from app import timeutil
from app.sources import http, registry
from app.sources.base import (
    BaseSource,
    CapabilitySpec,
    FetchError,
    IndexBar,
    JobVariant,
    NotFound,
    SymbolChange,
    SymbolRow,
    from_fetch_error,
)
from app.sources.http import HttpPolicy
from app.sources.parsers.nse_lists import (
    index_close_url,
    parse_index_close,
    parse_nifty500,
    parse_symbol_changes,
)

NIFTY500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
SYMBOL_CHANGES_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"


class NseArchives(BaseSource):
    name = "nse_archives"
    label = "NSE archives"
    description = "Official Nifty 500 constituent list from NSE's public archive files."
    homepage = "https://www.nseindia.com"
    http_policies = {"nsearchives.nseindia.com": HttpPolicy(1.0, 30, 3)}
    capabilities = (
        CapabilitySpec(
            "universe",
            "whole",
            (
                JobVariant(
                    schedule={"kind": "weekly", "weekday": 0, "at_time": "08:00"},
                    min_age_hours=144,
                    refresh=True,
                ),
            ),
        ),
        CapabilitySpec(
            "index",
            "whole",
            (
                JobVariant(
                    schedule={"kind": "daily", "at_time": "20:00", "weekdays_only": 1},
                    refresh=True,
                ),
            ),
        ),
        CapabilitySpec(
            "symbol_changes",
            "whole",
            (
                JobVariant(
                    schedule={"kind": "weekly", "weekday": 0, "at_time": "08:10"},
                    min_age_hours=144,
                ),
            ),
        ),
    )

    def symbol_changes(self) -> list[SymbolChange]:
        try:
            body = http.get(SYMBOL_CHANGES_URL, accept="text/csv,*/*")
        except FetchError as e:
            raise from_fetch_error(e) from e
        return parse_symbol_changes(body)

    def universe(self) -> list[SymbolRow]:
        try:
            body = http.get(NIFTY500_URL, accept="text/csv,*/*")
        except FetchError as e:
            raise from_fetch_error(e) from e
        return parse_nifty500(body)

    def index_bars(self, index_name: str, start: date) -> list[IndexBar]:
        """One small file per day: look at the last 15 days at most, skipping days without a file."""
        today = timeutil.today()
        d = max(start, today - timedelta(days=15))
        out: list[IndexBar] = []
        while d <= today:
            if d.weekday() < 5:
                try:
                    body = http.get(index_close_url(d), accept="text/csv,*/*")
                except FetchError as e:
                    err = from_fetch_error(e)
                    if not isinstance(err, NotFound):
                        raise err from e
                else:
                    close = parse_index_close(body, index_name)
                    if close is not None:
                        out.append(IndexBar(index_name, d.isoformat(), close))
            d += timedelta(days=1)
        return out


registry.register(NseArchives())
