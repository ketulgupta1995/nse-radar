#!/usr/bin/env python3
"""NSE quarterly results backfill: fetch the remaining stocks batch by batch (same code path as the app job).

Only new quarters are parsed per stock. Re-fetches a stock only after 7 days.

Usage (from the repo root):
    backend/.venv/bin/python scripts/quarters_backfill.py [--batch N] [--yes] [--keys SYM ...] [--force]

Ctrl+C stops cleanly; the run is marked cancelled and everything fetched so far is kept.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _backfill import main

if __name__ == "__main__":
    try:
        sys.exit(main("nse_api", "quarters", "", "NSE quarterly results", "stocks"))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
