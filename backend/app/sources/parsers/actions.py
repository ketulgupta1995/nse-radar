"""Corporate-action subject parsing for NSE (SPEC §7.2). Pure functions."""

import re
from datetime import datetime

_AMOUNT = r"(\d+(?:\.\d+)?)"
# "spl"/"splt" count only when an amount follows ("Spl Int Div" is a dividend); "fv spl..." always counts
_SPLIT_WORD = r"(?:split|sub[- ]?division|\bfv\s+splt?|\bsplt?(?=[\s-]*(?:frm|from|rs|re)\b))"
_STRONG_SPLIT = re.compile(r"split|sub[- ]?division|\bfv\s+splt?")
_DIVIDEND = re.compile(r"\bdiv\b|dividend")
_SPLIT = re.compile(
    rf"{_SPLIT_WORD}.*?(?:rs|re)\.?\s*{_AMOUNT}\s*/?-?.*?to\s*(?:rs|re)\.?\s*{_AMOUNT}",
    re.I | re.S,
)
_BONUS = re.compile(
    r"(?:bonus|\bbon\b)\s*(?:issue\s*)?(?:shares\s*)?(?:in\s+the\s+ratio\s+of\s*)?(?:of\s*)?-?\s*"
    r"(\d+)\s*:\s*(\d+)",
    re.I,
)
# bonus debentures / preference shares / NCRPS are not equity bonuses: drop that clause
_IGNORED_BONUS = re.compile(r"bonus[^/+]*?(?:\bdeb|ncrps?\b|preference)[^/+]*", re.I)


def _split_factor(subject: str) -> float | None:
    m = _SPLIT.search(subject)
    if m:
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and 0 < new <= old:
            return new / old
    return None


def _bonus_factor(subject: str) -> float | None:
    m = _BONUS.search(subject)
    if m:
        x, y = int(m.group(1)), int(m.group(2))
        if x > 0 and y > 0:
            return y / (x + y)
    return None


def parse_action_subject(subject: str) -> tuple[str, float | None]:
    """-> (kind, factor); factor multiplies prices BEFORE the ex-date. Split and bonus together multiply."""
    cleaned = _IGNORED_BONUS.sub(" ", subject)
    ignored_bonus = cleaned != subject
    subject = cleaned
    low = subject.lower()
    has_split = bool(re.search(_SPLIT_WORD, low))
    if has_split and _DIVIDEND.search(low) and not _STRONG_SPLIT.search(low):
        has_split = False  # "Div ... Spl Rs.100" is a special dividend, not a split
    has_bonus = "bonus" in low or bool(re.search(r"\bbon\b", low))
    if not has_split and not has_bonus:
        if ignored_bonus:
            return "other", None
        if "rights" in low:
            return "rights", None
        if "demerger" in low or "scheme of arrangement" in low:
            return "demerger", None
        return "other", None
    split = _split_factor(subject) if has_split else 1.0
    bonus = _bonus_factor(subject) if has_bonus else 1.0
    if split is None or bonus is None:
        return "unparsed", None
    return ("split" if has_split else "bonus"), split * bonus


def parse_nse_date(s: str | None) -> str | None:
    """'14-Oct-2026' -> '2026-10-14'; '-' or blank or unreadable -> None."""
    if not s or s.strip() in ("-", ""):
        return None
    try:
        return datetime.strptime(s.strip(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None
