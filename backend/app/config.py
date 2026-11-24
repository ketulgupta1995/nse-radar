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
USER_AGENT = "nse-radar/0.1 (personal research; single user; low rate)"

# Runtime modes (SPEC §17.2)
RUNTIME = os.environ.get("STOCK_RUNTIME", "local")  # "local" | "vercel" | "actions"
TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")  # libsql://<db>-<org>.turso.io; empty -> SQLite file
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
REPLICA_PATH = os.environ.get("STOCK_REPLICA_PATH", "")  # actions only: embedded replica file
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")  # "owner/nse-radar" (Vercel: to dispatch workflows)
