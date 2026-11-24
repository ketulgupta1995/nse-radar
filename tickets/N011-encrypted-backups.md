# N011: Weekly encrypted backup from the cloud worker
Cloud · Depends on: N006 · Model: sonnet

## Goal
A weekly backup of the whole DB exists outside Turso (whose free plan restores only 1 day back), and is never readable by the public (SPEC §17.8).

## Read first
SPEC §17.8, §6 (`backup` row), §5 (backup settings), `backend/app/jobs/defs/backup.py`, `backend/tests/test_backup_job.py`, `.github/workflows/drain.yml`

## Files
- `backend/app/jobs/defs/backup.py`: in `actions` mode, `VACUUM INTO` from the replica after `db.sync()`, then `quick_check`, gzip to `data/backups/nse-radar-YYYY-MM-DD.db.gz`, at most once every 7 days (settings key `backup_every_days`, default 7, replacing the phone-only keys), keeping 1 file on the runner. Local mode is unchanged. Remove `backup_keep_phone` / `backup_every_days_phone` from `DEFAULT_SETTINGS` and SPEC §5, and replace the "Phone rules: §17.2" note in the §6 table with "Cloud: weekly, §17.8".
- `.github/workflows/drain.yml`: after the drain, if `data/backups/*.db.gz` exists: `openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -in … -out ….enc`, delete the plain file, `actions/upload-artifact` the `.enc` with `retention-days: 90`. The plain file is never uploaded.
- `docs/CLOUD_SETUP.md`: how to restore (download the artifact → `openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:… -in x.enc | gunzip > restore.db` → `turso db import` into a new DB).
- Tests: the backup job in actions mode (tmp DB standing in for the replica, `db.sync` patched): the weekly skip, the file name, gzip validity, and that settings keys are seeded.

## Notes for the planner
