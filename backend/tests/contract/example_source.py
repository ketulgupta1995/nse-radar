"""A tiny example adapter showing the pattern (SPEC §3.2, docs/ADDING_A_SOURCE.md).

It is NOT in app/sources/adapters/, so it never shows up in the running app. The contract suite
registers it inside the test only.
"""

import csv
import io
from datetime import date

from app.sources import http
from app.sources.base import (
    Bar,
    BaseSource,
    CapabilitySpec,
    FetchError,
    JobVariant,
    SourceError,
    SymbolRow,
    from_fetch_error,
)
from app.sources.http import HttpPolicy


class ExampleSource(BaseSource):
    name = "example"
    label = "Example source"
    description = "A tiny CSV source used to show how adapters are written."
    homepage = "https://example.test"
    http_policies = {"example.test": HttpPolicy(1.0, 20, 2)}
    capabilities = (
        CapabilitySpec(
            "universe",
            "whole",
            (JobVariant(schedule={"kind": "weekly", "weekday": 0, "at_time": "08:00"}, min_age_hours=144),),
        ),
        CapabilitySpec(
            "bars",
            "by_date",
            (JobVariant(suffix="daily", title="daily", params={"recent_days": 30, "not_before": "18:30"}),),
            adjusted=False,
            history_start="2026-01-01",
        ),
    )

    def _csv(self, url: str) -> list[dict]:
        try:
            body = http.get(url)
        except FetchError as e:
            raise from_fetch_error(e) from e  # 403 -> SourceRefused, 404 -> NotFound, else SourceError
        try:
            return list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
        except (UnicodeDecodeError, csv.Error) as e:
            raise SourceError(f"unreadable CSV from {url}: {e}") from e

    def universe(self) -> list[SymbolRow]:
        rows = self._csv("https://example.test/universe.csv")
        return [
            SymbolRow(r["symbol"].strip().upper(), r["name"].strip(), r.get("industry") or None)
            for r in rows
        ]

    def bars_for_date(self, d: date) -> list[Bar]:
        rows = self._csv(f"https://example.test/bars/{d:%Y%m%d}.csv")
        try:
            return [
                Bar(
                    r["symbol"].strip().upper(),
                    d.isoformat(),
                    float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                    float(r["volume"]),
                )
                for r in rows
            ]  # fmt: skip
        except (KeyError, ValueError) as e:
            raise SourceError(f"bad bar row for {d}: {e}") from e


SOURCE = ExampleSource()
