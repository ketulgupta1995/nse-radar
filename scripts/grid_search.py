#!/usr/bin/env python3
"""Staged grid search over the preset screens: find the best few screens and their best settings.

Stages (each one reads the results of the one before):
  1. every screen x 54 exit settings (ATR stop x sell-below-SMA x time stop x breadth filter)
     x every max-positions value (--slots-grid, default 3..10), at the base capital (--capital)
  2. the top N screens: every entry-threshold variant (each number one notch looser / as is / stricter),
     with that screen's best stage-1 exit and max positions
  3. the top K screens: their best entry variant x the 54 exit settings x every max-positions value
     (--slots-grid, default 3..10) x every starting capital (--capital-grid, default 1..5 lakh)
  4. the K winners: one run over the whole period, reported separately for training and test,
     next to the same screen with its own numbers and default exits, at the winner's size

Stages 1-3 only simulate the training period (start -> day before --test-start). Ranking uses training
results only; the test period is looked at once, in stage 4. Score = CAGR / |max drawdown|, and a variant
needs at least --min-trades trades in training to count.

Output, in data/grid/<name>/:
  summary.md        the report to read: what was run, the winners in plain words, all screens ranked
  all_results.csv   every config that ran (open in a spreadsheet to dig in)
  stageN.wK.jsonl   raw results (one file per worker), written as they finish; a run resumes from them
  run.json          the settings and timings of the run

Stop the app first (it shares the price store and the database):
    ps -eo pid,args | grep "[.]venv/bin/uvicorn"     # must print nothing

Usage (from the repo root):
    backend/.venv/bin/python scripts/grid_search.py --dry-run          # counts only, runs nothing
    backend/.venv/bin/python scripts/grid_search.py                    # all stages, 3 workers
    backend/.venv/bin/python scripts/grid_search.py --stage 3          # one stage (needs the earlier ones)
    backend/.venv/bin/python scripts/grid_search.py --skip-fund        # leave out screens using fundamentals
    backend/.venv/bin/python scripts/grid_search.py --summary          # rebuild the report from saved results
    backend/.venv/bin/python scripts/grid_search.py --list             # list saved runs
    backend/.venv/bin/python scripts/grid_search.py --delete [--yes]   # delete this run's output folder
"""

# ruff: noqa: E501  (long report-text lines read better unbroken)
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import itertools
import json
import logging
import random
import shutil
import subprocess
import sys
import time
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

STOPS = (2.5, 3.0, 4.0)  # ATRs below the buy price
SMAS = (50, 100, 200)  # sell at the next open after a close below this average
DAYS = (60, 120, 200)  # time stop, trading days
BREADTH = (False, True)  # True: no new buys while under 50% of stocks are above their 200-day average
DEFAULT_EXIT = {"stop": 3.0, "sma": 100, "days": 120, "breadth": False}
SCREEN_NOTES = {
    13: "results data is thin before 2020, so the training years have few trades",
    14: "industry data exists only for today's 500 stocks (survivorship bias)",
}
# settings that change results: a saved run only resumes with the same values
RESULT_SETTINGS = ("capital", "slots", "start", "test_start", "min_trades", "top_screens", "top_final",
                   "max_entry_variants", "screens", "skip_fund", "slots_grid", "capital_grid")  # fmt: skip


# ---- configs ---------------------------------------------------------------------------------------


def exit_grid() -> list[dict]:
    """SMA outermost so configs sharing a signal set sit next to each other (the engine caches 8)."""
    return [
        {"stop": st, "sma": sma, "days": d, "breadth": b}
        for sma in SMAS
        for st in STOPS
        for d in DAYS
        for b in BREADTH
    ]


def exits_json(e: dict) -> list[dict]:
    sma = {"ind": "sma", "params": {"n": e["sma"]}}
    below = {"all": [{"left": {"ind": "close"}, "op": "<", "right": sma}]}
    return [
        {"type": "stop_atr", "params": {"k": e["stop"]}},
        {"type": "rule_exit", "params": {"rule": below}},
        {"type": "time_stop", "params": {"days": e["days"]}},
    ]


def operand_label(o: dict) -> str:
    name = o.get("ind") or o.get("fund") or "?"
    params = ",".join(str(v) for v in (o.get("params") or {}).values())
    return f"{name}({params})" + (" rank" if o.get("rank") else "") if params or o.get("rank") else name


def nice(x: float) -> float:
    return round(x) if abs(x) >= 10 else round(x, 1) if abs(x) >= 1 else round(x, 2)


