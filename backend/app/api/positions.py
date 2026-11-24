"""Positions, checklists, sizing suggestions and journal statistics (SPEC §13.1)."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import db, timeutil
from app.analytics import calendar, frames, indicators

router = APIRouter()
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PRESET = Path(__file__).resolve().parents[1] / "presets" / "checklist.json"


@lru_cache(maxsize=1)
def _questions() -> dict:
    return json.loads(PRESET.read_text())


def _check_date(value: str, name: str) -> str:
    try:
        if not _DATE.match(value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"{name}: must be a date like 2026-11-06") from None
    return value


# ---- checklist validation --------------------------------------------------------------------


def validate_answers(kind: str, answers: dict[str, Any]) -> dict[str, Any]:
    """Return cleaned answers, or raise 400 listing the missing / invalid / must-be-true ids."""
    missing: list[str] = []
    invalid: list[str] = []
    not_true: list[str] = []
    clean: dict[str, Any] = {}
    for q in _questions()[kind]:
        qid, raw = q["id"], answers.get(q["id"])
        empty = raw is None or (isinstance(raw, str) and not raw.strip())
        if q["type"] == "bool":
            if q.get("must_be_true"):
                if raw is not True:
                    not_true.append(qid)
                    continue
            elif raw is None and q["required"]:
                missing.append(qid)
                continue
        elif empty:
            if q["required"]:
                missing.append(qid)
            continue
        if raw is None:
            continue
        if q["type"] == "number":
            is_num = isinstance(raw, (int, float)) and not isinstance(raw, bool)
            if not is_num or not math.isfinite(raw) or raw <= 0:
                invalid.append(qid)
                continue
            clean[qid] = float(raw)
        elif q["type"] == "choice":
            if raw not in q["choices"]:
                invalid.append(qid)
                continue
            clean[qid] = raw
        elif q["type"] == "bool":
            clean[qid] = raw is True
        else:
            clean[qid] = str(raw).strip()
    parts = []
    if missing:
        parts.append(f"missing: {', '.join(missing)}")
    if not_true:
        parts.append(f"must be ticked: {', '.join(not_true)}")
    if invalid:
        parts.append(f"invalid: {', '.join(invalid)}")
    if parts:
        raise HTTPException(400, "; ".join(parts))
    return clean


# ---- sizing ----------------------------------------------------------------------------------


def _atr14(frame) -> float | None:
    if len(frame) < 2:
        return None
    v = indicators.compute("atr", frame, n=14).iloc[-1]
    return None if math.isnan(v) else float(v)


def suggest(symbol: str, entry: float | None = None, stop: float | None = None) -> dict:
    symbol = symbol.upper()
    frame = frames.load_frame(symbol)
    last = float(frame["close"].iloc[-1]) if len(frame) else None
    entry = entry if entry is not None else last
    if entry is None:
        raise HTTPException(400, f"No prices for {symbol}; give an entry price")
    atr = _atr14(frame)
    with db.tx() as c:
        capital = float(db.get_setting("capital_inr", c))
        risk_pct = float(db.get_setting("risk_per_trade_pct", c))
        k = float(db.get_setting("atr_stop_multiple", c))
        upcoming = calendar.next_results(c, [symbol]).get(symbol)
    suggested_stop = round(entry - k * atr, 2) if atr is not None else None
    use_stop = stop if stop is not None else suggested_stop
    risk_share = entry - use_stop if use_stop is not None and entry > use_stop else None
    qty = math.floor(capital * risk_pct / 100 / risk_share) if risk_share else 0
    target = round(entry + 2 * risk_share, 2) if risk_share else None
    return {
        "last_close": last,
        "atr14": atr,
        "suggested_stop": suggested_stop,
        "suggested_target": target,
        "risk_per_share": round(risk_share, 2) if risk_share else None,
        "qty": qty,
        "capital": capital,
        "risk_pct": risk_pct,
        "rr": round((target - entry) / risk_share, 2) if risk_share and target else None,
        "next_results": upcoming,
    }


@router.get("/positions/checklist/questions")
def checklist_questions() -> dict:
    return _questions()


@router.get("/positions/suggest")
def get_suggest(symbol: str, entry: float | None = None, stop: float | None = None) -> dict:
    return suggest(symbol, entry, stop)


# ---- positions -------------------------------------------------------------------------------


class PositionIn(BaseModel):
    symbol: str = Field(min_length=1)
    qty: int = Field(gt=0)
    entry_date: str
    answers: dict[str, Any]
    ai_review: Any = None


class CloseIn(BaseModel):
    exit_date: str
    answers: dict[str, Any]


class PositionPatch(BaseModel):
    stop: float | None = Field(default=None, gt=0)
    target: float | None = Field(default=None, gt=0)
    time_stop_date: str | None = None


def _review(v: Any) -> str | None:
    return None if v is None else v if isinstance(v, str) else json.dumps(v)


def _checklist_answers(c: sqlite3.Connection, rows: list[sqlite3.Row]) -> dict[int, dict]:
    """{checklist id: answers} for the entry and exit checklists of `rows`, in one query."""
    ids = sorted({i for r in rows for i in (r["entry_checklist_id"], r["exit_checklist_id"]) if i})
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    found = c.execute(f"SELECT id, answers FROM checklists WHERE id IN ({marks})", ids).fetchall()
    return {r["id"]: json.loads(r["answers"]) for r in found}


def _initial_stop(row: sqlite3.Row, answers: dict[int, dict]) -> float | None:
    """Risk is measured against the stop chosen at entry, even if the stop was trailed later."""
    stop = answers.get(row["entry_checklist_id"] or 0, {}).get("stop")
    return float(stop) if stop else row["stop"]


def _upcoming(rows: list[tuple[dict, float | None]]) -> dict[str, dict]:
    """Next results date for the open positions among `rows`, in one query."""
    symbols = sorted({p["symbol"] for p, _ in rows if p["status"] == "open"})
    if not symbols:
        return {}
    with db.tx() as c:
        return calendar.next_results(c, symbols)


def _closes(rows: list[tuple[dict, float | None]]) -> dict[str, float | None]:
    """Latest close of every open position among `rows`: batched key seeks, no frames (SPEC §17.5)."""
    return frames.latest_closes({p["symbol"] for p, _ in rows if p["status"] == "open"})


def _decorate(
    p: dict, init: float | None, upcoming: dict[str, dict] | None = None, closes: dict | None = None
) -> dict:
    today = timeutil.today()
    closed = p["status"] == "closed"
    last = p["exit_price"] if closed else (closes or {}).get(p["symbol"])
    entry, stop, target, qty = p["entry_price"], p["stop"], p["target"], p["qty"]
    risk = None
    if init is not None and entry > init:
        risk = entry - init
    end = date.fromisoformat(p["exit_date"]) if closed and p["exit_date"] else today
    p.update(
        last_close=last,
        pnl_inr=round((last - entry) * qty, 2) if last is not None else None,
        pnl_pct=round((last / entry - 1) * 100, 2) if last is not None else None,
        r_multiple=round((last - entry) / risk, 2) if last is not None and risk else None,
        to_stop_pct=round((last / stop - 1) * 100, 2) if last is not None and stop and not closed else None,
        to_target_pct=round((target / last - 1) * 100, 2) if last and target and not closed else None,
        days_held=(end - date.fromisoformat(p["entry_date"])).days,
        days_to_time_stop=(date.fromisoformat(p["time_stop_date"]) - today).days
        if p["time_stop_date"] and not closed
        else None,
        next_results=(upcoming or {}).get(p["symbol"]) if not closed else None,
    )
    return p


def _fetch(where: str, args: tuple = (), order: str = "id") -> list[tuple[dict, float | None]]:
    """Rows plus each one's entry stop. Read in one short transaction; price frames are loaded after it."""
    with db.tx() as c:
        rows = c.execute(f"SELECT * FROM positions WHERE {where} ORDER BY {order}", args).fetchall()
        answers = _checklist_answers(c, rows)
    return [(dict(r), _initial_stop(r, answers)) for r in rows]


