"""RSS/Atom feed parsing (SPEC §3.3 `rss`). Pure function: bytes in, NewsItem list out."""

from __future__ import annotations

import calendar
import html
import re
from datetime import UTC, datetime

import feedparser

from app import config, timeutil
from app.sources.base import NewsItem

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
MAX_SUMMARY = 500


def _clean(text: str | None) -> str:
    return _SPACES.sub(" ", html.unescape(_TAGS.sub(" ", text or ""))).strip()


def _ts(entry) -> str:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:  # feedparser gives UTC struct_time
        utc = datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)
        return utc.astimezone(config.TZ).isoformat(timespec="seconds")
    return timeutil.now().astimezone(config.TZ).isoformat(timespec="seconds")


def parse_feed(content: bytes, feed_name: str) -> list[NewsItem]:
    """Items with a title and a link. HTML is stripped from the summary; a missing date means 'now'."""
    items: list[NewsItem] = []
    for e in feedparser.parse(content).entries:
        title = _clean(e.get("title"))
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        summary = _clean(e.get("summary") or e.get("description"))[:MAX_SUMMARY] or None
        items.append(NewsItem(feed_name, _ts(e), title, link, summary))
    return items
