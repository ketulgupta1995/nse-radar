-- T092: widen price_checks.kind CHECK to include 'adjustment_jump' (rebuild the table, keeping ids).
DROP TABLE IF EXISTS price_checks_new;
CREATE TABLE price_checks_new (
  id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, date TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('mismatch','unexplained_gap','adjustment_jump')),
  primary_source TEXT, other_source TEXT, detail TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','ignored','fixed')),
  created_at TEXT, UNIQUE (symbol, date, kind));
INSERT INTO price_checks_new SELECT id, symbol, date, kind, primary_source, other_source, detail, status, created_at FROM price_checks;
DROP TABLE price_checks;
ALTER TABLE price_checks_new RENAME TO price_checks;
