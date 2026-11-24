#!/usr/bin/env python3
"""yfinance fundamentals backfill: fetch the remaining stocks batch by batch (same code path as the app job).

Gap-fill fundamentals. The weekly app job stops at 200 stocks per run; this does all of them.

Usage (from the repo root):
    backend/.venv/bin/python scripts/yf_fundamentals_backfill.py [--batch N] [--yes] [--keys SYM ...] [--force]

Ctrl+C stops cleanly; the run is marked cancelled and everything fetched so far is kept.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _backfill import main

if __name__ == "__main__":
    try:
        sys.exit(main("yfinance", "fundamentals", "", "yfinance fundamentals", "stocks"))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
