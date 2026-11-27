"""Normalized records, errors and the adapter base class (SPEC §3.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.sources import secrets
from app.sources.http import FetchError, HttpPolicy

Capability = Literal[
    "universe",
    "bars",
    "actions",
    "index",
    "fundamentals",
    "quarters",
    "announcements",
    "news",
    "symbol_changes",
    "events",
    "research",
]


@dataclass(frozen=True)
class SymbolRow:
    symbol: str
    name: str
    industry: str | None = None
    isin: str | None = None


@dataclass(frozen=True)
class Bar:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    value: float | None = None
    trades: int | None = None
    series: str | None = None
    isin: str | None = None


@dataclass(frozen=True)
class Action:
    symbol: str
    ex_date: str
    subject: str
    kind: Literal["split", "bonus", "demerger", "rights", "other", "unparsed"]
    factor: float | None  # multiplier for prices BEFORE ex_date


@dataclass(frozen=True)
class IndexBar:
    index_name: str
    date: str
    close: float


@dataclass(frozen=True)
class FundSnapshot:
    symbol: str
    fields: dict[str, float | str | None]  # keys = §9.4 field names only
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Quarter:
    symbol: str
    period_end: str
    consolidated: bool
    period_start: str | None = None
    audited: bool | None = None
    filing_date: str | None = None
    url: str | None = None
    revenue: float | None = None
    other_income: float | None = None
    total_expenses: float | None = None
    pbt: float | None = None
    net_profit: float | None = None
    eps: float | None = None  # ₹ crore; eps ₹
    parse_error: str | None = None


@dataclass(frozen=True)
class Announcement:
    symbol: str
    ts: str
    headline: str
    body: str | None = None
    url: str | None = None
    category: str | None = None  # None -> core categorizer (§13.2)


@dataclass(frozen=True)
class NewsItem:
    feed: str
    ts: str
    title: str
    url: str
    summary: str | None = None


@dataclass(frozen=True)
class SymbolChange:
    old_symbol: str
    new_symbol: str
    effective_date: str
    name: str | None = None  # ticker rename


@dataclass(frozen=True)
class Event:
    symbol: str
    date: str
    purpose: str
    description: str | None = None  # board meeting from the event calendar


@dataclass(frozen=True)
class ResearchReport:
    """One Buy or Sell row from a broker research-report list. Prices in ₹, changes in percent."""

    report_id: str  # the source's own permanent id for the report
    date: str
    stock: str
    author: str
    type: Literal["Buy", "Sell"]
    symbol: str | None = None  # NSE ticker, when the source links the stock to one
    ltp: float | None = None  # last price at the time of fetching
    target: float | None = None
    reco_price: float | None = None
    change_pct: float | None = None  # since the recommendation
    upside_pct: float | None = None  # as published: may be unsigned, even on a Sell
    url: str | None = None


class SourceRefused(Exception):
    """Site refused us (401/403/405/429): the job stops and the source is paused."""


class NotFound(Exception):
    """This key has no data (holiday, unlisted symbol, missing page): item 'skipped'."""


class SourceError(Exception):
    """Anything else (parse failure, timeout): item 'failed'."""


def from_fetch_error(e: FetchError) -> Exception:
    # 405 is how Trendlyne refuses GitHub Actions' IPs (laptop gets 200): treat it as a refusal.
    if e.status in (401, 403, 405, 429):
        return SourceRefused(str(e))
    if e.status == 404:
        return NotFound(str(e))
    return SourceError(str(e))


WHOLE_UNIVERSE = 600  # max_items for a job that must reach every stock each run (Nifty 500, with room)


@dataclass(frozen=True)
class JobVariant:
    suffix: str = ""  # job name = f"{capability}.{source}" + (f".{suffix}" if suffix else "")
    title: str = ""
    scope: Literal["universe", "watch", "none"] = "universe"
    schedule: dict = field(default_factory=lambda: {"kind": "manual"})
    max_items: int = 200  # per run
    min_age_hours: float = 20  # skip keys fetched OK more recently than this
    params: dict = field(default_factory=dict)
    refresh: bool = False  # included in "Refresh now" (§6.4)


@dataclass(frozen=True)
class CapabilitySpec:
    capability: Capability
    mode: Literal["by_symbol", "by_date", "whole"]
    jobs: tuple[JobVariant, ...]
    adjusted: bool | None = None  # bars only
    history_start: str | None = None  # by_date only


class BaseSource:
    name: str
    label: str
    description: str
    homepage: str
    capabilities: tuple[CapabilitySpec, ...] = ()
    http_policies: dict[str, HttpPolicy] = {}
    secrets: tuple[str, ...] = ()
    default_enabled: bool = True

    def universe(self) -> list[SymbolRow]:
        raise NotImplementedError

    def bars_for_date(self, d: date) -> list[Bar]:
        raise NotImplementedError

    def bars_for_symbol(self, symbol: str, start: date, end: date) -> list[Bar]:
        raise NotImplementedError

    def actions(self, symbol: str) -> list[Action]:
        raise NotImplementedError

    def index_bars(self, index_name: str, start: date) -> list[IndexBar]:
        raise NotImplementedError

    def fundamentals(self, symbol: str) -> FundSnapshot:
        raise NotImplementedError

    def quarters(self, symbol: str, known_periods: set[str]) -> list[Quarter]:
        raise NotImplementedError

    def announcements(self, symbol: str, since: date) -> list[Announcement]:
        raise NotImplementedError

    def news(self) -> list[NewsItem]:
        raise NotImplementedError

    def symbol_changes(self) -> list[SymbolChange]:
        raise NotImplementedError

    def events(self) -> list[Event]:
        raise NotImplementedError

    def research(self) -> list[ResearchReport]:
        raise NotImplementedError

    def secret(self, key: str) -> str | None:
        return secrets.get(self.name, key)
