"""Screens API (SPEC §10). Shortlist, score and backtest endpoints come with later tickets."""

import json
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import db, timeutil
from app.analytics import calendar, indicators, rules, score, screens
from app.jobs import runner

router = APIRouter()


class ScreenIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = None
    rule: dict


class PreviewIn(BaseModel):
    rule: dict


@router.get("/indicators")
def list_indicators() -> list[dict]:
    return indicators.catalogue()


@router.get("/rules/ops")
def list_ops() -> list[dict]:
    return [{"name": o.name, "words": o.words} for o in rules.OPS.values()]


@router.post("/rules/describe")
def describe_rule(rule: dict) -> dict:
    try:
        r = rules.validate_rule(rule)
    except rules.RuleError as e:
        raise HTTPException(400, str(e)) from None
    return {"text": rules.describe(r), "uses_fundamentals": rules.uses_fundamentals(r)}


def _describe(rule: dict) -> str:
    try:
        return rules.describe(rules.validate_rule(rule))
    except rules.RuleError as e:
        return f"(invalid rule: {e})"


def _screen(row: sqlite3.Row, last_run: str | None = None, count: int = 0) -> dict:
    rule = json.loads(row["rule"])
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "rule": rule,
        "describe": _describe(rule),
        "is_preset": bool(row["is_preset"]),
        "created_by": row["created_by"],
        "last_run_as_of": last_run,
        "count": count,
    }


def _get(c: sqlite3.Connection, screen_id: int) -> sqlite3.Row:
    row = c.execute("SELECT * FROM screens WHERE id=?", (screen_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no screen {screen_id}")
    return row


def _full(c: sqlite3.Connection, screen_id: int) -> dict:
    row = _get(c, screen_id)
    last, n = c.execute(
        "SELECT MAX(as_of), COUNT(*) FROM screen_results WHERE screen_id=?", (screen_id,)
    ).fetchone()
    return _screen(row, _latest(last, screens.last_runs(c).get(str(screen_id))), n)


def _latest(*dates: str | None) -> str | None:
    return max((d for d in dates if d), default=None)


def _check(body: ScreenIn) -> None:
    try:
        rules.validate_rule(body.rule)
    except rules.RuleError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/screens")
def list_screens() -> list[dict]:
    with db.tx() as c:
        stats = {
            r["screen_id"]: (r["last"], r["n"])
            for r in c.execute(
                "SELECT screen_id, MAX(as_of) AS last, COUNT(*) AS n FROM screen_results GROUP BY screen_id"
            )
        }
        rows = c.execute("SELECT * FROM screens ORDER BY is_preset DESC, id").fetchall()
        ran = screens.last_runs(c)
    out = []
    for r in rows:
        last, n = stats.get(r["id"], (None, 0))
        out.append(_screen(r, _latest(last, ran.get(str(r["id"]))), n))
    return out


@router.post("/screens")
def create_screen(body: ScreenIn) -> dict:
    _check(body)
    now = timeutil.now_iso()
    with db.tx() as c:
        try:
            cur = c.execute(
                "INSERT INTO screens(name, description, rule, is_preset, created_by, created_at, updated_at) "
                "VALUES (?,?,?,0,'user',?,?)",
                (body.name.strip(), body.description, json.dumps(body.rule), now, now),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(400, f"a screen named '{body.name}' already exists") from None
        return _full(c, cur.lastrowid)


@router.post("/screens/preview")
def preview_screen(body: PreviewIn) -> dict:
    try:
        return screens.preview(body.rule)
    except ValueError as e:  # RuleError (with its JSON path) and TooSlow
        raise HTTPException(400, str(e)) from None


@router.put("/screens/{screen_id}")
def update_screen(screen_id: int, body: ScreenIn) -> dict:
    _check(body)
    with db.tx() as c:
        _get(c, screen_id)
        try:
            c.execute(
                "UPDATE screens SET name=?, description=?, rule=?, updated_at=? WHERE id=?",
                (body.name.strip(), body.description, json.dumps(body.rule), timeutil.now_iso(), screen_id),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(400, f"a screen named '{body.name}' already exists") from None
        return _full(c, screen_id)


@router.delete("/screens/{screen_id}")
def delete_screen(screen_id: int) -> dict:
    with db.tx() as c:
        if _get(c, screen_id)["is_preset"]:
            raise HTTPException(400, "built-in screens can't be deleted")
        c.execute("DELETE FROM screens WHERE id=?", (screen_id,))
    return {"ok": True}


@router.post("/screens/{screen_id}/run")
def run_screen_now(screen_id: int) -> dict:
    with db.tx() as c:
        _get(c, screen_id)
    return {"run_id": runner.enqueue("screens_run", params={"screen_ids": [screen_id]}, trigger="manual")}


@router.get("/screens/{screen_id}/results")
def screen_results(screen_id: int) -> list[dict]:
    with db.tx() as c:
        _get(c, screen_id)
        rows = c.execute(
            "SELECT r.symbol, s.name, r.values_json, r.first_seen FROM screen_results r "
            "LEFT JOIN symbols s ON s.symbol = r.symbol WHERE r.screen_id=? ORDER BY r.symbol",
            (screen_id,),
        ).fetchall()
    ranked = {c["symbol"]: c for c in score.score_candidates()} if rows else {}
    return [
        {
            "symbol": r["symbol"],
            "name": r["name"],
            "values": json.loads(r["values_json"]),
            "first_seen": r["first_seen"],
            "score": ranked[r["symbol"]]["score"] if r["symbol"] in ranked else None,
            "reasons": ranked[r["symbol"]]["reasons"] if r["symbol"] in ranked else None,
        }
        for r in rows
    ]


@router.get("/shortlist")
def shortlist(limit: int = 20) -> list[dict]:
    items = score.score_candidates()[: max(1, limit)]
    with db.tx() as c:
        upcoming = calendar.next_results(c, [i["symbol"] for i in items])
    return [{**i, "next_results": upcoming.get(i["symbol"])} for i in items]


@router.get("/score/components")
def score_components() -> list[dict]:
    weights = db.get_setting("score_weights")
    return [
        {"name": c.name, "label": c.label, "explain": c.explain, "weight": weights.get(c.name, 0)}
        for c in score.COMPONENTS.values()
    ]
