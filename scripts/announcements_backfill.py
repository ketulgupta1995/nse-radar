#!/usr/bin/env python3
"""NSE announcements (all stocks) backfill: fetch the remaining stocks batch by batch (same code path as the app job).

First fetch per stock covers the last 3 days; later ones catch up since the last OK fetch (max 30 days).

Usage (from the repo root):
    backend/.venv/bin/python scripts/announcements_backfill.py [--batch N] [--yes] [--keys SYM ...] [--force]

Ctrl+C stops cleanly; the run is marked cancelled and everything fetched so far is kept.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _backfill import main

if __name__ == "__main__":
    try:
        sys.exit(main("nse_api", "announcements", "all", "NSE announcements (all stocks)", "stocks"))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
