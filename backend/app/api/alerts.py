"""Alerts API (SPEC §13.2)."""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app import db, timeutil
from app.alerts.base import all_scanners

router = APIRouter()

JOB_REFUSED = {"kind": "job_refused", "label": "A data source refused us"}


class SeenIn(BaseModel):
    ids: list[int] | None = None


@router.get("/alerts/kinds")
def kinds() -> list[dict]:
    return [{"kind": s.kind, "label": s.label} for s in all_scanners()] + [JOB_REFUSED]


@router.get("/alerts/count")
def count() -> dict:
    with db.tx() as c:
        return {"unseen": c.execute("SELECT COUNT(*) FROM alerts WHERE seen_at IS NULL").fetchone()[0]}


@router.get("/alerts")
def list_alerts(
    unseen: int = 0, kind: str | None = None, limit: int = Query(100, ge=1, le=500)
) -> list[dict]:
    where, args = [], []
    if unseen:
        where.append("seen_at IS NULL")
    if kind:
        where.append("kind=?")
        args.append(kind)
    sql = "SELECT * FROM alerts" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    with db.tx() as c:
        return [dict(r) for r in c.execute(sql, (*args, limit))]


@router.post("/alerts/seen")
def mark_seen(body: SeenIn | None = None) -> dict:
    ids = body.ids if body else None
    now = timeutil.now_iso()
    with db.tx() as c:
        if ids:
            marks = ",".join("?" * len(ids))
            sql = f"UPDATE alerts SET seen_at=? WHERE seen_at IS NULL AND id IN ({marks})"
            cur = c.execute(sql, (now, *ids))
        else:
            cur = c.execute("UPDATE alerts SET seen_at=? WHERE seen_at IS NULL", (now,))
        return {"marked": cur.rowcount}
