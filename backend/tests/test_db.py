import re
from pathlib import Path

from app import db
from app.sources import store

TABLES = {
    "source_state", "source_fetch", "symbols", "bar_sources", "bar_symbols", "bars", "corp_actions",
    "index_bars", "price_checks",
    "manual_adjustments", "fund_snapshots", "quarters", "fundamentals", "announcements", "news_items",
    "news_symbols", "watchlist", "settings", "checklists", "positions", "screens", "screen_results",
    "custom_indicators", "backtests", "job_schedules", "job_runs", "job_items", "job_logs", "alerts",
    "ai_requests", "signals", "signal_outcomes", "signal_days",
    "symbol_changes", "event_factors", "instruments", "events",
}


def test_all_tables_exist():
    db.init_db()
    with db.tx() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names
    ddl = (Path(db.__file__).with_name("schema.sql")).read_text()
    assert set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", ddl)) == TABLES


def test_fresh_db_is_current_version():
    db.init_db()
    conn = db.connect()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 12
    conn.close()


OLD_CORP_ACTIONS = """CREATE TABLE corp_actions (
  source TEXT NOT NULL, symbol TEXT NOT NULL, ex_date TEXT NOT NULL, subject TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('split','bonus','other','unparsed')), factor REAL,
  PRIMARY KEY (source, symbol, ex_date, subject))"""


def test_version_3_db_migrates_corp_actions():
    db.init_db()
    conn = db.connect()
    conn.execute("DROP TABLE corp_actions")
    conn.execute("DROP TABLE event_factors")
    conn.execute(OLD_CORP_ACTIONS)
    rows = [
        ("nse_api", "AAA", "2026-01-01", "Bonus 1:1", "bonus", 0.5),
        ("nse_api", "BBB", "2026-02-01", "Dividend", "other", None),
        ("yfinance", "AAA", "2026-03-01", "Split", "split", 0.2),
    ]
    conn.executemany("INSERT INTO corp_actions VALUES (?,?,?,?,?,?)", rows)
    conn.execute("PRAGMA user_version=3")
    conn.close()
    db.init_db()
    with db.tx() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        got = c.execute("SELECT * FROM corp_actions ORDER BY ex_date").fetchall()
        assert [tuple(r) for r in got] == rows
        c.execute("INSERT INTO corp_actions VALUES ('nse_api','CCC','2026-04-01','Demerger','demerger',NULL)")
        assert c.execute("SELECT COUNT(*) FROM event_factors").fetchone()[0] == 0
    db.init_db()  # second run changes nothing
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM corp_actions").fetchone()[0] == 4


def test_version_4_db_gains_instruments():
    db.init_db()
    conn = db.connect()
    conn.execute("DROP TABLE instruments")
    conn.execute("PRAGMA user_version=4")
    conn.close()
    db.init_db()
    with db.tx() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "instruments" in names
        assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_version_5_db_widens_event_factors():
    db.init_db()
    conn = db.connect()
    conn.execute("DROP TABLE event_factors")
    conn.execute(
        "CREATE TABLE event_factors (symbol TEXT NOT NULL, ex_date TEXT NOT NULL, "
        "kind TEXT NOT NULL CHECK (kind IN ('demerger','rights')), factor REAL, "
        "method TEXT NOT NULL CHECK (method IN ('reference','open','none')), "
        "detail TEXT, computed_at TEXT NOT NULL, PRIMARY KEY (symbol, ex_date, kind)) WITHOUT ROWID"
    )
    conn.execute("INSERT INTO event_factors VALUES ('AAA','2026-01-01','demerger',0.5,'open','{}','t')")
    conn.execute("PRAGMA user_version=5")
    conn.close()
    db.init_db()
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM event_factors").fetchone()[0] == 1
        c.execute("INSERT INTO event_factors VALUES ('BBB','2026-01-01','demerger',0.2,'close','{}','t')")
        assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_version_6_db_migrates_price_checks_keeping_ids():
    db.init_db()
    conn = db.connect()
    conn.execute("DROP TABLE price_checks")
    conn.execute(
        "CREATE TABLE price_checks (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, date TEXT NOT NULL, "
        "kind TEXT NOT NULL CHECK (kind IN ('mismatch','unexplained_gap')), primary_source TEXT, "
        "other_source TEXT, detail TEXT, status TEXT NOT NULL DEFAULT 'open' "
        "CHECK (status IN ('open','ignored','fixed')), created_at TEXT, UNIQUE (symbol, date, kind))"
    )
    conn.execute(
        "INSERT INTO price_checks VALUES (42,'AAA','2026-01-01','mismatch','raw','adj','{}','open','t')"
    )
    conn.execute("PRAGMA user_version=6")
    conn.close()
    db.init_db()
    with db.tx() as c:
        row = c.execute("SELECT id, symbol, status FROM price_checks").fetchone()
        assert (row["id"], row["symbol"], row["status"]) == (42, "AAA", "open")
        c.execute(
            "INSERT INTO price_checks(symbol, date, kind) VALUES ('BBB','2026-01-01','adjustment_jump')"
        )
        assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_version_2_db_gains_symbol_changes():
    db.init_db()
    conn = db.connect()
    conn.execute("DROP TABLE symbol_changes")
    conn.execute("PRAGMA user_version=2")
    conn.close()
    db.init_db()
    with db.tx() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "symbol_changes" in names
        assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_idempotent_and_settings_survive():
    db.init_db()
    db.set_setting("capital_inr", 123)
    db.init_db()
    assert db.get_setting("capital_inr") == 123
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == len(db.DEFAULT_SETTINGS)