def threshold_levels(cond: dict) -> list[float] | None:
    """[looser, as is, stricter] for a condition comparing against a non-zero number, else None."""
    right = cond.get("right") or {}
    if "value" not in right or right["value"] == 0:
        return None
    v = float(right["value"])
    up = cond["op"] in (">", ">=", "crosses_above")  # stricter means a bigger number
    if cond["left"].get("rank"):  # percentile 0-100
        step = 5 if v >= 90 else 10
        lv = [v - step, v, min(99, v + step)] if up else [v + step, v, max(1, v - step)]
    else:
        step = abs(v) / 3
        lv = [nice(v - step), v, nice(v + step)] if up else [nice(v + step), v, nice(v - step)]
    return list(dict.fromkeys(lv))


def entry_variants(rule: dict, cap: int) -> list[tuple[dict, dict]]:
    """[(rule, {label: new value})] for every combination of threshold levels; the original first.
    Above `cap` combinations, a fixed random sample (seed 0) that keeps the original."""
    conds = rule.get("all", [])
    knobs = [(i, lv) for i, c in enumerate(conds) if (lv := threshold_levels(c))]
    combos = list(itertools.product(*(lv for _, lv in knobs)))
    original = tuple(conds[i]["right"]["value"] for i, _ in knobs)
    combos.remove(original)
    if len(combos) + 1 > cap:
        combos = random.Random(0).sample(combos, cap - 1)
    out = []
    for combo in [original, *combos]:
        r = copy.deepcopy(rule)
        changes = {}
        for (i, _), val in zip(knobs, combo, strict=True):
            r["all"][i]["right"]["value"] = val
            if val != conds[i]["right"]["value"]:
                changes[f"{operand_label(conds[i]['left'])} {conds[i]['op']}"] = val
        out.append((r, changes))
    return out


def make_cfg(args, rule: dict, e: dict, slots: int, capital: float, full: bool = False):
    from app.backtest.engine import BacktestConfig

    train_end = (date.fromisoformat(args.test_start) - timedelta(days=1)).isoformat()
    return BacktestConfig(
        entry_rule=rule,
        exits=exits_json(e),
        max_positions=slots,
        initial_capital=capital,
        start=args.start,
        end=None if full else train_end,
        oos_start=args.test_start,
        universe="liquid500",
        regime_scale={"breadth_below": 50, "slots_pct": 0} if e["breadth"] else None,
    )


def cfg_id(cfg) -> str:
    return hashlib.sha256(cfg.model_dump_json().encode()).hexdigest()[:16]


def meta(s: dict, changes: dict, e: dict, slots: int, capital: float) -> dict:
    return {
        "screen": s["id"], "name": s["name"], "uses_fund": s["uses_fund"],
        "entry_changes": changes, "exit": e, "slots": slots, "capital": capital,
    }  # fmt: skip


# ---- results ---------------------------------------------------------------------------------------

KEEP = ("cagr", "bench_cagr", "excess", "max_drawdown", "volatility", "trades", "win_rate", "profit_factor",
        "avg_days", "exposure")  # fmt: skip


def slim(m: dict) -> dict:
    return {k: m.get(k) for k in KEEP}


def score(m: dict, min_trades: int) -> float | None:
    cagr, dd, n = m.get("cagr"), m.get("max_drawdown"), m.get("trades") or 0
    if cagr is None or dd is None or n < min_trades:
        return None
    return round(cagr / max(abs(dd), 1.0), 4)


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:  # a line cut short by a stop: that config simply runs again
            pass
    return out


def load_stage(args, stage: int, folder: Path | None = None) -> list[dict]:
    """All result rows of a stage (one file per worker), one row per config."""
    folder = folder or args.out
    rows = {r["id"]: r for p in sorted(folder.glob(f"stage{stage}.w*.jsonl")) for r in load(p)}
    return list(rows.values())


def best_per_screen(rows: list[dict]) -> dict[int, dict]:
    best: dict[int, dict] = {}
    for r in rows:
        if r.get("score") is None:
            continue
        if r["screen"] not in best or r["score"] > best[r["screen"]]["score"]:
            best[r["screen"]] = r
    return best


def ranked_screens(rows: list[dict]) -> list[dict]:
    return sorted(best_per_screen(rows).values(), key=lambda r: r["score"], reverse=True)


def top_of(args, stage: int, by_id: dict, n: int) -> list[dict]:
    """Best row per screen from a stage's results, best first, limited to the selected screens."""
    return [r for r in ranked_screens(load_stage(args, stage)) if r["screen"] in by_id][:n]


# ---- run bookkeeping -------------------------------------------------------------------------------


