# N003: Seed script and the owner's setup guide
Cloud · Depends on: N002 · Model: sonnet

## Goal
A one-time, read-only copy of the laptop DB becomes `data/seed.db`, ready for `turso db import` (SPEC §17.6). Plus a step-by-step setup guide for everything only the owner can do.

## Read first
SPEC §17.5, §17.6, §17.8, §4 (tables), `backend/app/db.py` (`DEFAULT_SETTINGS`)

## Files
- `scripts/make_seed.py` (new): `--from PATH --out PATH [--force]`. Follow §17.6 exactly. Refuse to overwrite `--out` without `--force`, and refuse if `--from` and `--out` resolve to the same file. Open the source only with a `mode=ro` URI. Print row counts per table, the file size and the next command. Use `logging`.
- `backend/tests/test_make_seed.py` (new): build a small source DB with `init_db()` in tmp, add job_runs/ai_requests rows and laptop settings, run the script's `main()`, and check the copy (history cleared, settings changed, WAL mode, `quick_check` ok), that the source file's bytes and mtime are unchanged, and the refusals.
- `docs/CLOUD_SETUP.md` (new), written for the owner in plain steps:
  1. GitHub: create the public repo `nse-radar` (empty), push `main`, Settings → Actions → "Require approval for all external contributors" (§17.8)
  2. Turso: install the CLI (`curl -sSfL https://get.tur.so/install.sh | bash`), `turso auth login`, then run `make_seed.py`, `turso db create nse-radar --group us --from-file data/seed.db` (group `us` is aws-us-east-1, SPEC §17.11; it already exists), `turso db show nse-radar --url`, `turso db tokens create nse-radar`. Put both into `.env.local` (copy `.env.example`).
  3. GitHub secrets: `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `BACKUP_PASSPHRASE` (generate with `openssl rand -base64 32`; keep a copy in a password manager)
  4. A fine-grained GitHub token for dispatch: this repo only, permission Actions: read and write
  5. Vercel: import the GitHub repo (framework "Other"), env vars from §17.5 (`APP_SECRET` from `openssl rand -hex 32`), deploy
  6. First run: Actions → drain → Run workflow; then open the site on the phone and log in
  7. How to decrypt and restore a backup artifact (§17.8)
  8. Reminder: never commit `.env.local`, and everything in the repo and the Actions logs is public

## Notes for the planner
