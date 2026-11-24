#!/usr/bin/env python3
"""Overall progress of every remaining backfill, grouped by lane (website), with rate and time left.

Usage (from the repo root):
    backend/.venv/bin/python scripts/backfill_progress.py            # print once
    backend/.venv/bin/python scripts/backfill_progress.py --watch 30 # refresh every 30s (Ctrl+C to quit)
    backend/.venv/bin/python scripts/backfill_progress.py nse        # only some lanes

Read-only; safe to run while the app or the backfill scripts are running.
Rate = items fetched in the last 10 minutes. Time left for a dataset that isn't running yet is a lower
bound from the site's minimum gap between requests (marked >=). A lane's steps run one after another,
so the lane's time left is the sum of its steps.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _backfill import _setup, _variant, bar, coverage, fmt_dur
from app import db, timeutil
from app.sources import http

# lane -> [(title, source, capability, job variant suffix)]   (same order the lanes run them)
LANES: dict[str, list[tuple[str, str, str, str]]] = {
    "nse": [
        ("Quarterly results", "nse_api", "quarters", ""),
        ("Announcements", "nse_api", "announcements", "all"),
        ("Corporate actions", "nse_api", "actions", ""),
    ],
    "yfinance": [("yf fundamentals", "yfinance", "fundamentals", "")],
    "screener": [("Screener funds", "screener", "fundamentals", "")],
}
HOST = {"nse_api": "www.nseindia.com", "screener": "www.screener.in"}
RATE_WINDOW = timedelta(minutes=10)


def recent_rate(source: str, cap: str) -> float:
    """Items per second over the last RATE_WINDOW (0 if nothing fetched in it)."""
    since = timeutil.now() - RATE_WINDOW
    with db.tx() as c:
        rows = c.execute(
            "SELECT fetched_at FROM source_fetch WHERE source=? AND capability=?", (source, cap)
        ).fetchall()
    times = [t for t in (datetime.fromisoformat(r["fetched_at"]) for r in rows) if t >= since]
    if len(times) < 2:
        return 0.0
    span = max((timeutil.now() - min(times)).total_seconds(), 60.0)
    return len(times) / span


def min_gap(source: str) -> float | None:
    if source == "yfinance":
        from app.sources.adapters import yfinance

        return float(getattr(yfinance, "MIN_INTERVAL_S", 0)) or None
    host = HOST.get(source)
    return http.POLICIES[host].min_interval_s if host in http.POLICIES else None


def render(lanes: list[str]) -> str:
    out = [f"Backfill progress  {datetime.now():%Y-%m-%d %H:%M:%S}"]
    grand_done = grand_total = 0
    for lane in lanes:
        lane_left, lane_lower = 0.0, False
        lines = []
        for title, source, cap, suffix in LANES[lane]:
            _, variant = _variant(source, cap, suffix)
            o = coverage(source, cap, variant, set())
            pending = len(o["pending"])
            grand_done += o["done"]
            grand_total += o["total"]
            rate = recent_rate(source, cap)
            if not pending:
                left = "done"
            elif rate:
                secs = pending / rate
                lane_left += secs
                left = f"{fmt_dur(secs)}"
            else:
                gap = min_gap(source)
                if gap:
                    secs = pending * gap
                    lane_left += secs
                    lane_lower = True
                    left = f">={fmt_dur(secs)}"
                else:
                    left = "?"
            rate_s = f"{rate * 60:5.1f}/min" if rate else "    idle "
            fail = f"  failed={o['failed']}" if o["failed"] else ""
            lines.append(
                f"    {title:<18} {bar(o['done'], o['total'], 24)}  {o['done']:>3}/{o['total']:<3}"
                f"  left {pending:>3}  {rate_s}  eta {left}{fail}"
            )
        eta = ("done" if not lane_left else (">=" if lane_lower else "") + fmt_dur(lane_left))
        out.append(f"\n  [{lane}]  lane time left: {eta}")
        out.extend(lines)
    out.append(f"\n  ALL  {bar(grand_done, grand_total, 24)}  {grand_done}/{grand_total} items")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lanes", nargs="*", help=f"lanes to show: {', '.join(LANES)} (default all)")
    ap.add_argument("--watch", type=int, metavar="SEC", help="refresh every SEC seconds")
    args = ap.parse_args()
    bad = [lane for lane in args.lanes if lane not in LANES]
    if bad:
        ap.error(f"unknown lane(s): {', '.join(bad)}")
    lanes = args.lanes or list(LANES)
    _setup()
    if not args.watch:
        print(render(lanes))
        return 0
    while True:
        text = render(lanes)
        print("\033[2J\033[H" + text + f"\n\n  (refresh every {args.watch}s, Ctrl+C to quit)", flush=True)
        time.sleep(args.watch)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
