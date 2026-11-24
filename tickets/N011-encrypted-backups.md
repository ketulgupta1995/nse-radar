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
- (Opus, after N002) `backup._verify` reads `PRAGMA user_version` of the copy; use `db.schema_version(conn)` instead (a Turso-made DB keeps its version in `schema_meta`, §17.11).
- (Sonnet, N011) Done: `_verify` now uses `db.schema_version`.
- (Sonnet, N011) `backup_keep_phone` / `backup_every_days_phone` were never in `DEFAULT_SETTINGS`, only in SPEC §5; removed from the SPEC.
- (Sonnet, N011) The weekly skip reads the last `done` backup run from `job_runs` (message `saved nse-radar-YYYY-MM-DD…`), because the plain file is deleted by drain.yml and `data/backups` isn't in the Actions cache.
- (Sonnet, N011) In actions mode the copy is `VACUUM INTO` via plain `sqlite3` on `REPLICA_PATH` after `db.sync()`, not through the libsql wrapper. Check on the first real drain that this works on a libsql replica file (N020).
- (Sonnet, N011) `backup_every_days` is in `DEFAULT_SETTINGS`, so `GET /api/settings` returns it, but `app/api/settings.py` has no validator for it: `PUT {"backup_every_days": …}` would raise a KeyError (500). Add `"backup_every_days": Annotated[int, Field(ge=1, le=90)]` to `Simple` (outside this ticket's files).
- (Sonnet, N011) drain.yml fails the encrypt step (and deletes the plain file) when the `BACKUP_PASSPHRASE` secret is missing, so a backup is never uploaded unencrypted.
