"""Screener.in company pages: ratios, growth, debt and shareholding (public pages only, slow and polite)."""

from app.sources import http, registry
from app.sources.base import (
    BaseSource,
    CapabilitySpec,
    FetchError,
    FundSnapshot,
    JobVariant,
    NotFound,
    SourceError,
    from_fetch_error,
)
from app.sources.http import HttpPolicy
from app.sources.parsers.screener_html import parse_company_page, to_fields

BASE = "https://www.screener.in/company"


def _quarters_ok(parsed: dict) -> bool:
    return "quarters" not in parsed["missing"]


class Screener(BaseSource):
    name = "screener"
    label = "Screener.in"
    description = "Company ratios, growth, debt and shareholding from Screener.in's public pages."
    homepage = "https://www.screener.in"
    http_policies = {"www.screener.in": HttpPolicy(5.0, 30, 2)}
    capabilities = (
        CapabilitySpec(
            "fundamentals",
            "by_symbol",
            (
                JobVariant(
                    schedule={"kind": "interval", "interval_min": 60},
                    max_items=60,
                    min_age_hours=168,
                ),
            ),
        ),
    )

    def _page(self, symbol: str, variant: str) -> dict:
        url = f"{BASE}/{symbol.upper()}/" + ("consolidated/" if variant == "consolidated" else "")
        try:
            html = http.get(url, accept="text/html")
        except FetchError as e:
            raise from_fetch_error(e) from e
        try:
            return parse_company_page(html)
        except Exception as e:  # parser bugs on odd pages must fail this symbol only
            raise SourceError(f"could not parse Screener page for {symbol}: {e}") from e

    def fundamentals(self, symbol: str) -> FundSnapshot:
        variant = "consolidated"
        try:
            parsed = self._page(symbol, "consolidated")
        except NotFound:
            parsed = None
        if parsed is None or not _quarters_ok(parsed):
            try:
                alt = self._page(symbol, "standalone")
            except NotFound:
                if parsed is None:
                    raise
                alt = None
            if alt is not None:
                parsed, variant = alt, "standalone"
        assert parsed is not None
        detail = {
            "quarters": parsed["quarters"],
            "profit_loss": parsed["profit_loss"],
            "shareholding": parsed["shareholding"],
            "balance_sheet": parsed["balance_sheet"],
            "ratios_hist": parsed["ratios_hist"],
            "growth": parsed["growth"],
            "variant": variant,
        }
        return FundSnapshot(symbol.upper(), to_fields(parsed), detail)


registry.register(Screener())
