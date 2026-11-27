-- 2026-11-27: broker research calls (Buy/Sell rows), see docs/DATA_SOURCES.md
CREATE TABLE IF NOT EXISTS research_reports (
  source TEXT NOT NULL, report_id TEXT NOT NULL, date TEXT NOT NULL, symbol TEXT, stock TEXT NOT NULL,
  author TEXT NOT NULL, type TEXT NOT NULL CHECK (type IN ('Buy','Sell')), ltp REAL, target REAL,
  reco_price REAL, change_pct REAL, upside_pct REAL, url TEXT, first_seen_at TEXT NOT NULL,
  fetched_at TEXT NOT NULL, PRIMARY KEY (source, report_id));
CREATE INDEX IF NOT EXISTS research_reports_date ON research_reports(date);
