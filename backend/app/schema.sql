-- sources
CREATE TABLE IF NOT EXISTS source_state (
  source TEXT PRIMARY KEY, enabled INTEGER NOT NULL, paused_reason TEXT,
  last_ok_at TEXT, last_error_at TEXT, last_error TEXT);
CREATE TABLE IF NOT EXISTS source_fetch (
  source TEXT NOT NULL, capability TEXT NOT NULL, key TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','not_found','failed')),
  fetched_at TEXT NOT NULL, rows INTEGER, error TEXT,
  PRIMARY KEY (source, capability, key)) WITHOUT ROWID;

-- universe & prices
CREATE TABLE IF NOT EXISTS symbols (
  symbol TEXT PRIMARY KEY, name TEXT, industry TEXT, isin TEXT,
  in_universe INTEGER NOT NULL DEFAULT 0, updated_at TEXT);
CREATE TABLE IF NOT EXISTS bar_sources (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS bar_symbols (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS bars (                     -- compact: see app/bardb.py (migrations 011/012)
  source_id INTEGER NOT NULL, sym_id INTEGER NOT NULL, day INTEGER NOT NULL,   -- day = YYYYMMDD
  open_p INTEGER, high_p INTEGER, low_p INTEGER, close_p INTEGER,              -- paise
  volume INTEGER, value INTEGER, trades INTEGER,                               -- value in rupees
  PRIMARY KEY (source_id, sym_id, day)) WITHOUT ROWID;                         -- no other index (bardb.LAST_DAY_SQL)
CREATE TABLE IF NOT EXISTS corp_actions (
  source TEXT NOT NULL, symbol TEXT NOT NULL, ex_date TEXT NOT NULL, subject TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('split','bonus','demerger','rights','other','unparsed')), factor REAL,
  PRIMARY KEY (source, symbol, ex_date, subject));
CREATE TABLE IF NOT EXISTS instruments (              -- what each traded symbol is, from bhavcopy (T087a)
  symbol TEXT PRIMARY KEY, isin TEXT, series TEXT,       -- latest seen; isin 'INF…' = fund unit, series RR/IV = REIT/InvIT
  last_date TEXT NOT NULL, source TEXT NOT NULL);         -- upserted by save_bars only when the new date >= last_date
CREATE TABLE IF NOT EXISTS events (                   -- board meetings from the event calendar (T095)
  source TEXT NOT NULL, symbol TEXT NOT NULL, date TEXT NOT NULL, purpose TEXT NOT NULL, description TEXT,
  fetched_at TEXT NOT NULL, PRIMARY KEY (source, symbol, date, purpose));
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
CREATE TABLE IF NOT EXISTS event_factors (            -- derived demerger/rights factors (§7.2a, T084)
  symbol TEXT NOT NULL, ex_date TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('demerger','rights')),
  factor REAL, method TEXT NOT NULL CHECK (method IN ('reference','open','close','none')),
  detail TEXT, computed_at TEXT NOT NULL, PRIMARY KEY (symbol, ex_date, kind)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS index_bars (
  source TEXT NOT NULL, index_name TEXT NOT NULL, date TEXT NOT NULL, close REAL NOT NULL,
  PRIMARY KEY (source, index_name, date)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS price_checks (
  id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, date TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('mismatch','unexplained_gap','adjustment_jump')),
  primary_source TEXT, other_source TEXT, detail TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','ignored','fixed')),
  created_at TEXT, UNIQUE (symbol, date, kind));
CREATE TABLE IF NOT EXISTS manual_adjustments (
  symbol TEXT NOT NULL, ex_date TEXT NOT NULL, factor REAL NOT NULL, note TEXT, PRIMARY KEY (symbol, ex_date));

-- fundamentals
CREATE TABLE IF NOT EXISTS fund_snapshots (
  source TEXT NOT NULL, symbol TEXT NOT NULL, fetched_at TEXT NOT NULL,
  fields TEXT NOT NULL, detail TEXT NOT NULL, PRIMARY KEY (source, symbol));
CREATE TABLE IF NOT EXISTS quarters (
  source TEXT NOT NULL, symbol TEXT NOT NULL, period_end TEXT NOT NULL, consolidated INTEGER NOT NULL,
  period_start TEXT, audited INTEGER, filing_date TEXT, url TEXT,
  revenue REAL, other_income REAL, total_expenses REAL, pbt REAL, net_profit REAL, eps REAL, parse_error TEXT,
  PRIMARY KEY (source, symbol, period_end, consolidated));
CREATE TABLE IF NOT EXISTS fundamentals (          -- merged snapshot (§9.4)
  symbol TEXT PRIMARY KEY, updated_at TEXT NOT NULL, data TEXT NOT NULL, sources TEXT NOT NULL);

-- news
CREATE TABLE IF NOT EXISTS announcements (
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, symbol TEXT NOT NULL, ts TEXT NOT NULL, category TEXT NOT NULL,
  headline TEXT NOT NULL, body TEXT, url TEXT, UNIQUE (symbol, ts, headline));
CREATE TABLE IF NOT EXISTS news_items (
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, feed TEXT NOT NULL, ts TEXT NOT NULL,
  title TEXT NOT NULL, url TEXT NOT NULL UNIQUE, summary TEXT);
CREATE TABLE IF NOT EXISTS news_symbols (
  news_id INTEGER NOT NULL REFERENCES news_items(id) ON DELETE CASCADE, symbol TEXT NOT NULL,
  PRIMARY KEY (news_id, symbol));

-- owner data
CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, added_at TEXT NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checklists (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('entry','exit')), symbol TEXT NOT NULL,
  answers TEXT NOT NULL, ai_review TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, qty INTEGER NOT NULL CHECK (qty > 0),
  entry_date TEXT NOT NULL, entry_price REAL NOT NULL, stop REAL, target REAL, time_stop_date TEXT,
  entry_checklist_id INTEGER REFERENCES checklists(id),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  exit_date TEXT, exit_price REAL, exit_reason TEXT, exit_checklist_id INTEGER REFERENCES checklists(id),
  source_screen_id INTEGER, created_at TEXT NOT NULL);

