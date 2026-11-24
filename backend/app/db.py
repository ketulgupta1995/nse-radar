import json
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app import config, timeutil

SCHEMA_VERSION = 12
MIGRATIONS_DIR = Path(__file__).with_name("migrations")
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCREEN_PRESETS_PATH = Path(__file__).with_name("presets") / "screens.json"
RETIRED_SCREEN_PRESETS = (
    "Uptrend leaders", "Pullback in strong trend", "Trend riders", "Smooth momentum leaders"
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "capital_inr": 500000,
    "risk_per_trade_pct": 1.0,
    "default_time_stop_weeks": 8,
    "atr_stop_multiple": 2.0,
    "signal_target_atr_multiple": 4.0,
    "position_exit_sma": 100,
    "trail_atr_multiple": 5.0,
    "source_priority": {
        "universe": ["nse_archives"],
        "bars": ["nse_bhav", "yfinance"],
        "actions": ["nse_api", "yfinance"],
        "index": ["nse_archives", "yfinance"],
        "fundamentals": ["screener", "yfinance"],
        "quarters": ["nse_api"],
        "announcements": ["nse_api"],
        "news": ["rss"],
    },
    "fundamentals_field_priority": {
        "sales_growth_yoy_pct": ["quarters", "screener", "yfinance"],
        "profit_growth_yoy_pct": ["quarters", "screener", "yfinance"],
        "profit_positive_4q": ["quarters", "screener"],
    },
    "holdout_start": "2022-01-01",
    "backtest_workers": 3,
    "ai_provider": "claude_cli",
    "ai_model": "sonnet",
    "ai_timeout_s": 240,
    "score_weights": {"rs": 30, "trend": 25, "fundamentals": 30, "backtest": 15},
    "rss_feeds": [
        {
            "name": "ET Markets",
            "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        },
        {"name": "Business Standard", "url": "https://www.business-standard.com/rss/markets-106.rss"},
    ],
    "jobs_paused": False,
    "last_visit_at": None,
    "cost_model": {
        "brokerage_pct": 0.03,
        "brokerage_cap_inr": 20,
        "stt_pct": 0.1,
        "exchange_pct": 0.00297,
        "sebi_pct": 0.0001,
        "stamp_buy_pct": 0.015,
        "gst_pct": 18,
        "dp_charge_inr": 15.93,
        "slippage_pct": 0.10,
    },
}


def connect() -> sqlite3.Connection:
    if config.TURSO_URL:  # Turso remote or embedded replica (SPEC §17.2); same sqlite3 surface
        from app import dbdriver

        return dbdriver.connect_turso()  # type: ignore[return-value]
    conn = sqlite3.connect(config.DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=NORMAL")  # safe with WAL: a power cut can lose only the last commit
    conn.execute("PRAGMA cache_size=-32768")  # 32 MB page cache per connection
    conn.execute("PRAGMA journal_size_limit=67108864")  # shrink the -wal file back to 64 MB after big writes
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = connect()
    stack = _pending_stack()
    stack.append([])
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
    finally:
        conn.close()
        callbacks = stack.pop()
    for fn in callbacks:  # after COMMIT/ROLLBACK, so other connections see the final state
        fn()


_local = threading.local()


def _pending_stack() -> list[list]:
    if not hasattr(_local, "stack"):
        _local.stack = []
    return _local.stack


def after_commit(fn) -> None:
    """Run `fn` once the current thread's open `tx()` ends (now, if none is open).

    For cache clears: clearing before COMMIT lets another thread re-read the old rows and cache them.
    """
    stack = _pending_stack()
    if stack:
        stack[-1].append(fn)
    else:
        fn()


@contextmanager
def read() -> Iterator[sqlite3.Connection]:
    """Read-only work: no BEGIN IMMEDIATE, so slow queries never block writers (WAL)."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def _already_applied(conn: sqlite3.Connection, sql: str) -> bool:
    """A migration may start with `-- skip-if-column: table.column` when re-running it would fail."""
    m = re.search(r"^-- skip-if-column: (\w+)\.(\w+)$", sql, re.M)
    return bool(m) and any(r[1] == m[2] for r in conn.execute(f"PRAGMA table_info({m[1]})"))


def _migrate(conn: sqlite3.Connection, version: int) -> None:
    """Run migrations/NNN_*.sql with NNN > version, each in its own transaction (SPEC §4)."""
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        if int(path.name[:3]) <= version or _already_applied(conn, path.read_text()):
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in path.read_text().split(";\n"):
                if not stmt.strip():
                    continue
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e):  # column already there: safe to skip
                        raise
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def sync() -> None:
    """Embedded replica: pull the primary's latest writes. Otherwise a no-op."""
    if not (config.TURSO_URL and config.REPLICA_PATH):
        return
    conn = connect()
    try:
        conn.sync()  # type: ignore[attr-defined]
    finally:
        conn.close()


def schema_status() -> str:
    """Returns "ok", or "update pending" when the DB's user_version is behind SCHEMA_VERSION (§17.2)."""
    with read() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    return "ok" if version >= SCHEMA_VERSION else "update pending"


def init_db() -> None:
    if config.RUNTIME == "vercel":
        raise RuntimeError("migrations run in the drain, not on Vercel")
    for d in (config.DATA_DIR, config.RAW_DIR, config.DATA_DIR / "backups"):
        d.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            has_actions = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='corp_actions'"
            ).fetchone()
            if has_actions:
                _migrate(conn, version)
            conn.executescript(SCHEMA_PATH.read_text())  # idempotent DDL; runs outside tx()
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    finally:
        conn.close()
    with tx() as conn:
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, json.dumps(value))
            )
        now = timeutil.now_iso()
        for p in json.loads(SCREEN_PRESETS_PATH.read_text()):
            conn.execute(
                "INSERT OR IGNORE INTO screens(name, description, rule, is_preset, created_by, "
                "created_at, updated_at) VALUES (?,?,?,1,'preset',?,?)",
                (p["name"], p.get("description"), json.dumps(p["rule"]), now, now),
            )
        # Presets dropped from screens.json (grid search run1, 2026-11-14). Seeding never deletes and the
        # API refuses to delete presets, so remove them here. screen_results cascade; the log keeps history.
        conn.executemany(
            "DELETE FROM screens WHERE is_preset=1 AND name=?", [(n,) for n in RETIRED_SCREEN_PRESETS]
        )


def _run(conn: sqlite3.Connection | None, fn):
    if conn is not None:
        return fn(conn)
    with tx() as c:
        return fn(c)


def get_setting(key: str, conn: sqlite3.Connection | None = None) -> Any:
    def go(c: sqlite3.Connection) -> Any:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row["value"])

    return _run(conn, go)


def set_setting(key: str, value: Any, conn: sqlite3.Connection | None = None) -> None:
    _run(
        conn,
        lambda c: c.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        ),
    )


def insert_alert(
    kind: str,
    message: str,
    *,
    dedupe_key: str,
    symbol: str | None = None,
    link: str | None = None,
    severity: str = "info",
    conn: sqlite3.Connection | None = None,
) -> bool:
    def go(c: sqlite3.Connection) -> bool:
        cur = c.execute(
            "INSERT OR IGNORE INTO alerts(kind, symbol, message, link, severity, dedupe_key, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, symbol, message, link, severity, dedupe_key, timeutil.now_iso()),
        )
        return cur.rowcount == 1

    return _run(conn, go)
