"""Append-only log of new screen and shortlist ideas (SPEC §16.2)."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from app import db, timeutil
from app.analytics import frames, indicators, score

log = logging.getLogger(__name__)

TOP_N = 10
HISTORY_DAYS = 730
NOTIONAL_INR = 100000
LAST_TOP10_KEY = "signal_last_top10"  # internal setting, not in DEFAULT_SETTINGS
REPO_ROOT = Path(__file__).resolve().parents[3]

INSERT = (
    "INSERT OR IGNORE INTO signals(source, screen_id, screen_name, symbol, as_of, rank, score, components, "
    "reasons, planned_entry, atr14, planned_stop, planned_target, exit_config, rule_hash, score_weights, "
    "app_version, bars_as_of, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def exit_config(conn=None) -> dict:
    """The frozen exit rules every logged signal is judged by."""
    return {
        "exits": [
            {"type": "stop_atr", "params": {"k": db.get_setting("atr_stop_multiple", conn)}},
            {"type": "target_atr", "params": {"k": db.get_setting("signal_target_atr_multiple", conn)}},
            {"type": "time_stop", "params": {"days": db.get_setting("default_time_stop_weeks", conn) * 5}},
        ],
        "notional_inr": NOTIONAL_INR,
    }


def _app_version() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, timeout=5
        )
        out = r.stdout.decode().strip()
        return out if r.returncode == 0 and out else "unknown"
    except Exception:
        return "unknown"


def _last_top10() -> list[str] | None:
    try:
        return list(db.get_setting(LAST_TOP10_KEY))
    except KeyError:
        return None


def _read_inputs(today: str) -> tuple[list[dict], dict[str, str], dict, dict]:
    with db.tx() as c:
        screen_rows = [
            dict(r)
            for r in c.execute(
                "SELECT r.screen_id, s.name, s.rule, r.symbol, r.as_of FROM screen_results r "
                "JOIN screens s ON s.id=r.screen_id WHERE r.first_seen=? ORDER BY r.screen_id, r.symbol",
                (today,),
            )
        ]
        newest = {
            r["symbol"]: r["as_of"]
            for r in c.execute("SELECT symbol, MAX(as_of) AS as_of FROM screen_results GROUP BY symbol")
        }
        cfg = exit_config(c)
        weights = db.get_setting("score_weights", c)
    return screen_rows, newest, cfg, weights


def _price_levels(frame: pd.DataFrame, bench: pd.Series, as_of: str) -> tuple[float, float] | None:
    """(close, ATR14) on `as_of`, or None when the frame has no such bar or ATR is NaN."""
    ts = pd.Timestamp(as_of)
    if len(frame) == 0 or ts not in frame.index:
        return None
    atr = float(indicators.compute("atr", frame, bench, n=14).loc[ts])
    if math.isnan(atr):
        return None
    return float(frame["close"].loc[ts]), atr


def _row(
    source: str, screen_id: int, screen_name: str | None, symbol: str, as_of: str, rank: int | None,
    ranked: dict | None, levels: tuple[float, float], cfg: dict, common: dict[str, Any],
    rule_hash: str | None,
) -> tuple:  # fmt: skip
    close, atr = levels
    k_stop = cfg["exits"][0]["params"]["k"]
    k_target = cfg["exits"][1]["params"]["k"]
    return (
        source, screen_id, screen_name, symbol, as_of, rank,
        ranked["score"] if ranked else None,
        json.dumps(ranked["components"]) if ranked else None,
        json.dumps(ranked["reasons"] if ranked else []),
        close, atr, close - k_stop * atr, close + k_target * atr,
        json.dumps(cfg), rule_hash, common["weights"], common["version"], common["bars_as_of"],
        common["created_at"],
    )  # fmt: skip


def log_signals(shortlist: list[dict] | None = None) -> dict:
    """Log today's new screen members and new top-10 shortlist entries. Returns the counts."""
    today = timeutil.today().isoformat()
    if shortlist is None:
        shortlist = score.score_candidates()
    screen_rows, newest, cfg, weights = _read_inputs(today)
    ranked = {r["symbol"]: r for r in shortlist}
    top10 = [r["symbol"] for r in shortlist[:TOP_N]]
    previous = _last_top10()
    new_top = [] if previous is None else [s for s in top10 if s not in previous]

    # everything that touches price frames happens before the write transaction
    bench = frames.load_benchmark()
    start = (timeutil.today() - timedelta(days=HISTORY_DAYS)).isoformat()
    wanted: dict[str, set[str]] = {}
    for r in screen_rows:
        wanted.setdefault(r["symbol"], set()).add(r["as_of"])
    for sym in new_top:
        if sym in newest:
            wanted.setdefault(sym, set()).add(newest[sym])
    levels: dict[tuple[str, str], tuple[float, float] | None] = {}
    for sym, dates in sorted(wanted.items()):
        frame = frames.load_frame(sym, start)
        for as_of in dates:
            levels[(sym, as_of)] = _price_levels(frame, bench, as_of)
    bars_as_of = frames.last_trading_date() or today
    common = {
        "weights": json.dumps(weights), "version": _app_version(), "bars_as_of": bars_as_of,
        "created_at": timeutil.now_iso(),
    }  # fmt: skip

    screen_batch: list[tuple] = []
    for r in screen_rows:
        lv = levels.get((r["symbol"], r["as_of"]))
        if lv is None:
            log.warning("signal skipped for %s on %s: no bar or no ATR", r["symbol"], r["as_of"])
            continue
        rule_hash = hashlib.sha1(score.canonical(json.loads(r["rule"])).encode()).hexdigest()
        screen_batch.append(_row("screen", r["screen_id"], r["name"], r["symbol"], r["as_of"], None,
                                 ranked.get(r["symbol"]), lv, cfg, common, rule_hash))  # fmt: skip
    short_batch: list[tuple] = []
    for sym in new_top:
        lv = levels.get((sym, newest[sym])) if sym in newest else None
        if lv is None:
            log.warning("signal skipped for %s: no bar or no ATR", sym)
            continue
        short_batch.append(_row("shortlist", 0, None, sym, newest[sym], top10.index(sym) + 1,
                                ranked[sym], lv, cfg, common, None))  # fmt: skip

    counts = {"screen": 0, "shortlist": 0}
    with db.tx() as c:
        for row in screen_batch:
            counts["screen"] += c.execute(INSERT, row).rowcount
        for row in short_batch:
            counts["shortlist"] += c.execute(INSERT, row).rowcount
        db.set_setting(LAST_TOP10_KEY, top10, c)
        c.execute(
            "INSERT INTO signal_days(as_of, logged, run_at) VALUES (?,?,?) "
            "ON CONFLICT(as_of) DO UPDATE SET logged=signal_days.logged+excluded.logged, "
            "run_at=excluded.run_at",
            (bars_as_of, counts["screen"] + counts["shortlist"], common["created_at"]),
        )
    return {"as_of": bars_as_of, **counts}
