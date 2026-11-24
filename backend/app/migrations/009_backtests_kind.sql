-- T113: backtests get a kind (explore / final / legacy), a parent link and a strategy fingerprint. Existing rows are legacy.
ALTER TABLE backtests ADD COLUMN kind TEXT NOT NULL DEFAULT 'legacy' CHECK (kind IN ('explore','final','legacy'));
ALTER TABLE backtests ADD COLUMN parent_id INTEGER;
ALTER TABLE backtests ADD COLUMN fingerprint TEXT
