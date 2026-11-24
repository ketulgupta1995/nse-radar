-- skip-if-column: bars.sym_id
-- 2026-11-23: shrink bars further (SPEC §4, app/bardb.py): the symbol as an id from bar_symbols, prices as
-- paise (an INTEGER when whole, else the exact float x100), volume and value as integers, and no
-- bars_day_symbol index (every lookup is a primary-key seek). NSE prices are whole paise; adjusted sources
-- keep full precision. Price columns are renamed (*_p) so old queries fail loudly.
CREATE TABLE IF NOT EXISTS bar_symbols (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL UNIQUE);
INSERT OR IGNORE INTO bar_symbols(symbol) SELECT DISTINCT symbol FROM bars ORDER BY symbol;
CREATE TABLE bars_new (
  source_id INTEGER NOT NULL, sym_id INTEGER NOT NULL, day INTEGER NOT NULL,
  open_p INTEGER, high_p INTEGER, low_p INTEGER, close_p INTEGER, volume INTEGER, value INTEGER, trades INTEGER,
  PRIMARY KEY (source_id, sym_id, day)) WITHOUT ROWID;
INSERT INTO bars_new
  SELECT b.source_id, y.id, b.day,
         CASE WHEN ROUND(b.open * 100) / 100.0 = b.open THEN CAST(ROUND(b.open * 100) AS INTEGER) ELSE b.open * 100 END,
         CASE WHEN ROUND(b.high * 100) / 100.0 = b.high THEN CAST(ROUND(b.high * 100) AS INTEGER) ELSE b.high * 100 END,
         CASE WHEN ROUND(b.low * 100) / 100.0 = b.low THEN CAST(ROUND(b.low * 100) AS INTEGER) ELSE b.low * 100 END,
         CASE WHEN ROUND(b.close * 100) / 100.0 = b.close THEN CAST(ROUND(b.close * 100) AS INTEGER) ELSE b.close * 100 END,
         CAST(ROUND(b.volume) AS INTEGER), CAST(ROUND(b.value) AS INTEGER), b.trades
  FROM bars b JOIN bar_symbols y ON y.symbol = b.symbol
  ORDER BY b.source_id, y.id, b.day;
DROP TABLE bars;
ALTER TABLE bars_new RENAME TO bars