def _view(pid: int) -> dict:
    found = _fetch("id=?", (pid,))
    if not found:
        raise HTTPException(404, f"No position {pid}")
    return _decorate(*found[0], _upcoming(found), _closes(found))


def _get(c: sqlite3.Connection, pid: int) -> sqlite3.Row:
    row = c.execute("SELECT * FROM positions WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"No position {pid}")
    return row


@router.post("/positions")
def create_position(body: PositionIn) -> dict:
    _check_date(body.entry_date, "entry_date")
    answers = validate_answers("entry", body.answers)
    symbol = body.symbol.strip().upper()
    now = timeutil.now().isoformat()
    weeks = answers["time_stop_weeks"]
    time_stop = (date.fromisoformat(body.entry_date) + timedelta(days=round(weeks * 7))).isoformat()
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO checklists(kind, symbol, answers, ai_review, created_at) VALUES ('entry',?,?,?,?)",
            (symbol, json.dumps(answers), _review(body.ai_review), now),
        )
        pid = c.execute(
            "INSERT INTO positions(symbol, qty, entry_date, entry_price, stop, target, time_stop_date, "
            "entry_checklist_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (symbol, body.qty, body.entry_date, answers["entry_price"], answers["stop"], answers["target"],
             time_stop, cur.lastrowid, now),
        ).lastrowid  # fmt: skip
    return _view(pid)


