# N006: GitHub Actions workflows: ci, drain, daily
Cloud · Depends on: N005 · Model: sonnet

## Goal
The cloud worker exists. Every push is tested, the drain can be started by hand or by Vercel, and the daily schedule runs it twice a day (SPEC §17.3, §17.4).

## Read first
SPEC §17.3, §17.4, §17.8, `docs/CLOUD_SPIKE.md`, `.github/workflows/spike.yml` (N001)

## Files
- `.github/workflows/ci.yml`: push + pull_request; Python 3.13 with pip cache → `pip install -e "backend[dev]"`, `pytest -q`, `ruff check app tests`; Node 22 with npm cache → `npm ci`, `npm run build`, `npm test` in `frontend/`. `permissions: contents: read`. No secrets.
- `.github/workflows/drain.yml`: `workflow_dispatch` (input `reason`, string, default "manual"; input `tick`, boolean, default false) and `workflow_call` (same inputs). The `concurrency` block from §17.4, `timeout-minutes: 150`, `permissions: contents: read`. Steps: checkout → Python 3.13 + pip cache → `pip install -e backend` → `actions/cache/restore` for `data/replica.db` and `data/cache/price_store.pkl` (restore-keys `replica-`) → `python -m app.jobs.drain --lane all [--tick]` in `backend/` with env `STOCK_RUNTIME=actions`, `STOCK_DATA_DIR=${{ github.workspace }}/data`, `STOCK_REPLICA_PATH=…/data/replica.db` and the Turso secrets → `actions/cache/save` with key `replica-${{ github.run_id }}` (`if: always()`) → the backup encrypt-and-upload steps are added by N011, not here.
- `.github/workflows/daily.yml`: the two crons from §17.4; one job `uses: ./.github/workflows/drain.yml` with `tick: true`, `reason: schedule`, `secrets: inherit`. Before it, a small `keepalive` job (`permissions: actions: write`) runs `gh workflow enable daily.yml` with `GH_TOKEN: ${{ github.token }}` (§17.4 keep-alive; it must not fail the run, so `|| true`).
- `.github/workflows/spike.yml`: delete it (N001 is done).
- `docs/CLOUD_SETUP.md`: one paragraph on what each workflow does and how to run a drain by hand.

## Requirements
- Validate the YAML locally with `python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/*.yml` if PyYAML is available. Otherwise review it carefully, because CI can't run until it's pushed.
- No step echoes secrets or private data.

## Notes for the planner
