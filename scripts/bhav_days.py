#!/usr/bin/env python3
"""NSE bhavcopy: re-fetch specific days now, ignoring the 24h retry cooldown.

Example: scripts/bhav_days.py --keys 2010-04-01   (for the full backfill use bhav_backfill.py)

Usage (from the repo root):
    backend/.venv/bin/python scripts/bhav_days.py [--batch N] [--yes] --keys YYYY-MM-DD ... [--force]

Ctrl+C stops cleanly; the run is marked cancelled and everything fetched so far is kept.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _backfill import main

if __name__ == "__main__":
    try:
        sys.exit(main("nse_bhav", "bars", "backfill", "NSE bhavcopy (chosen days)", "days"))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
