-- T091: widen event_factors.method CHECK to include 'close' (rebuild the table).
CREATE TABLE IF NOT EXISTS event_factors (
  symbol TEXT NOT NULL, ex_date TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('demerger','rights')),
  factor REAL, method TEXT NOT NULL CHECK (method IN ('reference','open','none')),
  detail TEXT, computed_at TEXT NOT NULL, PRIMARY KEY (symbol, ex_date, kind)) WITHOUT ROWID;
DROP TABLE IF EXISTS event_factors_new;
CREATE TABLE event_factors_new (
  symbol TEXT NOT NULL, ex_date TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('demerger','rights')),
  factor REAL, method TEXT NOT NULL CHECK (method IN ('reference','open','close','none')),
  detail TEXT, computed_at TEXT NOT NULL, PRIMARY KEY (symbol, ex_date, kind)) WITHOUT ROWID;
INSERT INTO event_factors_new SELECT symbol, ex_date, kind, factor, method, detail, computed_at FROM event_factors;
DROP TABLE event_factors;
ALTER TABLE event_factors_new RENAME TO event_factors;
