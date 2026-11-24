"""N001 cloud spike: can libsql stand in for sqlite3, and do data sources answer from GitHub Actions?

Prints and saves only status codes, timings, sizes and booleans: never data rows (SPEC §17.8).

    python scripts/spike_cloud.py --db --out data/spike-db.json         # needs TURSO_DATABASE_URL/TOKEN
    python scripts/spike_cloud.py --sources --latency HOST --out x.json  # run in GitHub Actions
"""

import argparse
import json
import os
import platform
import shutil
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def _timed(fn):
    t = time.perf_counter()
    try:
        out = fn()
        return {"ok": True, "s": round(time.perf_counter() - t, 3), **(out if isinstance(out, dict) else {})}
    except Exception as e:  # the spike records failures instead of stopping
        return {"ok": False, "s": round(time.perf_counter() - t, 3), "error": f"{type(e).__name__}: {e}"[:300]}


def check_db() -> dict:
    import libsql

    url, tok = os.environ["TURSO_DATABASE_URL"], os.environ["TURSO_AUTH_TOKEN"]
    c = libsql.connect(url, auth_token=tok, isolation_level=None)
    res: dict = {"libsql_version": getattr(libsql, "__version__", "?")}
    c.execute("DROP TABLE IF EXISTS spike_t")
    c.execute("CREATE TABLE spike_t(id INTEGER PRIMARY KEY, k TEXT UNIQUE, v REAL)")
    cur = c.execute("INSERT INTO spike_t(k, v) VALUES ('a', 1.5)")
    res["lastrowid"], res["rowcount"] = cur.lastrowid, cur.rowcount
    res["row_type"] = type(c.execute("SELECT * FROM spike_t").fetchone()).__name__
    res["row_factory_supported"] = hasattr(c, "row_factory")
    for name, sql in (("unique", "INSERT INTO spike_t(k, v) VALUES ('a', 2)"), ("no_table", "SELECT * FROM nope")):
        try:
            c.execute(sql)
            res[f"err_{name}"] = "no error"
        except Exception as e:
            res[f"err_{name}"] = f"{type(e).__name__}: {e}"[:200]
    res["pragmas"] = {}
    for p in ("foreign_keys=ON", "journal_mode=WAL", "busy_timeout=10000", "synchronous=NORMAL", "user_version"):
        try:
            c.execute(f"PRAGMA {p}")
            res["pragmas"][p] = "ok"
        except Exception:
            res["pragmas"][p] = "refused"
    c.execute("BEGIN IMMEDIATE")
    c.execute("INSERT INTO spike_t(k, v) VALUES ('tx', 1)")
    c.execute("ROLLBACK")
    res["rollback_works"] = c.execute("SELECT count(*) FROM spike_t WHERE k='tx'").fetchone()[0] == 0
    lat = []
    for _ in range(20):
        t = time.perf_counter()
        c.execute("SELECT 1").fetchone()
        lat.append(time.perf_counter() - t)
    res["select1_median_ms"] = round(statistics.median(lat) * 1000)
    rows = [(f"m{i}", i) for i in range(200)]
    res["executemany_200"] = _timed(lambda: c.executemany("INSERT INTO spike_t(k, v) VALUES (?, ?)", rows))
    flat = [x for i in range(5000) for x in (f"b{i}", i)]
    res["multirow_5000"] = _timed(
        lambda: c.execute("INSERT INTO spike_t(k, v) VALUES " + ",".join(["(?, ?)"] * 5000), flat)
    )
    script = ";".join(f"UPDATE spike_t SET v={i * 2} WHERE k='b{i}'" for i in range(500))
    res["executescript_500_updates"] = _timed(lambda: c.executescript(script))
    res["updates_applied"] = c.execute("SELECT count(*) FROM spike_t WHERE k LIKE 'b%' AND v = 2 * CAST(substr(k, 2) AS INTEGER) AND CAST(substr(k, 2) AS INTEGER) < 500").fetchone()[0]

    rp = Path(os.environ.get("SPIKE_REPLICA", "data/spike-replica.db"))
    for f in rp.parent.glob(rp.name + "*"):
        f.unlink()
    rp.parent.mkdir(parents=True, exist_ok=True)
    r = libsql.connect(str(rp), sync_url=url, auth_token=tok, isolation_level=None)
    res["replica_first_sync"] = _timed(lambda: r.sync())
    r.execute("BEGIN IMMEDIATE")
    r.execute("INSERT INTO spike_t(k, v) VALUES ('rep', 1)")
    res["replica_read_your_write_in_tx"] = r.execute("SELECT count(*) FROM spike_t WHERE k='rep'").fetchone()[0] == 1
    r.execute("COMMIT")
    res["remote_sees_replica_write"] = c.execute("SELECT count(*) FROM spike_t WHERE k='rep'").fetchone()[0] == 1
    c.execute("INSERT INTO spike_t(k, v) VALUES ('remote', 1)")
    res["replica_second_sync"] = _timed(lambda: r.sync())
    res["replica_sees_remote_after_sync"] = r.execute("SELECT count(*) FROM spike_t WHERE k='remote'").fetchone()[0] == 1
    single = []
    for i in range(10):
        t = time.perf_counter()
        r.execute("INSERT INTO spike_t(k, v) VALUES (?, ?)", (f"rs{i}", i))
        single.append(time.perf_counter() - t)
    res["replica_single_write_median_ms"] = round(statistics.median(single) * 1000)
    c.execute("DROP TABLE spike_t")
    return res


