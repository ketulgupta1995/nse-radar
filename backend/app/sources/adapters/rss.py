"""RSS news feeds from the `rss_feeds` setting (SPEC §3.3)."""

import logging
import sqlite3

from app import db
from app.sources import http, registry
from app.sources.base import (
    BaseSource,
    CapabilitySpec,
    FetchError,
    JobVariant,
    NewsItem,
    SourceError,
    SourceRefused,
    from_fetch_error,
)
from app.sources.parsers.rss import parse_feed

log = logging.getLogger(__name__)


def _feeds() -> list[dict]:
    try:
        return db.get_setting("rss_feeds")
    except (KeyError, sqlite3.Error):  # no database yet (contract tests): use the shipped defaults
        return db.DEFAULT_SETTINGS["rss_feeds"]


class Rss(BaseSource):
    name = "rss"
    label = "News feeds (RSS)"
    description = "Market headlines from the RSS feeds listed in Settings, linked to the stocks they mention."
    homepage = "https://en.wikipedia.org/wiki/RSS"
    capabilities = (
        CapabilitySpec(
            "news",
            "whole",
            (JobVariant(schedule={"kind": "interval", "interval_min": 120}, refresh=True),),
        ),
    )

    def news(self) -> list[NewsItem]:
        feeds = _feeds()
        items: list[NewsItem] = []
        errors: list[Exception] = []
        for feed in feeds:
            try:
                body = http.get(feed["url"], accept="application/rss+xml, application/xml, text/xml")
                items.extend(parse_feed(body, feed["name"]))
            except FetchError as e:
                errors.append(from_fetch_error(e))
                log.warning("news feed %s skipped: %s", feed["name"], e)
            except Exception as e:  # a broken feed must not stop the others
                errors.append(e)
                log.warning("news feed %s skipped: %s: %s", feed["name"], type(e).__name__, e)
        if feeds and len(errors) == len(feeds):
            if all(isinstance(e, SourceRefused) for e in errors):
                raise errors[0]  # every site refused us: the job stops and the source is paused
            raise SourceError("every news feed failed")
        return items


registry.register(Rss())