-- screens, indicators, backtests
CREATE TABLE IF NOT EXISTS screens (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT, rule TEXT NOT NULL,
  is_preset INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL DEFAULT 'user' CHECK (created_by IN ('preset','user','ai')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS screen_results (
  screen_id INTEGER NOT NULL REFERENCES screens(id) ON DELETE CASCADE, symbol TEXT NOT NULL, as_of TEXT NOT NULL,
  values_json TEXT NOT NULL, first_seen TEXT NOT NULL, PRIMARY KEY (screen_id, symbol));
CREATE TABLE IF NOT EXISTS custom_indicators (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, params_schema TEXT NOT NULL, explain TEXT NOT NULL,
  code TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  created_at TEXT NOT NULL, approved_at TEXT);
CREATE TABLE IF NOT EXISTS backtests (
  id INTEGER PRIMARY KEY, name TEXT, config TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed','cancelled')),
  run_id INTEGER, metrics TEXT, equity TEXT, trades TEXT, warnings TEXT, created_at TEXT NOT NULL, finished_at TEXT,
  kind TEXT NOT NULL DEFAULT 'explore' CHECK (kind IN ('explore','final','legacy')),   -- T113, §12.6
  parent_id INTEGER, fingerprint TEXT);                                               -- T113: final -> its explore run

-- jobs
CREATE TABLE IF NOT EXISTS job_schedules (
  job TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('interval','daily','weekly','manual')),
  interval_min INTEGER, at_time TEXT, weekday INTEGER, weekdays_only INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1, next_run_at TEXT, last_run_id INTEGER);
CREATE TABLE IF NOT EXISTS job_runs (
  id INTEGER PRIMARY KEY, job TEXT NOT NULL, params TEXT NOT NULL DEFAULT '{}',
  trigger TEXT NOT NULL CHECK (trigger IN ('schedule','manual','retry','startup','system')),
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed','cancelled','interrupted')),
  queued_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  total INTEGER, done INTEGER NOT NULL DEFAULT 0, ok INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0, message TEXT, stop_requested INTEGER NOT NULL DEFAULT 0, retry_of INTEGER);
CREATE INDEX IF NOT EXISTS job_runs_job ON job_runs(job, id DESC);
CREATE TABLE IF NOT EXISTS job_items (
  run_id INTEGER NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE, key TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','skipped','failed')), detail TEXT, at TEXT NOT NULL,
  PRIMARY KEY (run_id, key));
CREATE TABLE IF NOT EXISTS job_logs (
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE,
  at TEXT NOT NULL, level TEXT NOT NULL CHECK (level IN ('info','warn','error')), msg TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS job_logs_run ON job_logs(run_id, id);

-- alerts & ai
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, symbol TEXT, message TEXT NOT NULL, link TEXT,
  severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warn','critical')),
  dedupe_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, seen_at TEXT);
CREATE TABLE IF NOT EXISTS ai_requests (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, symbol TEXT, payload TEXT, prompt TEXT NOT NULL, response TEXT,
  result TEXT,                                  -- JSON from the task's postprocess (§11)
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed','cancelled')),
  provider TEXT, model TEXT, run_id INTEGER, duration_s REAL, error TEXT, created_at TEXT NOT NULL);

-- signal log (SPEC §16.1)
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL CHECK (source IN ('screen','shortlist')),
  screen_id INTEGER NOT NULL DEFAULT 0,          -- 0 for shortlist rows; NO foreign key (history outlives screens)
  screen_name TEXT,                              -- copied at log time; NULL for shortlist rows
  symbol TEXT NOT NULL,
  as_of TEXT NOT NULL,                           -- the bar date the signal fired on (YYYY-MM-DD)
  rank INTEGER,                                  -- shortlist rank 1..10; NULL for screen rows
  score REAL, components TEXT,                   -- score and {component: value} JSON at log time (NULL if unscored)
  reasons TEXT NOT NULL DEFAULT '[]',            -- JSON list of strings
  planned_entry REAL NOT NULL,                   -- close on as_of (adjusted as of log time; audit only)
  atr14 REAL NOT NULL,                           -- ATR(14) on as_of, same basis as planned_entry
  planned_stop REAL NOT NULL, planned_target REAL NOT NULL,
  exit_config TEXT NOT NULL,                     -- JSON, frozen: {"exits":[...], "notional_inr":100000}
  rule_hash TEXT,                                -- sha1 of score.canonical(rule) for screen rows; NULL for shortlist
  score_weights TEXT NOT NULL,                   -- JSON of the score_weights setting at log time
  app_version TEXT NOT NULL,                     -- `git rev-parse --short HEAD` of the repo, or "unknown"
  bars_as_of TEXT NOT NULL,                      -- frames.last_trading_date() at log time
  created_at TEXT NOT NULL,
  UNIQUE (source, screen_id, symbol, as_of));
