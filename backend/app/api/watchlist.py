"""Watchlist endpoints (SPEC §13.1)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import bardb, db, timeutil
from app.analytics import frames

router = APIRouter()


class WatchAdd(BaseModel):
    symbol: str = Field(min_length=1)
    note: str | None = None


@router.get("/watchlist")
def list_watchlist() -> list[dict]:
    with db.tx() as c:
        rows = c.execute(
            "SELECT w.symbol, s.name, w.added_at, w.note FROM watchlist w "
            "LEFT JOIN symbols s ON s.symbol = w.symbol ORDER BY w.added_at, w.symbol"
        ).fetchall()
    # batched key seeks, not one frame per stock (SPEC §17.5)
    last = frames.latest_closes([r["symbol"] for r in rows])
    added = frames.closes_on({r["symbol"]: r["added_at"][:10] for r in rows})
    return [
        {**dict(r), "last_close": last.get(r["symbol"]), "added_close": added.get(r["symbol"])} for r in rows
    ]


@router.post("/watchlist")
def add(body: WatchAdd) -> dict:
    sym = body.symbol.strip().upper()
    with db.tx() as c:
        known = c.execute("SELECT 1 FROM symbols WHERE symbol=?", (sym,)).fetchone()
        has_bars = c.execute(
            "SELECT 1 FROM bar_sources s WHERE EXISTS (SELECT 1 FROM bars b WHERE b.source_id=s.id "
            "AND b.sym_id=" + bardb.SYM_ID + ")",
            (sym,),
        ).fetchone()
        if not known and not has_bars:
            raise HTTPException(400, f"Unknown symbol {sym}")
        c.execute(
            "INSERT INTO watchlist(symbol, added_at, note) VALUES (?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET note=COALESCE(excluded.note, note)",
            (sym, timeutil.now().isoformat(), body.note),
        )
    frames.invalidate()
    return {"symbol": sym, "note": body.note}


@router.delete("/watchlist/{symbol}")
def remove(symbol: str) -> dict:
    with db.tx() as c:
        c.execute("DELETE FROM watchlist WHERE symbol=?", (symbol.upper(),))
    frames.invalidate()
    return {"ok": True}
