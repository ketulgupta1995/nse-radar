"""Announcements and announcement categories (SPEC §13). News items come with the RSS ticket."""

from fastapi import APIRouter, Query

from app import db
from app.sources import store

router = APIRouter()


def _hidden() -> list[str]:
    return [c["category"] for c in store._categories() if c.get("hidden")]


@router.get("/news/categories")
def categories() -> list[dict]:
    return store._categories()


@router.get("/news/announcements")
def announcements(
    symbol: str | None = None,
    category: str | None = None,
    include_hidden: int = 0,
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    where, args = [], []
    if symbol:
        where.append("symbol=?")
        args.append(symbol.upper())
    if category:
        where.append("category=?")
        args.append(category)
    hidden = _hidden()
    if not include_hidden and hidden:
        where.append(f"category NOT IN ({','.join('?' * len(hidden))})")
        args += hidden
    sql = "SELECT id, source, symbol, ts, category, headline, body, url FROM announcements"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    with db.tx() as c:
        return [dict(r) for r in c.execute(sql, (*args, limit))]


@router.get("/news/items")
def news_items(symbol: str | None = None, limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    sql = (
        "SELECT n.id, n.source, n.feed, n.ts, n.title, n.url, n.summary FROM news_items n"
        + (" JOIN news_symbols s ON s.news_id = n.id WHERE s.symbol=?" if symbol else "")
        + " ORDER BY n.ts DESC, n.id DESC LIMIT ?"
    )
    args = (symbol.upper(), limit) if symbol else (limit,)
    with db.tx() as c:
        items = [dict(r) for r in c.execute(sql, args)]
        tags: dict[int, list[str]] = {}
        if items:  # one query for every item's symbols, not one per item (SPEC §17.5)
            ids = [it["id"] for it in items]
            rows = c.execute(
                f"SELECT news_id, symbol FROM news_symbols WHERE news_id IN ({','.join('?' * len(ids))}) "
                "ORDER BY news_id, symbol",
                ids,
            )
            for r in rows:
                tags.setdefault(r["news_id"], []).append(r["symbol"])
    for it in items:
        it["symbols"] = tags.get(it["id"], [])
    return items