CREATE INDEX IF NOT EXISTS signals_as_of ON signals(as_of);
CREATE TRIGGER IF NOT EXISTS signals_no_update BEFORE UPDATE ON signals
  BEGIN SELECT RAISE(ABORT, 'signals is append-only'); END;
CREATE TRIGGER IF NOT EXISTS signals_no_delete BEFORE DELETE ON signals
  BEGIN SELECT RAISE(ABORT, 'signals is append-only'); END;

CREATE TABLE IF NOT EXISTS signal_outcomes (     -- 1:1 with signals; freely recomputed
  signal_id INTEGER PRIMARY KEY REFERENCES signals(id),
  status TEXT NOT NULL CHECK (status IN ('pending','open','closed','no_data')),
  entry_date TEXT, entry_fill REAL, gap_pct REAL,          -- gap_pct = (next open / as_of close - 1) * 100
  stop_level REAL, target_level REAL,                       -- re-anchored to entry_fill
  exit_date TEXT, exit_fill REAL, exit_reason TEXT,         -- reason as the backtester: stop|target|time stop|exit rule
  days_held INTEGER,
  return_pct REAL,                                          -- net of costs on notional_inr; unrealised for 'open'
  r_multiple REAL,                                          -- (exit_or_last - entry_fill) / (entry_fill - stop_level), price-only
  mfe_r REAL, mae_r REAL,                                   -- best high / worst low since entry, in R
  stock_cc_pct REAL, nifty_cc_pct REAL, excess_pct REAL,    -- close-basis: entry_date close -> exit_date (or last) close
  last_bar TEXT, updated_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS signal_days (         -- coverage: one row per bar date the logger ran for
  as_of TEXT PRIMARY KEY, logged INTEGER NOT NULL, run_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS symbol_changes (          -- ticker renames (T077); source 'manual' = owner-added
  source TEXT NOT NULL, old_symbol TEXT NOT NULL, new_symbol TEXT NOT NULL, effective_date TEXT NOT NULL,
  name TEXT, note TEXT, PRIMARY KEY (source, old_symbol, new_symbol, effective_date)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS symbol_changes_new ON symbol_changes(new_symbol);

CREATE TABLE IF NOT EXISTS source_secrets (          -- credentials in vercel/actions mode (N021, SPEC §3.6);
  source TEXT, key TEXT, value TEXT,                 -- locally they stay in data/secrets.json
  PRIMARY KEY (source, key));
