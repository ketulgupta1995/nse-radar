"""NSE website JSON API: corporate actions, quarterly results (old + integrated lists), announcements."""

from datetime import date, datetime

from app import config, timeutil
from app.sources import http, registry
from app.sources.base import (
    WHOLE_UNIVERSE,
    Action,
    Announcement,
    BaseSource,
    CapabilitySpec,
    Event,
    FetchError,
    JobVariant,
    NotFound,
    Quarter,
    SourceError,
    SourceRefused,
    from_fetch_error,
)
from app.sources.http import HttpPolicy
from app.sources.parsers.actions import parse_action_subject, parse_nse_date
from app.sources.parsers.nse_events import parse_event_calendar
from app.sources.parsers.xbrl import (
    INTEGRATED_FINANCIALS,
    XbrlError,
    parse_integrated_list,
    parse_results_list,
    parse_xbrl,
)

API = "https://www.nseindia.com/api"
MAX_PERIODS = 12
HEADLINE_CHARS = 120


def _announcement_ts(raw: str | None) -> str | None:
    """'09-Nov-2026 17:12:15' (IST) -> '2026-11-09T17:12:15+05:30'."""
    try:
        naive = datetime.strptime((raw or "").strip(), "%d-%b-%Y %H:%M:%S")
        return naive.replace(tzinfo=config.TZ).isoformat()
    except ValueError:
        return None


def parse_announcements(items: list, symbol: str, since: date) -> list[Announcement]:
    out: dict[tuple[str, str], Announcement] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        ts = _announcement_ts(it.get("an_dt"))
        text = (it.get("attchmntText") or "").strip()
        headline = (it.get("desc") or "").strip() or text[:HEADLINE_CHARS]
        if ts is None or not headline or datetime.fromisoformat(ts).date() < since:
            continue
        url = (it.get("attchmntFile") or "").strip() or None
        out[(ts, headline)] = Announcement(symbol.upper(), ts, headline, text or None, url)
    return sorted(out.values(), key=lambda a: a.ts, reverse=True)


