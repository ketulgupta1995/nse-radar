"""Symbol search and detail (SPEC §7.5)."""

from fastapi import APIRouter, HTTPException

from app import bardb, db
from app.analytics import calendar, frames

router = APIRouter()


def _like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/symbols/search")
def search(q: str = "") -> list[dict]:
    q = q.strip()
    if not q:
        return []
    pre, sub = _like(q.upper()) + "%", "%" + _like(q.lower()) + "%"
    with db.tx() as c:
        rows = c.execute(
            "SELECT symbol, name, industry, in_universe FROM symbols "
            "WHERE symbol LIKE ? ESCAPE '\\' OR LOWER(COALESCE(name,'')) LIKE ? ESCAPE '\\' "
            "ORDER BY (symbol LIKE ? ESCAPE '\\') DESC, in_universe DESC, symbol LIMIT 20",
            (pre, sub, pre),
        ).fetchall()
    return [{**dict(r), "in_universe": bool(r["in_universe"])} for r in rows]


@router.get("/symbols/{sym}")
def detail(sym: str) -> dict:
    sym = sym.upper()
    with db.tx() as c:
        row = c.execute(
            "SELECT symbol, name, industry, in_universe FROM symbols WHERE symbol=?", (sym,)
        ).fetchone()
        has_bars = c.execute(
            "SELECT 1 FROM bar_sources s WHERE EXISTS (SELECT 1 FROM bars b WHERE b.source_id=s.id "
            "AND b.sym_id=" + bardb.SYM_ID + ")",
            (sym,),
        ).fetchone()
        if row is None and not has_bars:
            raise HTTPException(404, f"Unknown symbol {sym}")
        inst = c.execute("SELECT series FROM instruments WHERE symbol=?", (sym,)).fetchone()
        in_watch = c.execute("SELECT 1 FROM watchlist WHERE symbol=?", (sym,)).fetchone()
        pos = c.execute(
            "SELECT id FROM positions WHERE symbol=? AND status='open' ORDER BY id LIMIT 1", (sym,)
        ).fetchone()
        upcoming = calendar.next_results(c, [sym]).get(sym)
    series = inst["series"] if inst else None
    info = dict(row) if row else {"symbol": sym, "name": None, "industry": None, "in_universe": 0}
    frame = frames.load_frame(sym)
    last_date = last_close = change_pct = None
    if len(frame):
        last_date = frame.index[-1].strftime("%Y-%m-%d")
        last_close = float(frame["close"].iloc[-1])
        if len(frame) > 1:
            prev = float(frame["close"].iloc[-2])
            change_pct = round((last_close / prev - 1) * 100, 2) if prev else None
    return {
        **info,
        "in_universe": bool(info["in_universe"]),
        "last_date": last_date,
        "last_close": last_close,
        "change_pct": change_pct,
        "bars_source": frame.attrs.get("source") or None,
        "series": series,
        "trade_for_trade": series in ("BE", "BZ"),
        "in_watchlist": in_watch is not None,
        "open_position_id": pos["id"] if pos else None,
        "next_results": upcoming,
    }
