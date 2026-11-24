import os
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]  # stock-tools/
DATA_DIR = Path(os.environ.get("STOCK_DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "stock.db"
SECRETS_PATH = DATA_DIR / "secrets.json"
RAW_DIR = DATA_DIR / "raw"
TZ = ZoneInfo("Asia/Kolkata")
HISTORY_START = date(2010, 1, 1)
USER_AGENT = "stock-tools/0.1 (personal research; single user; low rate)"
