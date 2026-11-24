-- 2026-11-24 (N021): source credentials in the cloud. Vercel's file system is read-only, so in `vercel` and
-- `actions` mode sources/secrets.py keeps them here (Turso, private) instead of data/secrets.json.
CREATE TABLE IF NOT EXISTS source_secrets (source TEXT, key TEXT, value TEXT, PRIMARY KEY (source, key))
