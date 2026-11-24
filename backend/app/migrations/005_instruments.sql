-- T087a: what each traded symbol is, from bhavcopy.
CREATE TABLE IF NOT EXISTS instruments (
  symbol TEXT PRIMARY KEY, isin TEXT, series TEXT,
  last_date TEXT NOT NULL, source TEXT NOT NULL)
