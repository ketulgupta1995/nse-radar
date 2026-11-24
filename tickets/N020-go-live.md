# N020: Go live
Cloud · Depends on: N001–N011 (the phone tickets can land before or after) · **Opus + owner**

## Goal
nse-radar is running for real: seeded Turso, the Vercel site behind the password, the daily drain on schedule, and checked from the phone.

## Steps (Opus walks the owner through `docs/CLOUD_SETUP.md`)
1. Laptop: let stock-tools finish a catch-up, then `scripts/make_seed.py --from ~/ketul/claude_projects/stock-tools/data/stock.db --out data/seed.db`, then `turso db import`.
2. GitHub secrets, the Vercel project and env, and the dispatch token, as in the guide.
3. Run the drain by hand. Check its summary, that `/api/health` on the site says `schema: ok`, and the Turso usage after the run (reads/writes), and record those in `docs/CLOUD_SPIKE.md` under "First week".
4. On the phone: log in, Dashboard, a Stock page, run one screen and one backtest, and confirm both finish via the cloud worker.
5. Watch the first two scheduled runs. After a week, compare Turso and Vercel usage with the limits in §17.1 and note any route to slim down.

## Notes for the planner