class NseApi(BaseSource):
    name = "nse_api"
    label = "NSE website data"
    description = "NSE's public corporate data: splits and bonuses (and later results and announcements)."
    homepage = "https://www.nseindia.com"
    http_policies = {
        "www.nseindia.com": HttpPolicy(2.0, 30, 2),
        "nsearchives.nseindia.com": HttpPolicy(1.0, 30, 3),
    }
    capabilities = (
        CapabilitySpec(
            "actions",
            "by_symbol",
            (
                JobVariant(
                    schedule={"kind": "weekly", "weekday": 5, "at_time": "09:00"},
                    max_items=WHOLE_UNIVERSE,
                    min_age_hours=144,
                ),
            ),
        ),
        CapabilitySpec(
            "quarters",
            "by_symbol",
            (
                JobVariant(
                    schedule={"kind": "interval", "interval_min": 60},
                    max_items=60,  # 2 drains a weekday, 1 on weekends: 720 a week covers 500 stocks
                    min_age_hours=168,
                ),
            ),
        ),
        CapabilitySpec(
            "announcements",
            "by_symbol",
            (
                JobVariant(
                    suffix="watch",
                    title="watchlist",
                    scope="watch",
                    schedule={"kind": "interval", "interval_min": 90},
                    min_age_hours=1,
                    params={"days": 7},
                    refresh=True,
                ),
                JobVariant(
                    suffix="all",
                    title="all stocks",
                    scope="universe",
                    schedule={"kind": "daily", "at_time": "22:30"},
                    max_items=500,
                    min_age_hours=20,
                    params={"days": 3},
                ),
            ),
        ),
        CapabilitySpec(
            "events",
            "whole",
            (
                JobVariant(
                    schedule={"kind": "daily", "at_time": "08:30"},
                    min_age_hours=20,
                    refresh=True,
                ),
            ),
        ),
    )

    def events(self) -> list[Event]:
        try:
            data = http.get_json(f"{API}/event-calendar")
        except FetchError as e:
            raise from_fetch_error(e) from e
        return parse_event_calendar(data)

    def actions(self, symbol: str) -> list[Action]:
        try:
            # Without a date range NSE returns only the latest 20 rows, which hides old splits.
            data = http.get_json(
                f"{API}/corporates-corporateActions",
                params={
                    "index": "equities",
                    "symbol": symbol,
                    "from_date": config.HISTORY_START.strftime("%d-%m-%Y"),
                    "to_date": timeutil.today().strftime("%d-%m-%Y"),
                },
            )
        except FetchError as e:
            raise from_fetch_error(e) from e
        if not isinstance(data, list):
            raise SourceError("corporate actions response was not a list")
        out: dict[tuple[str, str], Action] = {}
        for item in data:
            if not isinstance(item, dict) or item.get("series") != "EQ":
                continue
            ex = parse_nse_date(item.get("exDate"))
            subject = (item.get("subject") or "").strip()
            if ex is None or not subject:
                continue
            kind, factor = parse_action_subject(subject)
            out[(ex, subject)] = Action(symbol.upper(), ex, subject, kind, factor)  # type: ignore[arg-type]
        return sorted(out.values(), key=lambda a: (a.ex_date, a.subject))

    def announcements(self, symbol: str, since: date) -> list[Announcement]:
        # Verified 2026-11-09: from_date/to_date filter server-side (3 items vs 3,385 without them).
        try:
            data = http.get_json(
                f"{API}/corporate-announcements",
                params={
                    "index": "equities",
                    "symbol": symbol.upper(),
                    "from_date": since.strftime("%d-%m-%Y"),
                    "to_date": timeutil.today().strftime("%d-%m-%Y"),
                },
            )
        except FetchError as e:
            raise from_fetch_error(e) from e
        if not isinstance(data, list):
            raise SourceError("announcements response was not a list")
        return parse_announcements(data, symbol, since)

    def quarters(self, symbol: str, known_periods: set[str]) -> list[Quarter]:
        """Newest 12 unknown periods; one filing per period (consolidated preferred, else standalone).

        Two NSE lists: integrated filings (Mar 2025 onwards) and the old results list (up to
        Dec 2024). Either may be empty for a symbol; integrated wins if both have a period.
        """
        sym = symbol.upper()
        filings = self._integrated_filings(sym) + self._legacy_filings(sym)
        if not filings:
            raise NotFound(f"no results filings for {sym}")
        chosen: dict[str, dict] = {}
        for f in filings:  # integrated first; consolidated sorts first within a period
            chosen.setdefault(f["period_end"], f)
        periods = [p for p in sorted(chosen, reverse=True) if p not in known_periods][:MAX_PERIODS]
        return [self._quarter(sym, chosen[p]) for p in periods]

    def _legacy_filings(self, sym: str) -> list[dict]:
        data = self._results_json(
            "corporates-financial-results", {"index": "equities", "period": "Quarterly", "symbol": sym}
        )
        if data is None:
            return []
        if not isinstance(data, list):
            raise SourceError("financial results response was not a list")
        return parse_results_list(data)

    def _integrated_filings(self, sym: str) -> list[dict]:
        data = self._results_json(
            "integrated-filing-results",
            {"index": "equities", "symbol": sym, "type": INTEGRATED_FINANCIALS},
        )
        if data is None:
            return []
        if not isinstance(data, dict | list):
            raise SourceError("integrated filing response was not JSON object or list")
        return parse_integrated_list(data)

    def _results_json(self, path: str, params: dict) -> object | None:
        """JSON from one results list; None when NSE has nothing for the symbol (404)."""
        try:
            return http.get_json(f"{API}/{path}", params=params)
        except FetchError as e:
            err = from_fetch_error(e)
            if isinstance(err, NotFound):
                return None
            raise err from e

    def _quarter(self, sym: str, f: dict) -> Quarter:
        base = dict(
            symbol=sym,
            period_end=f["period_end"],
            consolidated=f["consolidated"],
            period_start=f["period_start"],
            audited=f["audited"],
            filing_date=f["filing_date"],
            url=f["xbrl_url"],
        )
        try:
            values = parse_xbrl(http.get(f["xbrl_url"]), f["period_start"], f["period_end"])
        except FetchError as e:
            err = from_fetch_error(e)
            if isinstance(err, SourceRefused):
                raise err from e
            return Quarter(**base, parse_error=f"download failed: {e}")
        except XbrlError as e:
            return Quarter(**base, parse_error=str(e))
        return Quarter(**base, **values)


registry.register(NseApi())
