# N007: Vercel entry point and config
Cloud · Depends on: N004 · Model: sonnet

## Goal
Importing the repo into Vercel gives the React build plus the FastAPI app as one Python function in `vercel` mode, light and fast to cold-start (SPEC §17.5).

## Read first
SPEC §17.2, §17.5, `backend/app/main.py`, `backend/app/plugins.py`, `backend/pyproject.toml`, `frontend/vite.config.ts`

## Files
- `api/index.py` (new): as §17.5. No uvicorn.
- `vercel.json` (new): as §17.5 (`buildCommand`, `outputDirectory`, rewrites, `functions` with `maxDuration` 60 and `excludeFiles`, `ignoreCommand`). Set `"installCommand"` only if needed.
- `requirements.txt` (new, repo root): as §17.5, pinned to the versions installed in `backend/.venv` (`pip freeze`) for the listed packages.
- `backend/app/main.py`: in vercel mode, don't mount `StaticFiles` or the SPA fallback (Vercel serves the static build); `/api/*` routing is unchanged.
- `backend/tests/test_vercel_mode.py` (new): import `api/index.py` with `STOCK_RUNTIME=vercel` and a tmp SQLite DB that was initialised beforehand. Check that `TestClient(app).get("/api/health")` works, that no worker/scheduler thread started, that `init_db` wasn't called, and that custom indicators weren't loaded.
- `README.md`: replace the laptop setup with a short "Local dev" section (`./start.sh --dev` still works on a local SQLite file) and a link to `docs/CLOUD_SETUP.md`. Remove the Windows auto-start and LAN paragraphs.

## Requirements
- Report the installed size of the `requirements.txt` set (`pip install --target /tmp/x -r requirements.txt && du -sh /tmp/x`, using the scratch dir) in the notes. It must be well under 500 MB.

## Notes for the planner
- **Install size:** `pip install --target` wasn't approved in the headless session, so I measured the same packages and their dependencies in `backend/.venv/site-packages` instead (fastapi, starlette, pydantic(+core), httpx stack, pandas, numpy, dateutil, tzdata, bs4, soupsieve, lxml, feedparser, sgmllib, libsql): **≈192 MB**, well under 500 MB. You can confirm it with `pip install --target <scratch> -r requirements.txt && du -sh <scratch>`.
- `vercel.json` `ignoreCommand` uses `git diff --quiet HEAD^ HEAD -- . ':(exclude)…'`: exit 0 (only ignored paths changed) skips the deploy. If `HEAD^` is missing (shallow clone), git exits non-zero and the deploy runs anyway, which is the safe direction.
- `installCommand` is not set: Vercel installs the root `requirements.txt` for the Python function by default.
- README: the "first full load" section still talks about leaving the laptop running and keeping it awake, and "Backup and restore" / "AI features" still describe the laptop. These are out of scope here; they should be rewritten for the cloud (N010/N011/N020).
