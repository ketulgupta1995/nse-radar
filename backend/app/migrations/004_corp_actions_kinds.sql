-- T083: widen corp_actions.kind CHECK (SQLite cannot alter a CHECK): rebuild the table.
DROP TABLE IF EXISTS corp_actions_new;
CREATE TABLE corp_actions_new (
  source TEXT NOT NULL, symbol TEXT NOT NULL, ex_date TEXT NOT NULL, subject TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('split','bonus','demerger','rights','other','unparsed')), factor REAL,
  PRIMARY KEY (source, symbol, ex_date, subject));
INSERT INTO corp_actions_new SELECT source, symbol, ex_date, subject, kind, factor FROM corp_actions;
DROP TABLE corp_actions;
ALTER TABLE corp_actions_new RENAME TO corp_actions;