def test_settings_roundtrip():
    db.init_db()
    assert db.get_setting("capital_inr") == 500000
    db.set_setting("score_weights", {"rs": 1})
    assert db.get_setting("score_weights") == {"rs": 1}


def test_unknown_setting():
    db.init_db()
    try:
        db.get_setting("nope")
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_insert_alert_dedupes():
    db.init_db()
    assert db.insert_alert("k", "m", dedupe_key="a") is True
    assert db.insert_alert("k", "m", dedupe_key="a") is False


def test_pragmas():
    db.init_db()
    conn = db.connect()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_version_8_db_marks_existing_backtests_legacy():
    db.init_db()
    conn = db.connect()
    conn.execute("DROP TABLE backtests")
    conn.execute(
        "CREATE TABLE backtests (id INTEGER PRIMARY KEY, name TEXT, config TEXT NOT NULL, "
        "status TEXT NOT NULL, run_id INTEGER, metrics TEXT, equity TEXT, trades TEXT, warnings TEXT, "
        "created_at TEXT NOT NULL, finished_at TEXT)"
    )
    conn.execute("INSERT INTO backtests(config,status,created_at) VALUES ('{}','done','x'),('{}','done','y')")
    conn.execute("PRAGMA user_version=8")
    conn.close()
    db.init_db()
    with db.tx() as c:
        assert [r["kind"] for r in c.execute("SELECT kind FROM backtests ORDER BY id")] == ["legacy"] * 2
        c.execute("INSERT INTO backtests(config,status,kind,created_at) VALUES ('{}','queued','explore','z')")
        assert c.execute("SELECT kind FROM backtests WHERE id=3").fetchone()[0] == "explore"


def test_lifespan_inits_db(client):
    assert client.get("/api/health").status_code == 200
    assert db.get_setting("capital_inr") == 500000


def test_version_9_db_drops_bars_symbol_date():
    db.init_db()
    conn = db.connect()
    conn.execute("CREATE INDEX bars_symbol_date ON bars(sym_id, day)")
    conn.execute("PRAGMA user_version=9")
    conn.close()
    db.init_db()
    with db.read() as c:
        q = "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='bars'"
        idx = {r[0] for r in c.execute(q)}
        assert "bars_symbol_date" not in idx and "bars_day_symbol" not in idx
        assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