def settings_of(args) -> dict:
    return {k: getattr(args, k) for k in RESULT_SETTINGS}


def run_info(args) -> dict:
    p = args.out / "run.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_run_info(args, info: dict) -> None:
    (args.out / "run.json").write_text(json.dumps(info, indent=1))


def check_settings(args) -> None:
    """A run folder keeps one set of settings; changing them needs a new --name or --delete."""
    info = run_info(args)
    now = settings_of(args)
    if info and info.get("settings") != now:
        diff = [k for k in RESULT_SETTINGS if info["settings"].get(k) != now[k]]
        sys.exit(
            f"Run '{args.name}' was started with different settings ({', '.join(diff)}).\n"
            f"Use a new --name, or delete the old results with --delete."
        )
    if not info:
        save_run_info(args, {"settings": now, "created": datetime.now().isoformat(timespec="seconds"),
                             "commit": git_commit(), "stages": {}})  # fmt: skip


def git_commit() -> str:
    try:
        root = Path(__file__).resolve().parent.parent
        out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%h %s"], capture_output=True, text=True)
        return out.stdout.strip()
    except OSError:
        return "?"


# ---- running ---------------------------------------------------------------------------------------


def make_row(stage: int, job: dict, rid: str, r, test_start: str, min_trades: int) -> dict:
    from app.backtest import metrics

    row = {"id": rid, "stage": stage, **job["meta"]}
    if isinstance(r, Exception):
        row["error"], row["score"] = str(r), None
    elif job.get("full"):
        split = metrics.split_metrics(r, test_start)
        row["train"], row["test"] = slim(split["is"]), slim(split["oos"])
        row["score"] = score(row["train"], min_trades)
        row["last_day"] = r["equity"][-1]["t"] if r["equity"] else None
    else:
        eq = r["equity"]
        m = metrics.compute_metrics(eq, r["trades"], eq[0]["t"], eq[-1]["t"]) if eq else {}
        row["train"] = slim(m)
        row["score"] = score(row["train"], min_trades)
    return row


def progress(tag: str, n: int, total: int, row: dict, t_start: float) -> None:
    el = time.time() - t_start
    eta = el / n * (total - n)
    tr = row.get("train") or {}
    err = f" ERROR {row['error'][:80]}" if "error" in row else ""
    print(
        f"  {tag}[{n}/{total}] #{row['screen']:<2} {row['slots']} pos ₹{row['capital'] / 1e5:g}L "
        f"cagr={tr.get('cagr')} dd={tr.get('max_drawdown')} trades={tr.get('trades')} score={row['score']}{err}"
        f"  ({el / 60:.1f} min, ~{eta / 60:.0f} min left)",
        flush=True,
    )


def run_share(stage: int, out_file: str, test_start: str, min_trades: int, share: list[dict], tag: str) -> int:
    """Run configs ({"cfg_json", "id", "meta", "full"}) with one shared load, appending a row per result
    to `out_file` as it finishes. Runs in-process or as a spawned worker (then it registers plug-ins)."""
    from app.analytics import price_store
    from app.backtest import batch
    from app.backtest.engine import BacktestConfig

    if tag:  # worker process
        from app.analytics import custom_indicators
        from app.backtest.parallel import PLUGIN_PACKAGES
        from app.plugins import import_all

        warnings.filterwarnings("ignore")
        for pkg in PLUGIN_PACKAGES:
            import_all(pkg)
        try:
            custom_indicators.load_approved()
        except Exception:
            logging.exception("could not load custom indicators")
    cfgs = [BacktestConfig.model_validate_json(j["cfg_json"]) for j in share]
    t_start, n = time.time(), [0]
    with open(out_file, "a") as fh:

        def on_result(k: int, r) -> None:
            row = make_row(stage, share[k], share[k]["id"], r, test_start, min_trades)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            n[0] += 1
            progress(tag, n[0], len(share), row, t_start)

        batch.run_batch(cfgs, None, on_result)
    price_store.save_if_dirty()
    return n[0]


