# Cloud setup (owner steps)

These are the steps only you can do: accounts, secrets and the first run. Do them in order. Each step says what to type or click. The background is in SPEC §17.

You need: a GitHub account, a Turso account, a Vercel account (all free), and a terminal on the laptop in `~/ketul/claude_projects/nse-radar`.

---

## 1. GitHub: the repo

1. On github.com click **New repository**. Name: `nse-radar`. Visibility: **Public**. Leave "Add a README" and the other boxes **unticked**, so it starts empty. Click **Create repository**.
2. In the laptop terminal, push the code:
   ```bash
   cd ~/ketul/claude_projects/nse-radar
   git remote add origin https://github.com/<your-user>/nse-radar.git
   git push -u origin main
   ```
3. In the repo on github.com: **Settings → Actions → General**. Under "Approval for running fork pull request workflows from contributors", choose **Require approval for all external contributors** and click **Save**. This stops a stranger's pull request from running changed workflows against your data (SPEC §17.8).

## 2. Turso: the database

1. Install the Turso command-line tool and log in (a browser window opens):
   ```bash
   curl -sSfL https://get.tur.so/install.sh | bash
   turso auth login
   ```
2. Make the seed file: a cleaned copy of the laptop database. The laptop app can keep running; the script only reads its database and never changes it.
   ```bash
   cd ~/ketul/claude_projects/nse-radar
   backend/.venv/bin/python scripts/make_seed.py \
     --from ~/ketul/claude_projects/stock-tools/data/stock.db --out data/seed.db
   ```
   It prints how many rows each table has, the file size (about 370 MB) and the next command. If `data/seed.db` already exists it stops; add `--force` to replace it.
3. Create the database from the file. Group `us` is in aws-us-east-1, next to GitHub's runners and Vercel (SPEC §17.11). It already exists.
   ```bash
   turso db create nse-radar --group us --from-file data/seed.db
   ```
4. Get the address and a key for the database:
   ```bash
   turso db show nse-radar --url
   turso db tokens create nse-radar
   ```
5. Copy the example settings file and fill in those two values:
   ```bash
   cp .env.example .env.local
   ```
   In `.env.local` set `TURSO_DATABASE_URL=` to the URL (starts with `libsql://`) and `TURSO_AUTH_TOKEN=` to the token. Keep this file; it is never committed (`.gitignore` covers it).

## 3. GitHub secrets

In the repo: **Settings → Secrets and variables → Actions → New repository secret**. Add three:

| Name | Value |
|---|---|
| `TURSO_DATABASE_URL` | the URL from step 2.4 |
| `TURSO_AUTH_TOKEN` | the token from step 2.4 |
| `BACKUP_PASSPHRASE` | a new random passphrase (below) |

Make the passphrase with:
```bash
openssl rand -base64 32
```
**Save a copy in your password manager.** Without it the weekly backups can't be opened, and GitHub won't show a secret again once saved.

## 4. A GitHub token so the website can start the cloud worker

1. On github.com: your picture → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Name: `nse-radar dispatch`. Expiration: the longest offered (put a reminder in your calendar to renew it).
3. Repository access: **Only select repositories** → `nse-radar`.
4. Permissions → Repository permissions → **Actions: Read and write**. Leave everything else as "No access".
5. Click **Generate token** and copy it. You need it in step 5 as `GITHUB_DISPATCH_TOKEN`.

## 5. Vercel: the website

1. On vercel.com: **Add New → Project → Import** your `nse-radar` GitHub repo.
2. Framework Preset: **Other**. Leave the build settings alone; `vercel.json` sets them.
3. Open **Environment Variables** and add:

   | Name | Value |
   |---|---|
   | `STOCK_RUNTIME` | `vercel` |
   | `TURSO_DATABASE_URL` | the URL from step 2.4 |
   | `TURSO_AUTH_TOKEN` | the token from step 2.4 |
   | `APP_PASSWORD` | the password you'll type to open the site |
   | `APP_SECRET` | output of `openssl rand -hex 32` |
   | `GITHUB_REPO` | `<your-user>/nse-radar` |
   | `GITHUB_DISPATCH_TOKEN` | the token from step 4 |

4. Click **Deploy**. When it finishes, Vercel shows the site's address (`https://nse-radar-….vercel.app`).

## 6. First run

1. In the GitHub repo: **Actions → drain → Run workflow → Run workflow**. This runs migrations and any waiting jobs. Wait for the green tick (the first run takes longer while it copies the database).
2. On your phone, open the Vercel address and log in with `APP_PASSWORD`. Add it to the home screen if you like.
3. From now on the `daily` workflow runs by itself every weekday evening (18:45 IST) and every morning (08:00 IST).

### What the workflows do

The repo has three workflows under **Actions**. `ci` runs the backend tests and lint and the frontend build and tests on every push and pull request; it uses no secrets. `drain` is the cloud worker: it restores its local copy of the database from the Actions cache, runs every waiting job, then saves the copy again; only one drain runs at a time and at most one more waits, and its log shows counts only. The website starts a drain whenever you queue a job. `daily` runs at 18:45 IST on weekdays and 08:00 IST every day; it keeps the schedule switched on (GitHub turns off schedules after 60 quiet days) and then calls `drain` with "tick" on, so every job that's due gets queued first. To run a drain by hand: **Actions → drain → Run workflow**, optionally type a reason and tick **Enqueue every due schedule first**, then click **Run workflow**.

## 7. Opening a backup

Every week the cloud worker saves an encrypted copy of the database as a GitHub artifact, kept for 90 days.

1. In the repo: **Actions** → pick a recent `drain` run → scroll to **Artifacts** → download the backup. GitHub gives you a `.zip`; unzip it to get the encrypted file (ends in `.enc`).
2. Decrypt and unpack it, entering your `BACKUP_PASSPHRASE` when asked:
   ```bash
   openssl enc -d -aes-256-cbc -pbkdf2 -in nse-radar-YYYY-MM-DD.db.gz.enc -out nse-radar-YYYY-MM-DD.db.gz
   gunzip nse-radar-YYYY-MM-DD.db.gz
   ```
   You now have a normal SQLite file, `nse-radar-YYYY-MM-DD.db`.
3. To restore it into Turso as a fresh database (keep the old one until the new one works):
   ```bash
   sqlite3 nse-radar-YYYY-MM-DD.db "PRAGMA journal_mode=WAL;"
   turso db create nse-radar-restored --group us --from-file nse-radar-YYYY-MM-DD.db
   turso db show nse-radar-restored --url
   turso db tokens create nse-radar-restored
   ```
   Then put the new URL and token into the GitHub secrets (step 3), the Vercel variables (step 5) and `.env.local`, and redeploy on Vercel. For a mistake made in the last day, Turso's own point-in-time restore (in the Turso dashboard) is quicker.

## 8. Keep private things private

- **Never commit `.env.local`** (or any `.env*` file other than `.env.example`) or anything in `data/`. `git status` should never list them.
- **Everything in the repo and in the Actions logs and artifacts is public.** Secrets belong only in GitHub secrets, Vercel environment variables and `.env.local`. Don't paste a token, password, or your positions or journal into an issue, a commit message or a workflow file.
- If a secret leaks: make a new one (Turso: `turso db tokens invalidate nse-radar`, then create a new token; GitHub: delete the token and generate another), update it everywhere, and redeploy.
