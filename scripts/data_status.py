#!/usr/bin/env python3
"""Print how much data stock-tools has filled and what is pending.

Usage: python3 scripts/data_status.py [path/to/stock.db]
Read-only; safe to run while the app is running.
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data" / "stock.db"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def q(sql):
    return c.execute(sql).fetchall()


def one(sql):
    return q(sql)[0][0]


def bar(done, total, width=30):
    frac = (done / total) if total else 0
    n = round(frac * width)
    return f"[{'#' * n}{'.' * (width - n)}] {frac:4.0%}"


def status(done, total):
    return "DONE   " if total and done >= total else ("EMPTY  " if done == 0 else "PARTIAL")


def head(title):
    print(f"\n{'=' * 78}\n {title}\n{'=' * 78}")


def table(headers, rows):
    rows = [[str(x) for x in r] for r in rows]
    w = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * x for x in w))
    for r in rows:
        print("  ".join(r[i].ljust(w[i]) for i in range(len(headers))))


def short_time(ts):
    return ts[:16].replace("T", " ") if ts else "never"


total = one("select count(*) from symbols where in_universe=1")
print(f"STOCK-TOOLS DATA STATUS   (db: {DB})")
print(f"Stocks tracked (Nifty 500 universe): {total}")

# ---------------------------------------------------------------- coverage
head("1. FILLED vs PENDING (per symbol coverage)")


def cov_symbols(sql):
    return one(sql)


price_syms = cov_symbols(
    "select count(distinct symbol) from bars where source='yfinance' "
    "and symbol in (select symbol from symbols where in_universe=1)"
)
bhav_syms = cov_symbols(
    "select count(distinct symbol) from bars where source='nse_bhav' "
    "and symbol in (select symbol from symbols where in_universe=1)"
)
fund_syms = cov_symbols("select count(distinct symbol) from fundamentals")
qtr_syms = cov_symbols("select count(distinct symbol) from quarters")
ann_syms = cov_symbols("select count(distinct symbol) from announcements") if q("select 1 from announcements limit 1") else 0
news_n = one("select count(*) from news_items")

rows = []
for label, n in [
    ("Price history (yfinance)", price_syms),
    ("Price history (NSE bhavcopy)", bhav_syms),
    ("Fundamentals (snapshot)", fund_syms),
    ("Quarterly results", qtr_syms),
    ("Announcements", ann_syms),
]:
    rows.append([label, status(n, total), f"{n}/{total}", bar(n, total), total - n])
table(["Data set", "State", "Filled", "Progress", "Pending"], rows)
print(f"\nNews items stored: {news_n}  ({'none yet' if not news_n else 'has data'})")

# ---------------------------------------------------------------- prices detail
head("2. PRICE DATA DETAIL")
rows = []
for src, n, lo, hi in q("select source,count(*),min(date),max(date) from bars group by source"):
    rows.append([src, f"{n:,}", lo, hi])
table(["Source", "Rows", "From", "To"], rows)
print(f"\nTrading days with data: {one('select count(distinct date) from bars')}")
print(f"Index (NIFTY 500) bars: {one('select count(*) from index_bars'):,}")
print(f"Corporate actions (splits/bonus/dividends): {one('select count(*) from corp_actions')}")
print(f"Price cross-checks done: {one('select count(*) from price_checks')}")

missing = [r[0] for r in q(
    "select symbol from symbols where in_universe=1 and symbol not in "
    "(select distinct symbol from bars where source='yfinance') order by symbol"
)]
if missing:
    print(f"Symbols with NO yfinance prices ({len(missing)}): {', '.join(missing[:20])}{' ...' if len(missing) > 20 else ''}")

# ---------------------------------------------------------------- jobs
head("3. JOBS RIGHT NOW")
rows = q("select id,job,status,total,done,ok,skipped,failed,started_at from job_runs where status in ('running','queued')")
if rows:
    table(
        ["Run", "Job", "State", "Progress", "Done/Total", "OK", "Skipped", "Failed", "Started"],
        [[i, j, s, bar(d, t) if t else "-", f"{d}/{t}" if t else "-", ok, sk, f, short_time(st)] for i, j, s, t, d, ok, sk, f, st in rows],
    )
else:
    print("No jobs running or queued.")

head("4. LAST RUN OF EACH JOB")
table(
    ["Job", "Result", "When", "Items ok/total", "Failed"],
    [
        [j, s, short_time(w), f"{ok}/{t}" if t else "-", f]
        for j, s, w, ok, t, f in q(
            "select job,status,coalesce(finished_at,started_at,queued_at),ok,total,failed from job_runs "
            "where id in (select max(id) from job_runs group by job) order by job"
        )
    ],
)

head("5. NEXT SCHEDULED RUNS")
table(
    ["Job", "Repeats", "Enabled", "Next run"],
    [
        [j, k if not t else f"{k} @ {t}", "yes" if e else "PAUSED", short_time(n)]
        for j, k, t, e, n in q("select job,kind,at_time,enabled,next_run_at from job_schedules order by next_run_at is null, next_run_at")
    ],
)

# ---------------------------------------------------------------- sources
head("6. DATA SOURCES")
rows = []
for src, en, paused, ok, err_at, err in q("select source,enabled,paused_reason,last_ok_at,last_error_at,last_error from source_state"):
    fetched = one(f"select count(*) from source_fetch where source='{src}' and status='ok'")
    failed = one(f"select count(*) from source_fetch where source='{src}' and status!='ok'")
    state = "on" if en else f"OFF ({paused})"
    rows.append([src, state, short_time(ok), fetched, failed, (err or "")[:40]])
table(["Source", "State", "Last success", "Fetches ok", "Fetches failed", "Last error"], rows)

head("7. APP USAGE (your own data)")
table(
    ["Table", "Rows"],
    [[t, one(f"select count(*) from {t}")] for t in ("screens", "screen_results", "alerts", "watchlist", "positions", "checklists", "backtests", "ai_requests")],
)
print()
