"""Dashboard API: one call for the home page (SPEC §14 item 1). Aggregates the existing helpers."""

from datetime import date

from fastapi import APIRouter

from app import db, timeutil
from app.analytics import frames
from app.api import alerts as alerts_api
from app.api import data as data_api
from app.api import positions as positions_api
from app.api import screens as screens_api
from app.jobs import runner
from app.sources import store

router = APIRouter()

STALE_DAYS = 4  # a weekend plus one holiday; older than this and prices look out of date
SEVERITY = {"critical": 0, "warn": 1, "info": 2}
LIST_LIMIT = 20


def _positions_summary(open_positions: list[dict]) -> dict:
    invested = sum(p["entry_price"] * p["qty"] for p in open_positions)
    pnl = sum(p["pnl_inr"] or 0 for p in open_positions)
    risk = sum((p["entry_price"] - p["stop"]) * p["qty"] for p in open_positions if p.get("stop"))
    return {
        "open": len(open_positions),
        "invested": round(invested, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl / invested * 100, 2) if invested else None,
        "open_risk": round(max(risk, 0), 2),
    }


def _data_status() -> dict:
    last = data_api.health()
    last_date = last["last_trading_date"]
    stale = True
    if last_date:
        stale = (timeutil.today() - date.fromisoformat(last_date)).days > STALE_DAYS
    status = runner.status()
    return {
        "last_trading_date": last_date,
        "stale": stale,
        "updating": status["updating"],
        "checks_open": last["checks_open"],
    }


def _move_since(symbol: str, visit_day: str) -> float | None:
    f = frames.load_frame(symbol)
    if len(f) == 0:
        return None
    before = f[f.index <= visit_day]
    if len(before) == 0:
        return None
    return round((float(f["close"].iloc[-1]) / float(before["close"].iloc[-1]) - 1) * 100, 2)


def _since(last_visit: str, open_positions: list[dict]) -> dict:
    day, stamp = last_visit[:10], last_visit[:19]
    alert_cats = [c["category"] for c in store._categories() if c.get("alert")]
    with db.tx() as c:
        new_alerts = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM alerts WHERE substr(created_at,1,19) > ? ORDER BY created_at DESC LIMIT ?",
                (stamp, LIST_LIMIT),
            )
        ]
        screens: dict[str, list[str]] = {}
        for r in c.execute(
            "SELECT s.name, r.symbol FROM screen_results r JOIN screens s ON s.id=r.screen_id "
            "WHERE r.first_seen > ? ORDER BY s.name, r.symbol",
            (day,),
        ):
            screens.setdefault(r["name"], []).append(r["symbol"])
        symbols = sorted(
            {r["symbol"] for r in c.execute("SELECT symbol FROM watchlist")}
            | {p["symbol"] for p in open_positions}
        )
        news: list[dict] = []
        if symbols and alert_cats:
            sm = ",".join("?" * len(symbols))
            cm = ",".join("?" * len(alert_cats))
            news = [
                dict(r)
                for r in c.execute(
                    "SELECT id, symbol, ts, category, headline, url FROM announcements "
                    f"WHERE substr(ts,1,19) > ? AND symbol IN ({sm}) AND category IN ({cm}) "
                    "ORDER BY ts DESC LIMIT ?",
                    (stamp, *symbols, *alert_cats, LIST_LIMIT),
                )
            ]
    moves = []
    for p in open_positions:
        if p["entry_date"] > day:
            continue
        change = _move_since(p["symbol"], day)
        if change is not None:
            moves.append({"symbol": p["symbol"], "change_pct_since_visit": change})
    return {
        "last_visit_at": last_visit,
        "alerts": new_alerts,
        "new_in_screens": [{"screen": k, "symbols": v} for k, v in screens.items()],
        "positions": moves,
        "announcements": news,
    }


@router.get("/dashboard")
def dashboard() -> dict:
    open_positions = positions_api.list_positions("open")
    unseen = alerts_api.list_alerts(unseen=1, limit=100)
    unseen.sort(key=lambda a: SEVERITY.get(a["severity"], 3))  # stable: newest first within a severity
    last_visit = db.get_setting("last_visit_at")
    return {
        "shortlist": screens_api.shortlist(10),
        "alerts": unseen[:10],
        "positions": _positions_summary(open_positions),
        "data": _data_status(),
        "since": _since(last_visit, open_positions) if last_visit else None,
    }


@router.post("/dashboard/visit")
def visit() -> dict:
    now = timeutil.now_iso()
    db.set_setting("last_visit_at", now)
    return {"last_visit_at": now}
