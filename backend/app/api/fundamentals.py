"""Fundamentals API (SPEC §9.4)."""

import json

from fastapi import APIRouter, HTTPException

from app import db
from app.analytics import fundamentals

router = APIRouter()


@router.get("/fundamentals/fields")
def list_fields() -> list[dict]:
    return fundamentals.FIELDS


@router.get("/fundamentals/{sym}")
def get_fundamentals(sym: str) -> dict:
    sym = sym.upper()
    with db.tx() as c:
        if c.execute("SELECT 1 FROM symbols WHERE symbol=?", (sym,)).fetchone() is None:
            raise HTTPException(404, f"unknown symbol {sym}")
        row = c.execute("SELECT * FROM fundamentals WHERE symbol=?", (sym,)).fetchone()
        quarters = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM quarters WHERE symbol=? ORDER BY period_end DESC, consolidated DESC LIMIT 40",
                (sym,),
            )
        ]
        snapshots = {
            r["source"]: {"fetched_at": r["fetched_at"], "detail": json.loads(r["detail"] or "{}")}
            for r in c.execute("SELECT source, fetched_at, detail FROM fund_snapshots WHERE symbol=?", (sym,))
        }
    return {
        "data": json.loads(row["data"]) if row else {},
        "sources": json.loads(row["sources"]) if row else {},
        "updated_at": row["updated_at"] if row else None,
        "quarters": quarters,
        "snapshots": snapshots,
    }