@router.get("/positions")
def list_positions(status: str = "open") -> list[dict]:
    if status not in ("open", "closed"):
        raise HTTPException(400, "status must be open or closed")
    order = "entry_date DESC, id DESC" if status == "open" else "exit_date DESC, id DESC"
    found = _fetch("status=?", (status,), order)
    upcoming, closes = _upcoming(found), _closes(found)
    return [_decorate(p, init, upcoming, closes) for p, init in found]


@router.post("/positions/{pid}/close")
def close_position(pid: int, body: CloseIn) -> dict:
    _check_date(body.exit_date, "exit_date")
    answers = validate_answers("exit", body.answers)
    with db.tx() as c:
        row = _get(c, pid)
        if row["status"] != "open":
            raise HTTPException(400, f"Position {pid} is already closed")
        if body.exit_date < row["entry_date"]:
            raise HTTPException(400, "exit_date: is before the entry date")
        cur = c.execute(
            "INSERT INTO checklists(kind, symbol, answers, created_at) VALUES ('exit',?,?,?)",
            (row["symbol"], json.dumps(answers), timeutil.now().isoformat()),
        )
        c.execute(
            "UPDATE positions SET status='closed', exit_date=?, exit_price=?, exit_reason=?, "
            "exit_checklist_id=? WHERE id=?",
            (body.exit_date, answers["exit_price"], answers["exit_reason"], cur.lastrowid, pid),
        )
    return _view(pid)


@router.put("/positions/{pid}")
def update_position(pid: int, body: PositionPatch) -> dict:
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if "time_stop_date" in changes:
        _check_date(changes["time_stop_date"], "time_stop_date")
    with db.tx() as c:
        row = _get(c, pid)
        if row["status"] != "open":
            raise HTTPException(400, f"Position {pid} is closed")
        if changes:
            sets = ", ".join(f"{k}=?" for k in changes)
            c.execute(f"UPDATE positions SET {sets} WHERE id=?", (*changes.values(), pid))
    return _view(pid)


@router.get("/positions/{pid}/checklists")
def position_checklists(pid: int) -> list[dict]:
    with db.tx() as c:
        row = _get(c, pid)
        ids = [i for i in (row["entry_checklist_id"], row["exit_checklist_id"]) if i]
        out = []
        for cid in ids:
            r = c.execute("SELECT * FROM checklists WHERE id=?", (cid,)).fetchone()
            out.append({**dict(r), "answers": json.loads(r["answers"])})
        return out


# ---- journal ---------------------------------------------------------------------------------


def _group(rows: list[dict], key: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in sorted({r[key] for r in rows if r[key]}):
        sub = [r for r in rows if r[key] == name]
        rs = [r["r"] for r in sub if r["r"] is not None]
        out[name] = {
            "n": len(sub),
            "win_rate": round(sum(r["win"] for r in sub) / len(sub) * 100, 1),
            "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
        }
    return out


@router.get("/journal/stats")
def journal_stats() -> dict:
    with db.tx() as c:
        rows = c.execute("SELECT * FROM positions WHERE status='closed'").fetchall()
        answers = _checklist_answers(c, rows)
        recs = []
        for p in rows:
            init = _initial_stop(p, answers)
            risk = p["entry_price"] - init if init is not None and p["entry_price"] > init else None
            ret = (p["exit_price"] / p["entry_price"] - 1) * 100
            entry_ans = answers.get(p["entry_checklist_id"] or 0, {})
            exit_ans = answers.get(p["exit_checklist_id"] or 0, {})
            recs.append({
                "win": p["exit_price"] > p["entry_price"], "ret": ret,
                "r": (p["exit_price"] - p["entry_price"]) / risk if risk else None,
                "reason": p["exit_reason"], "emotion": entry_ans.get("emotion"),
                "thesis": exit_ans.get("thesis_right"),
            })  # fmt: skip
    n = len(recs)
    wins = [r["ret"] for r in recs if r["win"]]
    losses = [r["ret"] for r in recs if not r["win"]]
    rs = [r["r"] for r in recs if r["r"] is not None]
    thesis = [r["thesis"] for r in recs if r["thesis"]]

    def avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 2) if xs else None

    return {
        "closed": n,
        "win_rate": round(len(wins) / n * 100, 1) if n else None,
        "avg_r": avg(rs),
        "avg_win_pct": avg(wins),
        "avg_loss_pct": avg(losses),
        "thesis_right_pct": round(thesis.count("yes") / len(thesis) * 100, 1) if thesis else None,
        "by_exit_reason": _group(recs, "reason"),
        "by_emotion": _group(recs, "emotion"),
    }
