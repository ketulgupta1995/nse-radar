"""Custom indicators API (SPEC §8.3). Code runs only inside `approve`."""

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db, timeutil
from app.analytics import custom_indicators as ci

log = logging.getLogger(__name__)
router = APIRouter()


class CustomIn(BaseModel):
    name: str
    params_schema: list[dict] = []
    explain: str
    code: str


def _out(row, **extra) -> dict:
    d = dict(row)
    d["params_schema"] = json.loads(d["params_schema"])
    d["problems"] = ci.static_check(d["code"])
    return d | extra


def _get_row(conn, cid: int):
    row = conn.execute("SELECT * FROM custom_indicators WHERE id=?", (cid,)).fetchone()
    if row is None:
        raise HTTPException(404, "No such custom indicator")
    return row


def _uses(node, name: str) -> bool:
    if isinstance(node, dict):
        return node.get("ind") == name or any(_uses(v, name) for v in node.values())
    if isinstance(node, list):
        return any(_uses(v, name) for v in node)
    return False


@router.post("/custom-indicators")
def create(body: CustomIn) -> dict:
    """Store as pending. Only parses the code (static_check); never runs it."""
    if err := ci.validate_name(body.name):
        raise HTTPException(400, err)
    try:
        ci.validate_params_schema(body.params_schema)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    if not body.explain.strip() or len(body.explain) > 140:
        raise HTTPException(400, "The explanation must be 1-140 characters.")
    with db.tx() as c:
        if c.execute("SELECT 1 FROM custom_indicators WHERE name=?", (body.name,)).fetchone():
            raise HTTPException(400, f"A custom indicator called '{body.name}' already exists.")
        cur = c.execute(
            "INSERT INTO custom_indicators (name, params_schema, explain, code, status, created_at) "
            "VALUES (?,?,?,?, 'pending', ?)",
            (body.name, json.dumps(body.params_schema), body.explain.strip(), body.code, timeutil.now_iso()),
        )
        return _out(_get_row(c, cur.lastrowid))


@router.get("/custom-indicators")
def list_all() -> list[dict]:
    with db.tx() as c:
        return [_out(r) for r in c.execute("SELECT * FROM custom_indicators ORDER BY id DESC")]


@router.post("/custom-indicators/{cid}/approve")
def approve(cid: int) -> dict:
    with db.tx() as c:
        row = _get_row(c, cid)
    if row["status"] != "pending":
        raise HTTPException(400, f"This indicator is already {row['status']}.")
    if problems := ci.static_check(row["code"]):
        raise HTTPException(400, "; ".join(problems))
    schema = json.loads(row["params_schema"])
    try:
        parsed = ci.validate_params_schema(schema)
        defaults = {p.name: int(p.default) if p.kind == "int" else p.default for p in parsed}
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    trial = ci.trial_run(row["code"], defaults)
    if not trial.get("ok"):
        raise HTTPException(400, trial.get("error", "The trial run failed."))
    with db.tx() as c:
        c.execute(
            "UPDATE custom_indicators SET status='approved', approved_at=? WHERE id=?",
            (timeutil.now_iso(), cid),
        )
        fresh = dict(_get_row(c, cid))
    fresh["params_schema"] = schema
    try:
        ci.register_row(fresh)
    except ValueError as e:
        with db.tx() as c:
            c.execute("UPDATE custom_indicators SET status='pending', approved_at=NULL WHERE id=?", (cid,))
        raise HTTPException(400, str(e)) from None
    with db.tx() as c:
        return _out(_get_row(c, cid), sample=trial["sample"])


@router.post("/custom-indicators/{cid}/reject")
def reject(cid: int) -> dict:
    with db.tx() as c:
        row = _get_row(c, cid)
        c.execute("UPDATE custom_indicators SET status='rejected', approved_at=NULL WHERE id=?", (cid,))
        out = _out(_get_row(c, cid))
    ci.unregister_custom(row["name"])
    return out


@router.delete("/custom-indicators/{cid}")
def delete(cid: int) -> dict:
    with db.tx() as c:
        row = _get_row(c, cid)
        for s in c.execute("SELECT name, rule FROM screens"):
            try:
                used = _uses(json.loads(s["rule"]), row["name"])
            except ValueError:
                used = False
            if used:
                raise HTTPException(400, f"The screen '{s['name']}' uses this indicator.")
        c.execute("DELETE FROM custom_indicators WHERE id=?", (cid,))
    ci.unregister_custom(row["name"])
    return {"deleted": cid}
