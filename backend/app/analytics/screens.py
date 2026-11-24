"""Run saved screens over the universe (SPEC §10). Score and shortlist are added in a later ticket."""

from __future__ import annotations

import json
import logging
import time
from datetime import timedelta

import pandas as pd

from app import db, timeutil
from app.analytics import frames, indicators, rules
from app.analytics.rules import RuleError

log = logging.getLogger(__name__)

HISTORY_DAYS = 730  # enough for 252-day indicators plus slack
STALE_DAYS = 7  # a symbol whose last bar is older than the newest one by this much is skipped
PREVIEW_LIMIT_S = 20.0


class TooSlow(ValueError):
    """Preview ran past its time limit."""


def _fundamentals() -> dict[str, dict]:
    with db.tx() as c:
        rows = c.execute("SELECT symbol, data FROM fundamentals").fetchall()
    return {r["symbol"]: json.loads(r["data"]) for r in rows}


def _round(values: dict) -> dict:
    return {k: (None if v is None else round(float(v), 2)) for k, v in values.items()}


def _latest_ranks(rule, fresh: list, bench) -> dict[str, dict]:
    """{symbol: {rank_key: one-value Series at its last date}} for the rule's ranked operands."""
    out: dict[str, dict] = {}
    for o in rules.rank_operands(rule):
        key = rules.rank_key(o)
        last = {
            sym: indicators.compute(o.ind, frame, bench, **o.params).iloc[-1:] for sym, frame in fresh
        }
        values = pd.DataFrame({sym: s.reset_index(drop=True) for sym, s in last.items()})
        pct = rules.cross_rank(values.astype(float))
        for sym, s in last.items():
            out.setdefault(sym, {})[key] = pd.Series(pct[sym].to_numpy(), index=s.index)
    return out


def scan(rule, ctx=None, time_limit: float | None = None) -> list[dict]:
    """Evaluate `rule` on the latest bar of every universe symbol. Rows are sorted by symbol.

    Each row: {symbol, as_of, values}. Never call this inside a write transaction.
    """
    parsed = rules.validate_rule(rule) if isinstance(rule, dict) else rule
    started = time.monotonic()
    start = (timeutil.today() - timedelta(days=HISTORY_DAYS)).isoformat()
    bench = frames.load_benchmark()
    fund = _fundamentals()
    loaded = []
    for sym in frames.universe():
        if ctx is not None:
            ctx.check_stop()
        if time_limit is not None and time.monotonic() - started > time_limit:
            raise TooSlow("too slow: narrow the rule or run it as a saved screen instead")
        frame = frames.load_frame(sym, start)
        if len(frame) > 0:
            loaded.append((sym, frame))
    newest = max((f.index[-1] for _, f in loaded), default=None)
    fresh = [(s, f) for s, f in loaded if (newest - f.index[-1]).days <= STALE_DAYS]
    ranks = _latest_ranks(parsed, fresh, bench)
    rows: list[dict] = []
    for sym, frame in loaded:
        if ctx is not None:
            ctx.check_stop()
        if time_limit is not None and time.monotonic() - started > time_limit:
            raise TooSlow("too slow: narrow the rule or run it as a saved screen instead")
        if (newest - frame.index[-1]).days > STALE_DAYS:
            continue
        ok, details = rules.evaluate_latest(parsed, frame, bench, fund.get(sym), ranks.get(sym))
        if ok:
            as_of = frame.index[-1].date().isoformat()
            rows.append({"symbol": sym, "as_of": as_of, "values": _round(details)})
    return sorted(rows, key=lambda r: r["symbol"])


def preview(rule) -> dict:
    """{count, rows:[{symbol, values}]}; raises RuleError for a bad rule and TooSlow after 20 s."""
    rows = scan(rule, time_limit=PREVIEW_LIMIT_S)
    return {"count": len(rows), "rows": [{"symbol": r["symbol"], "values": r["values"]} for r in rows]}


def run_screen(screen_id: int, ctx=None) -> list[dict]:
    """Run a saved screen and replace its stored results, keeping `first_seen` for repeat symbols."""
    with db.tx() as c:
        row = c.execute("SELECT rule FROM screens WHERE id=?", (screen_id,)).fetchone()
    if row is None:
        raise KeyError(f"no screen {screen_id}")
    found = scan(json.loads(row["rule"]), ctx)
    today = timeutil.today().isoformat()
    with db.tx() as c:
        old = c.execute("SELECT symbol, first_seen FROM screen_results WHERE screen_id=?", (screen_id,))
        seen = {r["symbol"]: r["first_seen"] for r in old}
        c.execute("DELETE FROM screen_results WHERE screen_id=?", (screen_id,))
        for r in found:
            r["first_seen"] = seen.get(r["symbol"], today)
            c.execute(
                "INSERT INTO screen_results(screen_id, symbol, as_of, values_json, first_seen) "
                "VALUES (?,?,?,?,?)",
                (screen_id, r["symbol"], r["as_of"], json.dumps(r["values"]), r["first_seen"]),
            )
        # remember the run even when nothing matched (screen_results alone can't say so)
        as_of = max((r["as_of"] for r in found), default=None) or frames.last_trading_date(c) or today
        runs = last_runs(c)
        runs[str(screen_id)] = as_of
        db.set_setting(LAST_RUNS_KEY, runs, c)
    return found


LAST_RUNS_KEY = "screen_last_runs"  # internal: {screen_id: as_of}; not a user setting


def last_runs(conn=None) -> dict[str, str]:
    """{str(screen_id): as_of} of each screen's latest run, including runs with no matches."""
    try:
        return dict(db.get_setting(LAST_RUNS_KEY, conn))
    except KeyError:
        return {}


__all__ = ["RuleError", "TooSlow", "last_runs", "preview", "run_screen", "scan"]
