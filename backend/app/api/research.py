"""Stored broker Buy/Sell calls. One indexed read (SPEC §17.5)."""

from typing import Literal

from fastapi import APIRouter, Query

from app import db

router = APIRouter()


@router.get("/research/reports")
def reports(
    type: Literal["Buy", "Sell"] | None = None,
    limit: int = Query(500, ge=1, le=2000),
) -> list[dict]:
    sql = (
        "SELECT r.source, r.report_id, r.date, r.symbol, r.stock, r.author, r.type, r.ltp, r.target, "
        "r.reco_price, r.change_pct, r.upside_pct, r.url, r.fetched_at, "
        "s.symbol IS NOT NULL AS tracked "
        "FROM research_reports r LEFT JOIN symbols s ON s.symbol = r.symbol"
        + (" WHERE r.type=?" if type else "")
        + " ORDER BY r.date DESC, r.report_id DESC LIMIT ?"
    )
    args = (type, limit) if type else (limit,)
    with db.tx() as c:
        return [{**dict(r), "tracked": bool(r["tracked"])} for r in c.execute(sql, args)]
