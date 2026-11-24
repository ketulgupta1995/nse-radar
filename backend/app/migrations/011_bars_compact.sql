-- skip-if-column: bars.source_id
-- 2026-11-23: store bars compactly (SPEC §4, app/bardb.py): source as an id from bar_sources, date as
-- INTEGER YYYYMMDD. ~25% smaller database. Columns are renamed (source_id, day) so any old query fails loudly.
CREATE TABLE IF NOT EXISTS bar_sources (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
INSERT OR IGNORE INTO bar_sources(name) SELECT DISTINCT source FROM bars ORDER BY source;
CREATE TABLE bars_new (
  source_id INTEGER NOT NULL, symbol TEXT NOT NULL, day INTEGER NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL, value REAL, trades INTEGER,
  PRIMARY KEY (source_id, symbol, day)) WITHOUT ROWID;
INSERT INTO bars_new
  SELECT s.id, b.symbol, CAST(substr(b.date, 1, 4) || substr(b.date, 6, 2) || substr(b.date, 9, 2) AS INTEGER),
         b.open, b.high, b.low, b.close, b.volume, b.value, b.trades
  FROM bars b JOIN bar_sources s ON s.name = b.source
  ORDER BY s.id, b.symbol, b.date;
DROP TABLE bars;
ALTER TABLE bars_new RENAME TO bars;
CREATE INDEX IF NOT EXISTS bars_day_symbol ON bars(day, symbol)