def run_jobs(args, stage: int, jobs: list[dict]) -> None:
    """Run the jobs ({"cfg", "meta", "full"?}) not yet in this stage's results. Each worker appends to its
    own stageN.wK.jsonl as results finish, so stopping loses nothing and memory stays small."""
    import concurrent.futures as cf
    import multiprocessing

    from app.backtest import parallel

    done = {r["id"] for r in load_stage(args, stage)}
    todo = []
    for j in jobs:
        rid = cfg_id(j["cfg"])
        if rid not in done:
            todo.append({"cfg_json": j["cfg"].model_dump_json(), "id": rid, "meta": j["meta"],
                         "full": j.get("full", False), "cfg": j["cfg"]})  # fmt: skip
    print(f"\n== Stage {stage}: {len(jobs)} configs ({len(jobs) - len(todo)} already done, {len(todo)} to run)")
    info = run_info(args)
    st = info["stages"].setdefault(str(stage), {"seconds": 0.0})
    st["configs"] = len(jobs)
    t0 = time.time()
    try:
        if not todo:
            return
        cfgs = [t.pop("cfg") for t in todo]
        from app.backtest import batch

        workers = min(args.workers, len({batch.signal_key(c) for c in cfgs}))
        base = args.out / f"stage{stage}"
        if workers <= 1:
            run_share(stage, f"{base}.w0.jsonl", args.test_start, args.min_trades, todo, "")
            return
        shares = parallel.schedule(cfgs, workers)
        print(f"   {len(shares)} worker processes (each loads prices first, ~30-70 s)")
        ctx = multiprocessing.get_context("spawn")
        with cf.ProcessPoolExecutor(max_workers=len(shares), mp_context=ctx) as pool:
            futs = [
                pool.submit(run_share, stage, f"{base}.w{w}.jsonl", args.test_start, args.min_trades,
                            [todo[i] for i in ix], f"w{w} ")
                for w, ix in enumerate(shares)
            ]  # fmt: skip
            for f in cf.as_completed(futs):
                f.result()  # a crashed worker raises here; its finished rows are already saved
    finally:
        st["seconds"] = round(st["seconds"] + time.time() - t0, 1)
        st["finished"] = datetime.now().isoformat(timespec="seconds")
        save_run_info(args, info)


def screens(args) -> list[dict]:
    import sqlite3

    from app import config

    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    rows = conn.execute("SELECT id, name, description, rule FROM screens ORDER BY id").fetchall()
    out = []
    for sid, name, desc, rule_js in rows:
        rule = json.loads(rule_js)
        uses_fund = '"fund"' in rule_js
        if args.screens and sid not in args.screens:
            continue
        if args.skip_fund and uses_fund:
            continue
        out.append({"id": sid, "name": name, "desc": desc or "", "rule": rule, "uses_fund": uses_fund})
    return out


def stage1(args, scr: list[dict], dry: bool) -> int:
    jobs = []
    for s in scr:
        for e in exit_grid():
            for slots in args.slots_grid:  # sizing innermost: it never changes the signals
                cfg = None if dry else make_cfg(args, s["rule"], e, slots, args.capital)
                jobs.append({"cfg": cfg, "meta": meta(s, {}, e, slots, args.capital)})
    if not dry:
        run_jobs(args, 1, jobs)
    return len(jobs)


def stage2(args, scr: list[dict], dry: bool) -> int:
    by_id = {s["id"]: s for s in scr}
    if dry:
        counts = sorted((len(entry_variants(s["rule"], args.max_entry_variants)) for s in scr), reverse=True)
        return sum(counts[: args.top_screens])  # upper bound: the biggest N
    top = top_of(args, 1, by_id, args.top_screens)
    if not top:
        sys.exit("stage 2 needs stage 1 results with at least one screen scoring (run stage 1 first)")
    jobs = []
    for best in top:
        s = by_id[best["screen"]]
        for rule, changes in entry_variants(s["rule"], args.max_entry_variants):
            cfg = make_cfg(args, rule, best["exit"], best["slots"], args.capital)
            jobs.append({"cfg": cfg, "meta": meta(s, changes, best["exit"], best["slots"], args.capital)})
    run_jobs(args, 2, jobs)
    return len(jobs)


def apply_changes(s: dict, changes: dict) -> dict:
    rule = copy.deepcopy(s["rule"])
    for c in rule.get("all", []):
        label = f"{operand_label(c['left'])} {c['op']}"
        if label in changes:
            c["right"]["value"] = changes[label]
    return rule


def stage3(args, scr: list[dict], dry: bool) -> int:
    per_screen = len(exit_grid()) * len(args.slots_grid) * len(args.capital_grid)
    if dry:
        return args.top_final * per_screen
    by_id = {s["id"]: s for s in scr}
    top = top_of(args, 2, by_id, args.top_final)
    if not top:
        sys.exit("stage 3 needs stage 2 results (run stage 2 first)")
    jobs = []
    for best in top:
        s = by_id[best["screen"]]
        rule = apply_changes(s, best["entry_changes"])
        for e in exit_grid():  # sizing innermost: it never changes the signals
            for slots in args.slots_grid:
                for cap in args.capital_grid:
                    jobs.append({"cfg": make_cfg(args, rule, e, slots, cap),
                                 "meta": meta(s, best["entry_changes"], e, slots, cap)})  # fmt: skip
    run_jobs(args, 3, jobs)
    return len(jobs)