def _recent_weekdays(n: int) -> list[date]:
    d, out = date.today(), []
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def check_sources() -> dict:
    from app import db
    from app.sources import http
    from app.sources.parsers.bhavcopy import bhav_url

    def fetch(url: str, **kw) -> dict:
        def go():
            return {"bytes": len(http.get(url, **kw))}

        out = _timed(go)
        if not out["ok"] and "HTTP " in out.get("error", ""):
            out["status"] = int(out["error"].split("HTTP ")[1].split()[0])
        return out

    res: dict = {}
    for d in _recent_weekdays(3):
        res[f"bhav_{d.isoformat()}"] = fetch(bhav_url(d))
    res["nifty500_csv"] = fetch("https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv")
    res["nse_corporate_actions"] = fetch(
        "https://www.nseindia.com/api/corporates-corporateActions", params={"index": "equities", "symbol": "TCS"},
        accept="application/json",
    )
    to, fr = date.today(), date.today() - timedelta(days=7)
    res["nse_announcements"] = fetch(
        "https://www.nseindia.com/api/corporate-announcements",
        params={"index": "equities", "symbol": "TCS", "from_date": fr.strftime("%d-%m-%Y"),
                "to_date": to.strftime("%d-%m-%Y")},
        accept="application/json",
    )
    res["nse_xbrl"] = fetch(
        "https://nsearchives.nseindia.com/corporate/xbrl/INDAS_117182_1341298_09012025093940.xml"
    )
    res["screener_company"] = fetch("https://www.screener.in/company/TCS/consolidated/")
    for feed in db.DEFAULT_SETTINGS["rss_feeds"]:
        res[f"rss_{feed['name']}"] = fetch(feed["url"])

    def yf():
        import yfinance

        df = yfinance.download("TCS.NS", period="1mo", progress=False, auto_adjust=False)
        return {"rows": int(len(df))}

    res["yfinance_TCS"] = _timed(yf)
    return res


def check_latency(host: str) -> dict:
    import httpx

    out, codes = [], set()
    with httpx.Client(timeout=10) as cl:
        for _ in range(8):
            t = time.perf_counter()
            codes.add(cl.get(f"https://{host}/health").status_code)
            out.append(time.perf_counter() - t)
    return {"host": host, "codes": sorted(codes), "median_ms_warm": round(statistics.median(out[1:]) * 1000)}


def runner_info() -> dict:
    info = {"python": platform.python_version(), "cpus": os.cpu_count(),
            "disk_free_gb": round(shutil.disk_usage(".").free / 1e9, 1)}
    try:
        kb = int(next(line for line in open("/proc/meminfo") if line.startswith("MemTotal")).split()[1])
        info["ram_gb"] = round(kb / 1e6, 1)
    except (OSError, StopIteration):
        pass
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="store_true")
    ap.add_argument("--sources", action="store_true")
    ap.add_argument("--latency", action="append", default=[])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res: dict = {"where": os.environ.get("SPIKE_WHERE", "local"), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "runner": runner_info()}
    if a.db:
        res["db"] = check_db()
    if a.sources:
        from app.plugins import import_all

        import_all("app.sources.adapters")  # registers the per-host rate-limit policies
        res["sources"] = check_sources()
    for h in a.latency:
        res.setdefault("latency", []).append(check_latency(h))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