READ_BACK = (
    "SELECT s.name, y.symbol, b.day, b.open_p / 100.0, b.high_p / 100.0, b.low_p / 100.0, b.close_p / 100.0, "
    "b.volume, b.value, b.trades FROM bars b JOIN bar_sources s ON s.id = b.source_id "
    "JOIN bar_symbols y ON y.id = b.sym_id ORDER BY s.name, y.symbol, b.day"
)
V11_BARS = """CREATE TABLE bars (
  source_id INTEGER NOT NULL, symbol TEXT NOT NULL, day INTEGER NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL, value REAL, trades INTEGER,
  PRIMARY KEY (source_id, symbol, day)) WITHOUT ROWID"""

OLD_BARS = """CREATE TABLE bars (
  source TEXT NOT NULL, symbol TEXT NOT NULL, date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL, value REAL, trades INTEGER,
  PRIMARY KEY (source, symbol, date)) WITHOUT ROWID"""


def test_version_10_db_compacts_bars_keeping_every_row():
    db.init_db()
    conn = db.connect()
    conn.execute("DROP TABLE bars")
    conn.execute("DELETE FROM bar_sources")
    conn.execute(OLD_BARS)
    conn.execute("CREATE INDEX bars_date_symbol ON bars(date, symbol)")
    old = [
        ("nse_bhav", "AAA", "2026-11-12", 1.0, 2.0, 0.5, 1.5, 100.0, 150.0, 7),
        ("nse_bhav", "AAA", "2026-11-13", 1.5, 2.5, 1.0, 2.0, None, None, None),
        ("yfinance", "AAA", "2010-01-04", 3.0, 3.0, 3.0, 3.0, 9.0, None, None),
    ]
    conn.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?)", old)
    conn.execute("PRAGMA user_version=10")
    conn.commit()
    conn.close()
    db.init_db()
    with db.read() as c:
        assert [r[1] for r in c.execute("PRAGMA table_info(bars)")][:3] == ["source_id", "sym_id", "day"]
        got = c.execute(READ_BACK).fetchall()
        q = "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='bars'"
        idx = {r[0] for r in c.execute(q)}
    assert [tuple(r) for r in got] == [(s, sym, int(d.replace("-", "")), *rest) for s, sym, d, *rest in old]
    assert not idx
    assert store.last_bar_date("nse_bhav", "AAA", db.connect()) == "2026-11-13"


def test_version_11_db_moves_to_paise_and_symbol_ids_exactly():
    db.init_db()
    conn = db.connect()
    conn.execute("DROP TABLE bars")
    conn.execute("DELETE FROM bar_sources")
    conn.executemany("INSERT INTO bar_sources(id, name) VALUES (?,?)", [(1, "nse_bhav"), (2, "yfinance")])
    conn.execute(V11_BARS)
    conn.execute("CREATE INDEX bars_day_symbol ON bars(day, symbol)")
    old = [  # NSE prices are whole paise; yfinance's adjusted prices aren't and must survive exactly
        (1, "BBB", 20261113, 46.55, 47.9, 45.7, 0.05, 36282.0, 1719201.35, 12),
        (1, "BBB", 20261114, None, None, None, 2.0, None, None, None),
        (2, "AAA", 20100104, 302.5, 317.625, 0.4000000059604645, 1.4366660118103027, 7109860.0, None, None),
    ]
    conn.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?)", old)
    conn.execute("PRAGMA user_version=11")
    conn.commit()
    conn.close()
    db.init_db()
    with db.read() as c:
        got = [tuple(r) for r in c.execute(READ_BACK)]
        kinds = c.execute("SELECT typeof(open_p), typeof(close_p), typeof(volume), typeof(value) FROM bars "
                          "WHERE source_id=1 AND day=20261113").fetchone()
        q = "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='bars'"
        idx = {r[0] for r in c.execute(q)}
    assert got == [
        ("nse_bhav", "BBB", 20261113, 46.55, 47.9, 45.7, 0.05, 36282, 1719201, 12),
        ("nse_bhav", "BBB", 20261114, None, None, None, 2.0, None, None, None),
        ("yfinance", "AAA", 20100104, 302.5, 317.625, 0.4000000059604645, 1.4366660118103027, 7109860,
         None, None),
    ]
    assert tuple(kinds) == ("integer", "integer", "integer", "integer")
    assert not idx
    assert store.last_bar_date("yfinance", "AAA", db.connect()) == "2010-01-04"