def stage4(args, scr: list[dict], dry: bool) -> int:
    if dry:
        return args.top_final * 2
    by_id = {s["id"]: s for s in scr}
    top = top_of(args, 3, by_id, args.top_final)
    if not top:
        sys.exit("stage 4 needs stage 3 results (run stage 3 first)")
    jobs = []
    for best in top:  # the winner, and the untouched screen with default settings for comparison
        s = by_id[best["screen"]]
        rule = apply_changes(s, best["entry_changes"])
        m = meta(s, best["entry_changes"], best["exit"], best["slots"], best["capital"])
        win = make_cfg(args, rule, best["exit"], best["slots"], best["capital"], full=True)
        jobs.append({"cfg": win, "meta": {**m, "role": "winner"}, "full": True})
        # same size as the winner, so the gap shows only what the entry and exit tuning added
        m0 = meta(s, {}, DEFAULT_EXIT, best["slots"], best["capital"])
        plain = make_cfg(args, s["rule"], DEFAULT_EXIT, best["slots"], best["capital"], full=True)
        jobs.append({"cfg": plain, "meta": {**m0, "role": "default"}, "full": True})
    run_jobs(args, 4, jobs)
    return len(jobs)


# ---- report ----------------------------------------------------------------------------------------


def pct(x, signed: bool = False) -> str:
    if x is None:
        return "–"
    return f"{x:+.1f}%" if signed else f"{x:.1f}%"


def lakh(x: float) -> str:
    return f"₹{x / 1e5:g} lakh"


def exit_words(e: dict) -> str:
    out = (f"stop-loss {e['stop']:g} ATR below the buy price; sell when the close drops below the "
           f"{e['sma']}-day average; sell after {e['days']} trading days at most")  # fmt: skip
    return out + ("; no new buys while fewer than half of all stocks are above their 200-day average"
                  if e["breadth"] else "")  # fmt: skip


def exit_short(e: dict) -> str:
    return f"stop {e['stop']:g} ATR · SMA{e['sma']} · {e['days']}d" + (" · breadth" if e["breadth"] else "")


def changes_words(s: dict, changes: dict) -> str:
    if not changes:
        return "none (the screen's own numbers were best)"
    old = {f"{operand_label(c['left'])} {c['op']}": c["right"].get("value") for c in s["rule"].get("all", [])}
    return "; ".join(f"`{k}` {old.get(k):g} → {v:g}" for k, v in changes.items())


def verdict(tr: dict, te: dict, min_trades: int) -> list[str]:
    out = []
    ex = te.get("excess")
    if ex is not None:
        out.append(f"Test period: {'beat' if ex >= 0 else 'trailed'} the Nifty 500 by {abs(ex):.1f} points a year.")
    tx = tr.get("excess")
    if tx is not None and ex is not None and tx > 0 and ex < 0.5 * tx:
        out.append("Did much worse in the test than in training: the tuning may have fitted the past (overfit).")
    if (te.get("trades") or 0) < min_trades:
        out.append(f"Only {te.get('trades') or 0} trades in the test period: too few to trust.")
    dd = te.get("max_drawdown")
    if dd is not None and dd <= -40:
        out.append(f"At its worst the account fell {abs(dd):.0f}% from a peak in the test period.")
    return out


def sizing_table(args, rows3: list[dict], w: dict) -> list[str]:
    """Training CAGR / max drawdown for each positions x capital, with the winner's entry and exits."""
    same = {(r["slots"], r["capital"]): r for r in rows3
            if r["screen"] == w["screen"] and r["exit"] == w["exit"] and r["entry_changes"] == w["entry_changes"]}  # fmt: skip
    if not same:
        return []
    caps = sorted({c for _, c in same})
    lines = ["| Max positions | " + " | ".join(lakh(c) for c in caps) + " |", "|---" * (len(caps) + 1) + "|"]
    for slots in sorted({s for s, _ in same}):
        cells = []
        for c in caps:
            r = same.get((slots, c))
            t = (r or {}).get("train") or {}
            mark = " ★" if (slots, c) == (w["slots"], w["capital"]) else ""
            cells.append(f"{pct(t.get('cagr'))} / {pct(t.get('max_drawdown'))}{mark}" if r else "–")
        lines.append(f"| {slots} | " + " | ".join(cells) + " |")
    return lines


