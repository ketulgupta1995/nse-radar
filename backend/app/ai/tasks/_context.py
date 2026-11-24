"""Shared prompt pieces for the stock-based AI tasks (SPEC §11). Not a task itself."""

from __future__ import annotations

import logging
import math
import sqlite3

import pandas as pd

from app import db, timeutil
from app.analytics import frames, fundamentals, indicators
from app.sources import registry as sources

log = logging.getLogger(__name__)

MAX_CHARS = 25_000
N_QUARTERS = 6
N_ANNOUNCEMENTS = 15
N_NEWS = 10

AUDIENCE = (
    "The reader is a retail investor who holds stocks for a few weeks up to about 4 months. "
    "They are not a maths person, so use plain language and explain any jargon in a few words. "
    "This is not financial advice: give no buy or sell calls and no price predictions. "
    "Stick to facts from the data, risks, and questions worth verifying. "
    "If anything in the data looks inconsistent or odd, point it out."
)


def _num(v: float | None, digits: int = 1, suffix: str = "") -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v:,.{digits}f}{suffix}"


def _ind(name: str, frame: pd.DataFrame, bench: pd.Series | None, **params) -> float | None:
    try:
        s = indicators.compute(name, frame, bench, **params)
    except Exception:  # noqa: BLE001 - a missing indicator must not break the prompt
        log.exception("indicator %s failed", name)
        return None
    if s is None or s.empty or pd.isna(s.iloc[-1]):
        return None
    return float(s.iloc[-1])


def _price_section(symbol: str) -> str:
    frame = frames.load_frame(symbol)
    if frame.empty:
        return "## Price\nNo price data available.\n"
    bench = frames.load_benchmark()
    bench = bench if len(bench) else None
    last = float(frame["close"].iloc[-1])
    lines = [f"Last close: {_num(last, 2)} (on {frame.index[-1].date().isoformat()})"]
    for label, n in (("1 month", 21), ("3 months", 63), ("6 months", 126), ("1 year", 252)):
        ret = _ind("return_pct", frame, bench, n=n)
        rel = _ind("rel_strength", frame, bench, n=n) if bench is not None else None
        lines.append(f"Return over {label}: {_num(ret, 1, '%')}; vs Nifty 500: {_num(rel, 1, ' points')}")
    lines.append(f"Distance from 52-week high: {_num(_ind('pct_from_high', frame, bench, n=252), 1, '%')}")
    rsi = _num(_ind("rsi", frame, bench, n=14))
    lines.append(f"RSI (14 days; above 70 is stretched, below 30 is weak): {rsi}")
    atr = _num(_ind("atr_pct", frame, bench, n=14), 2, "%")
    lines.append(f"Daily swing (ATR as % of price, 14 days): {atr}")
    return "## Price\n" + "\n".join(lines) + "\n"


def _fundamentals_section(symbol: str, conn: sqlite3.Connection) -> str:
    data, _ = fundamentals.merge(symbol, conn)
    lines = []
    for meta in fundamentals.FIELDS:
        v = data.get(meta["field"])
        shown = "n/a" if v is None else (_num(v, 2) if isinstance(v, (int, float)) else str(v))
        lines.append(f"{meta['label']}: {shown}")
    return "## Fundamentals\n" + "\n".join(lines) + "\n"


def _quarters_section(symbol: str, conn: sqlite3.Connection) -> str:
    rows: list[sqlite3.Row] = []
    for src in sources.ordered("quarters", conn):
        got = conn.execute(
            "SELECT * FROM quarters WHERE source=? AND symbol=? AND parse_error IS NULL "
            "ORDER BY consolidated DESC, period_end DESC",
            (src.name, symbol),
        ).fetchall()
        if got:
            top = got[0]["consolidated"]
            rows = [r for r in got if r["consolidated"] == top][:N_QUARTERS]
            break
    if not rows:
        return "## Quarterly results\nNo quarterly results available.\n"
    lines = ["(₹ crore unless stated; newest first)"]
    for r in rows:
        lines.append(
            f"Quarter ended {r['period_end']}: sales {_num(r['revenue'])}, "
            f"profit before tax {_num(r['pbt'])}, net profit {_num(r['net_profit'])}, EPS {_num(r['eps'], 2)}"
        )
    return "## Quarterly results\n" + "\n".join(lines) + "\n"


def _announcement_lines(symbol: str, conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT ts, category, headline FROM announcements WHERE symbol=? AND category != 'routine' "
        "ORDER BY ts DESC LIMIT ?",
        (symbol, N_ANNOUNCEMENTS),
    ).fetchall()
    return [f"{r['ts'][:10]} [{r['category']}] {r['headline']}" for r in rows]


def _news_lines(symbol: str, conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT n.ts, n.title FROM news_items n JOIN news_symbols s ON s.news_id=n.id "
        "WHERE s.symbol=? ORDER BY n.ts DESC LIMIT ?",
        (symbol, N_NEWS),
    ).fetchall()
    return [f"{r['ts'][:10]} {r['title']}" for r in rows]


def _list_section(title: str, lines: list[str], empty: str, budget: int) -> str:
    """Newest-first `lines`; drop the oldest until the section fits `budget` characters."""
    lines = list(lines)
    while lines and len(title) + sum(len(x) + 1 for x in lines) > budget:
        lines.pop()
    return f"{title}\n" + ("\n".join(lines) if lines else empty) + "\n"


def stock_context(symbol: str) -> str:
    """Plain-text facts about one stock, at most MAX_CHARS characters."""
    symbol = symbol.upper()
    price = _price_section(symbol)  # opens its own connections, so keep it outside the transaction
    with db.tx() as conn:
        head = (
            f"# {symbol}\nToday's date: {timeutil.today().isoformat()}. "
            f"Latest price data is from {frames.last_trading_date(conn) or 'unknown'}.\n"
        )
        fixed = [price, _fundamentals_section(symbol, conn), _quarters_section(symbol, conn)]
        ann = _announcement_lines(symbol, conn)
        news = _news_lines(symbol, conn)
    used = len(head) + sum(len(s) for s in fixed) + 4  # separators
    free = max(MAX_CHARS - used - 200, 0)
    ann_sec = _list_section("## Recent announcements", ann, "None in the data.", free // 2)
    news_sec = _list_section("## Recent news", news, "None in the data.", free - len(ann_sec))
    text = "\n".join([head, *fixed, ann_sec, news_sec])
    return text[:MAX_CHARS]
