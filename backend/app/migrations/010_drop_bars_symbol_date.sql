-- 2026-11-23: bars_symbol_date (~277 MB) duplicated the primary key (source, symbol, date): symbol lookups
-- use a skip-scan on the key, and the one query that needed it (last trading date) now reads bars_date_symbol.
DROP INDEX IF EXISTS bars_symbol_date