def write_csv(args) -> None:
    cols = ["stage", "role", "screen", "name", "entry_changes", "stop_atr", "sell_below_sma", "time_stop_days",
            "breadth_filter", "max_positions", "capital", "score", "train_cagr", "train_max_dd", "train_trades",
            "train_win_rate", "train_profit_factor", "train_avg_days", "test_cagr", "test_max_dd", "test_trades",
            "test_nifty500_cagr", "error"]  # fmt: skip
    with (args.out / "all_results.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for stage in (1, 2, 3, 4):
            for r in load_stage(args, stage):
                tr, te, e = r.get("train") or {}, r.get("test") or {}, r["exit"]
                ch = "; ".join(f"{k} {v:g}" for k, v in r["entry_changes"].items())
                w.writerow([
                    stage, r.get("role", ""), r["screen"], r["name"], ch, e["stop"], e["sma"], e["days"],
                    e["breadth"], r["slots"], r["capital"], r["score"], tr.get("cagr"), tr.get("max_drawdown"),
                    tr.get("trades"), tr.get("win_rate"), tr.get("profit_factor"), tr.get("avg_days"),
                    te.get("cagr"), te.get("max_drawdown"), te.get("trades"), te.get("bench_cagr"),
                    r.get("error", ""),
                ])  # fmt: skip


def summary(args, scr: list[dict]) -> None:
    rows = [load_stage(args, k) for k in (1, 2, 3, 4)]
    if not any(rows):
        print("No results yet.")
        return
    write_csv(args)
    info, by_id = run_info(args), {s["id"]: s for s in scr}
    train_end = (date.fromisoformat(args.test_start) - timedelta(days=1)).isoformat()
    secs = sum(v.get("seconds", 0) for v in info.get("stages", {}).values())
    last_day = next((r["last_day"] for r in rows[3] if r.get("last_day")), None)
    L = [
        f"# Grid search: {args.name}",
        "",
        "## What was run",
        "",
        f"- **Started** {info.get('created', '?')}; compute time so far {secs / 60:.0f} min; code `{info.get('commit')}`.",
        "- **Stocks:** the 500 most-traded NSE stocks of each month (includes companies later delisted).",
        f"- **Training period:** {args.start} → {train_end}. Every choice below was made on these years only.",
        f"- **Test period:** {args.test_start} → {last_day or 'today'}. Looked at once, for the winners only.",
        f"- **Screens tried:** {len(scr)} ({', '.join(f'#{s['id']}' for s in scr)})."
        + (" Screens using fundamentals were left out." if args.skip_fund else ""),
        f"- **Base settings** (stages 1-2): {lakh(args.capital)} starting capital, equal money per position, "
        f"trading costs included.",
        "",
        "| Stage | What it tried | Configs |",
        "|---|---|---|",
        f"| 1 | every screen × 54 exit settings: stop-loss {'/'.join(f'{x:g}' for x in STOPS)} ATR × sell below "
        f"the {'/'.join(map(str, SMAS))}-day average × time stop {'/'.join(map(str, DAYS))} days × breadth "
        f"filter on/off × max positions {', '.join(map(str, args.slots_grid))} | {len(rows[0])} |",
        f"| 2 | best {args.top_screens} screens: each number in the screen one notch looser / as is / stricter "
        f"(up to {args.max_entry_variants} combinations each), with the screen's best exit and max positions "
        f"| {len(rows[1])} |",
        f"| 3 | best {args.top_final} screens: best entry × 54 exits × max positions "
        f"{', '.join(map(str, args.slots_grid))} × capital {', '.join(lakh(c) for c in args.capital_grid)} "
        f"| {len(rows[2])} |",
        f"| 4 | the winners over training + test, next to the untouched screen (own numbers, default exits, "
        f"same max positions and capital as the winner) | {len(rows[3])} |",
        "",
        "**How to read the numbers**",
        "",
        "- **CAGR**: average growth per year. The Nifty 500 column is the index over the same days.",
        "- **Max drawdown (DD)**: the worst fall from a peak, e.g. −30% means ₹1 lakh became ₹70,000 at the worst point.",
        f"- **Score** = CAGR ÷ |max drawdown|: growth per unit of pain. Higher is better. A config needs at least "
        f"{args.min_trades} trades in training to get a score.",
        "- **Trust the test columns more than the training ones.** Training numbers are the best of many tries, "
        f"so they look better than reality. Only forward testing is truly fresh ({args.test_start[:4]}→ has been "
        "seen before).",
    ]
    winners = sorted((r for r in rows[3] if r.get("role") == "winner"), key=lambda r: r["score"] or -1e9,
                     reverse=True)  # fmt: skip
    defaults = {r["screen"]: r for r in rows[3] if r.get("role") == "default"}
    if winners:
        L += ["", "## The winners", "",
              "| Rank | Screen | Max positions | Capital | Train CAGR | Train DD | Test CAGR | Test DD | Test trades "
              "| Nifty 500 (test) | Untouched screen, same size: test CAGR / DD |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for i, r in enumerate(winners, 1):
            tr, te = r.get("train") or {}, r.get("test") or {}
            d = (defaults.get(r["screen"]) or {}).get("test") or {}
            L.append(f"| {i} | #{r['screen']} {r['name']} | {r['slots']} | {lakh(r['capital'])} | {pct(tr.get('cagr'))} "
                     f"| {pct(tr.get('max_drawdown'))} | {pct(te.get('cagr'))} | {pct(te.get('max_drawdown'))} "
                     f"| {te.get('trades', '–')} | {pct(te.get('bench_cagr'))} "
                     f"| {pct(d.get('cagr'))} / {pct(d.get('max_drawdown'))} |")  # fmt: skip
        for i, r in enumerate(winners, 1):
            s = by_id.get(r["screen"], {"rule": {}, "desc": ""})
            tr, te = r.get("train") or {}, r.get("test") or {}
            L += ["", f"### {i}. #{r['screen']} {r['name']}", "", f"*{s['desc']}*", "",
                  f"- **Changed numbers:** {changes_words(s, r['entry_changes'])}",
                  f"- **Exits:** {exit_words(r['exit'])}",
                  f"- **Size:** at most {r['slots']} stocks at once, starting with {lakh(r['capital'])}",
                  f"- **Training:** {pct(tr.get('cagr'))} a year (Nifty 500 {pct(tr.get('bench_cagr'))}), worst fall "
                  f"{pct(tr.get('max_drawdown'))}, {tr.get('trades')} trades, {pct(tr.get('win_rate'))} winners, "
                  f"held {tr.get('avg_days')} days on average",
                  f"- **Test:** {pct(te.get('cagr'))} a year (Nifty 500 {pct(te.get('bench_cagr'))}), worst fall "
                  f"{pct(te.get('max_drawdown'))}, {te.get('trades')} trades, {pct(te.get('win_rate'))} winners"]  # fmt: skip
            L += [f"- {v}" for v in verdict(tr, te, args.min_trades)]
            if r["uses_fund"]:
                L.append("- Uses fundamentals: only as good as the Screener history that was fetched.")
            if r["screen"] in SCREEN_NOTES:
                L.append(f"- Note: {SCREEN_NOTES[r['screen']]}.")
            table = sizing_table(args, rows[2], r)
            if table:
                L += ["", "Training CAGR / max drawdown by size, same entry and exits (★ = chosen):", "", *table]
    if rows[0]:
        best1, top_ids = best_per_screen(rows[0]), {r["screen"] for r in ranked_screens(rows[0])[: args.top_screens]}
        L += ["", f"## All screens, stage 1 (training, {lakh(args.capital)})", "",
              "| Screen | Best score | Best exits | Max positions | CAGR | DD | Trades "
              f"| Default exits, {args.slots} positions: CAGR / DD | Went on? |",
              "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
        dflt = {r["screen"]: r for r in rows[0] if r["exit"] == DEFAULT_EXIT and r["slots"] == args.slots}
        order = sorted({r["screen"] for r in rows[0]}, key=lambda k: -(best1[k]["score"] if k in best1 else -1e9))
        for k in order:
            b, d = best1.get(k), (dflt.get(k) or {}).get("train") or {}
            name = next(r["name"] for r in rows[0] if r["screen"] == k)
            if b is None:
                most = max((r.get("train") or {}).get("trades") or 0 for r in rows[0] if r["screen"] == k)
                L.append(f"| #{k} {name} | – | never reached {args.min_trades} trades (most: {most}) | | | | | "
                         f"{pct(d.get('cagr'))} / {pct(d.get('max_drawdown'))} | no |")  # fmt: skip
                continue
            t = b["train"]
            L.append(f"| #{k} {name} | {b['score']:.2f} | {exit_short(b['exit'])} | {b['slots']} | {pct(t.get('cagr'))} "
                     f"| {pct(t.get('max_drawdown'))} | {t.get('trades')} | {pct(d.get('cagr'))} / "
                     f"{pct(d.get('max_drawdown'))} | {'yes' if k in top_ids else 'no'} |")  # fmt: skip
    errors = sum(1 for rs in rows for r in rs if r.get("error"))
    if errors:
        L += ["", f"**{errors} configs failed** (see the `error` column in all_results.csv)."]
    L += ["", "Files: `all_results.csv` (every config, for a spreadsheet), `stageN.wK.jsonl` (raw), `run.json` (settings)."]
    (args.out / "summary.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nSaved {args.out / 'summary.md'} and {args.out / 'all_results.csv'}")


# ---- main ------------------------------------------------------------------------------------------


def list_runs(root: Path) -> None:
    runs = sorted(p for p in root.glob("*") if p.is_dir()) if root.exists() else []
    if not runs:
        print(f"No saved runs in {root}")
    for p in runs:
        size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        n = sum(len(load_stage(None, k, p)) for k in (1, 2, 3, 4))
        created = json.loads((p / "run.json").read_text()).get("created", "?") if (p / "run.json").exists() else "?"
        print(f"  {p.name:<20} started {created}  {n} results  {size / 1e6:.1f} MB")


def delete_run(args) -> int:
    if not args.out.exists():
        print(f"Nothing to delete: {args.out} does not exist.")
        return 0
    files = sorted(f for f in args.out.rglob("*") if f.is_file())
    print(f"This deletes {args.out}:")
    for f in files:
        print(f"  {f.name}  ({f.stat().st_size / 1e3:.0f} KB)")
    if not args.yes and input("Delete these files? [y/N] ").strip().lower() != "y":
        print("Kept.")
        return 1
    shutil.rmtree(args.out)
    print("Deleted.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stage", choices=["1", "2", "3", "4", "all"], default="all")
    ap.add_argument("--name", default="run1", help="results folder under data/grid/ (default run1)")
    ap.add_argument("--workers", type=int, default=3, help="worker processes, ~750 MB RAM each (default 3)")
    ap.add_argument("--capital", type=float, default=100_000, help="base capital, stages 1-2 (default 1 lakh)")
    ap.add_argument("--slots", type=int, default=3, help="max positions for the stage 1 'default exits' column (default 3)")
    ap.add_argument("--slots-grid", type=int, nargs="+", default=list(range(3, 11)),
                    help="max positions tried in stages 1 and 3 (default 3 4 5 6 7 8 9 10)")  # fmt: skip
    ap.add_argument("--capital-grid", type=float, nargs="+", default=[1e5, 2e5, 3e5, 4e5, 5e5],
                    help="starting capital tried in stage 3 (default 1-5 lakh)")  # fmt: skip
    ap.add_argument("--start", default="2012-01-01")
    ap.add_argument("--test-start", default="2022-01-01")
    ap.add_argument("--min-trades", type=int, default=30)
    ap.add_argument("--top-screens", type=int, default=8, help="screens taken into stage 2 (default 8)")
    ap.add_argument("--top-final", type=int, default=5, help="screens taken into stages 3-4 (default 5)")
    ap.add_argument("--max-entry-variants", type=int, default=243, help="per screen in stage 2 (default 243)")
    ap.add_argument("--screens", type=int, nargs="*", help="only these screen ids")
    ap.add_argument("--skip-fund", action="store_true", help="leave out screens that use fundamentals")
    ap.add_argument("--dry-run", action="store_true", help="print config counts per stage, then stop")
    ap.add_argument("--summary", action="store_true", help="only rebuild summary.md and all_results.csv")
    ap.add_argument("--list", action="store_true", help="list saved runs")
    ap.add_argument("--delete", action="store_true", help="delete this run's output folder (asks first)")
    ap.add_argument("--yes", action="store_true", help="with --delete: don't ask")
    args = ap.parse_args()

    warnings.filterwarnings("ignore")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    from app import config

    root = config.DATA_DIR / "grid"
    args.out = root / args.name
    if args.list:
        list_runs(root)
        return 0
    if args.delete:
        return delete_run(args)

    from app.plugins import import_all

    for pkg in ("app.sources.adapters", "app.jobs.defs", "app.alerts.scanners"):
        import_all(pkg)
    scr = screens(args)
    print(f"{len(scr)} screens: {', '.join(f'#{s['id']}' for s in scr)}  ->  results in {args.out}")
    stages = {"1": stage1, "2": stage2, "3": stage3, "4": stage4}
    chosen = list(stages) if args.stage == "all" else [args.stage]
    if args.dry_run:
        for k in chosen:
            print(f"  stage {k}: {'up to ' if k == '2' else ''}{stages[k](args, scr, True)} configs")
        return 0
    if args.summary:
        summary(args, scr)
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    check_settings(args)
    for k in chosen:
        stages[k](args, scr, False)
    summary(args, scr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped. Finished results are saved; run the same command again to resume.")
        sys.exit(130)
