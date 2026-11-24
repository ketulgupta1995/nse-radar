"""Backtests API (SPEC §12.4)."""

import json
import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from app import db, timeutil
from app.backtest import exits, metrics
from app.backtest.engine import BacktestConfig
from app.jobs import runner

router = APIRouter()


class BacktestIn(BaseModel):
    name: str | None = None
    config: dict


class BatchIn(BaseModel):
    name: str | None = None
    configs: list[dict]
    names: list[str] | None = None  # T119: one row name per config


class ScreenBacktestIn(BaseModel):
    name: str | None = None
    config: dict = {}  # optional overrides (exits, max_positions, ...); the entry rule is the screen's


def _day_before(d: str) -> str:
    return (date.fromisoformat(d) - timedelta(days=1)).isoformat()


def _check_dates(cfg: BacktestConfig) -> None:
    """Training = start .. day before oos_start; test = oos_start .. end (SPEC §12.6)."""
    try:
        start, oos = date.fromisoformat(cfg.start), date.fromisoformat(cfg.oos_start or "")
        end = date.fromisoformat(cfg.end) if cfg.end else None
    except ValueError:
        raise HTTPException(400, "Dates must look like 2022-01-01.") from None
    if start >= oos:
        raise HTTPException(400, "The training period must start before the test period begins.")
    if end is not None and end <= oos:
        raise HTTPException(400, "The end date must be after the test period begins.")


def _insert(name: str | None, cfg_json: str, kind: str, parent_id: int | None = None,
            fingerprint: str | None = None, metrics: dict | None = None) -> dict:  # fmt: skip
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO backtests(name, config, status, kind, parent_id, fingerprint, metrics, created_at) "
            "VALUES (?,?,'queued',?,?,?,?,?)",
            (name, cfg_json, kind, parent_id, fingerprint, json.dumps(metrics) if metrics else None,
             timeutil.now_iso()),
        )  # fmt: skip
        bid = int(cur.lastrowid)
    run_id = runner.enqueue("backtest", params={"backtest_id": bid})
    with db.tx() as c:
        c.execute("UPDATE backtests SET run_id=? WHERE id=?", (run_id, bid))
    return {"id": bid, "run_id": run_id}


def _validate(config: dict) -> BacktestConfig:
    try:
        cfg = BacktestConfig(**config)
    except (ValidationError, TypeError) as e:
        raise HTTPException(400, str(e)) from None
    if not cfg.oos_start:  # resolved now and stored, so a later settings change never rewrites history
        cfg.oos_start = db.get_setting("holdout_start")
    _check_dates(cfg)
    return cfg


def _create(name: str | None, config: dict) -> dict:
    return _insert(name, _validate(config).model_dump_json(), "explore")


MAX_BATCH = 20


@router.post("/backtests/batch")
def create_batch(body: BatchIn) -> dict:
    if not 1 <= len(body.configs) <= MAX_BATCH:
        raise HTTPException(400, f"A batch needs between 1 and {MAX_BATCH} configs.")
    if body.names is not None and len(body.names) != len(body.configs):
        raise HTTPException(400, "names must have the same length as configs.")
    cfgs = []
    for i, config in enumerate(body.configs):
        try:
            cfgs.append(_validate(config))
        except HTTPException as e:
            raise HTTPException(400, f"Config {i}: {e.detail}") from None
    ids = []
    with db.tx() as c:
        for n, cfg in enumerate(cfgs, 1):
            if body.names is not None:
                row_name = body.names[n - 1] or None
            else:
                row_name = f"{body.name} #{n}" if body.name else None
            cur = c.execute(
                "INSERT INTO backtests(name, config, status, kind, created_at) "
                "VALUES (?,?,'queued','explore',?)",
                (row_name, cfg.model_dump_json(), timeutil.now_iso()),
            )
            ids.append(int(cur.lastrowid))
    run_id = runner.enqueue("backtest_batch", params={"backtest_ids": ids})
    with db.tx() as c:
        c.executemany("UPDATE backtests SET run_id=? WHERE id=?", [(run_id, i) for i in ids])
    return {"ids": ids, "run_id": run_id}


def _window(cfg: dict, kind: str) -> tuple[str, str]:
    """Calendar window a run covers: test period for a final, training period otherwise."""
    today = str(timeutil.today())
    oos = cfg.get("oos_start")
    if kind == "final":
        return oos or "", cfg.get("end") or today
    return cfg.get("start") or "", _day_before(oos) if oos else cfg.get("end") or today


