"""Parser for NSE's event calendar (pure function: JSON list in, records out)."""

import logging

from app.sources.base import Event, SourceError
from app.sources.parsers.actions import parse_nse_date

log = logging.getLogger(__name__)


def parse_event_calendar(items: list) -> list[Event]:
    """Items look like {symbol, company, purpose, bm_desc, date 'DD-Mon-YYYY'}."""
    if not isinstance(items, list):
        raise SourceError("event calendar response was not a list")
    out: dict[tuple[str, str, str], Event] = {}
    skipped = 0
    for it in items:
        if not isinstance(it, dict):
            skipped += 1
            continue
        symbol = (it.get("symbol") or "").strip().upper()
        purpose = (it.get("purpose") or "").strip()
        day = parse_nse_date(it.get("date"))
        if not symbol or not purpose or day is None:
            skipped += 1
            continue
        desc = (it.get("bm_desc") or "").strip() or None
        out[(symbol, day, purpose)] = Event(symbol, day, purpose, desc)
    if skipped:
        log.warning("event calendar: skipped %d unusable items", skipped)
    return list(out.values())