def _overlap(a: tuple[str, str], b: tuple[str, str]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


@router.post("/backtests/{backtest_id}/final")
def final_test(backtest_id: int) -> dict:
    with db.tx() as c:
        row = c.execute("SELECT * FROM backtests WHERE id=?", (backtest_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such backtest")
        if row["kind"] != "explore" or row["status"] != "done":
            raise HTTPException(400, "Only a finished training-period backtest can get a final test.")
        cfg = json.loads(row["config"])
        fp = metrics.fingerprint(cfg)
        mine = _window(cfg, "final")
        earlier = c.execute("SELECT id, config, fingerprint FROM backtests WHERE kind='final'").fetchall()
    attempt = 1 + sum(_overlap(mine, _window(json.loads(r["config"]), "final")) for r in earlier)
    warns = []
    if attempt > 1:
        warns.append(
            f"The test period has been looked at {attempt - 1} time(s) before by other final tests. "
            "Each look makes it a weaker check."
        )
    same = next((r["id"] for r in earlier if r["fingerprint"] == fp), None)
    if same is not None:
        warns.append(
            f"This exact strategy already had a final test (#{same}). "
            "Running it again does not make the result more reliable."
        )
    pending = {"attempt": attempt, "final_warnings": warns}
    out = _insert((row["name"] or f"Backtest {backtest_id}") + " (final)", row["config"], "final",
                  backtest_id, fp, pending)  # fmt: skip
    return {**out, "attempt": attempt}


@router.post("/backtests")
def create_backtest(body: BacktestIn) -> dict:
    return _create(body.name, body.config)


@router.get("/backtests/exits")
def list_exits() -> list[dict]:
    return exits.catalogue()


def _explore_counts(c: sqlite3.Connection) -> dict[int, int]:
    """id -> number of explore rows created up to it whose training window overlaps its own."""
    rows = c.execute("SELECT id, kind, config FROM backtests ORDER BY id").fetchall()
    wins = [(r["id"], r["kind"] == "explore", _window(json.loads(r["config"]), "explore")) for r in rows]
    return {
        i: sum(1 for j, is_explore, w2 in wins if is_explore and j <= i and _overlap(w, w2))
        for i, _, w in wins
    }


def _load(r: sqlite3.Row | None, explore_runs: int = 0) -> dict:
    if r is None:
        raise HTTPException(404, "no such backtest")
    cols = ("id", "name", "status", "kind", "parent_id", "run_id", "created_at", "finished_at")
    out = {k: r[k] for k in cols}
    out["config"] = json.loads(r["config"])
    for k in ("metrics", "equity", "trades", "warnings"):
        out[k] = json.loads(r[k]) if r[k] else None
    out["explore_runs"] = explore_runs
    out["attempt"] = (out["metrics"] or {}).get("attempt") if r["kind"] == "final" else None
    if out["metrics"]:
        out["metrics"].pop("final_warnings", None)
    return out


def _brief(m: dict | None) -> dict | None:
    return None if m is None else {"cagr": m.get("cagr"), "excess": m.get("excess")}


@router.get("/backtests")
def list_backtests() -> list[dict]:
    with db.tx() as c:
        rows = c.execute(
            "SELECT id, name, status, kind, parent_id, created_at, finished_at, metrics "
            "FROM backtests ORDER BY id DESC"
        ).fetchall()
    out = []
    for r in rows:
        m = json.loads(r["metrics"]) if r["metrics"] else {}
        out.append({
            "id": r["id"], "name": r["name"], "status": r["status"], "kind": r["kind"],
            "parent_id": r["parent_id"], "created_at": r["created_at"], "finished_at": r["finished_at"],
            "metrics": {"is": _brief(m.get("is")), "oos": _brief(m.get("oos"))} if m else None,
        })  # fmt: skip
    return out


@router.get("/backtests/{backtest_id}")
def get_backtest(backtest_id: int) -> dict:
    with db.tx() as c:
        row = c.execute("SELECT * FROM backtests WHERE id=?", (backtest_id,)).fetchone()
        return _load(row, _explore_counts(c).get(backtest_id, 0) if row else 0)


@router.delete("/backtests/{backtest_id}")
def delete_backtest(backtest_id: int) -> dict:
    with db.tx() as c:
        if c.execute("DELETE FROM backtests WHERE id=?", (backtest_id,)).rowcount == 0:
            raise HTTPException(404, "no such backtest")
    return {"ok": True}


@router.post("/screens/{screen_id}/backtest")
def backtest_screen(screen_id: int, body: ScreenBacktestIn | None = None) -> dict:
    body = body or ScreenBacktestIn()
    with db.tx() as c:
        row = c.execute("SELECT name, rule FROM screens WHERE id=?", (screen_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such screen")
    config = {**body.config, "entry_rule": json.loads(row["rule"])}
    return _create(body.name or row["name"], config)
