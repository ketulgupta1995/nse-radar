"""Dashboard API: one call for the home page (SPEC §14 item 1). Aggregates the existing helpers."""

from datetime import date

from fastapi import APIRouter

from app import db, timeutil
from app.analytics import frames
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


def _data_facts() -> dict:
    """The two `/data/health` numbers the dashboard shows, without the rest of its counts."""
    with db.read() as c:
        return {
            "last_trading_date": frames.last_trading_date(c),
            "checks_open": c.execute("SELECT COUNT(*) FROM price_checks WHERE status='open'").fetchone()[0],
        }


def _data_status() -> dict:
    last = frames.memo("dashboard.data", _data_facts)
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


def _moves(c, open_positions: list[dict], visit_day: str) -> list[dict]:
    """% change of each open position since the visit day's close: batched key seeks, no frames (§17.5)."""
    held = [p for p in open_positions if p["entry_date"] <= visit_day]
    before = frames.closes_on({p["symbol"]: visit_day for p in held}, c)
    moves = []
    for p in held:
        then, now = before.get(p["symbol"].upper()), p.get("last_close")
        if then and now is not None:
            moves.append({"symbol": p["symbol"], "change_pct_since_visit": round((now / then - 1) * 100, 2)})
    return moves


def _since(c, last_visit: str, open_positions: list[dict]) -> dict:
    day, stamp = last_visit[:10], last_visit[:19]
    alert_cats = [cat["category"] for cat in store._categories() if cat.get("alert")]
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
    return {
        "last_visit_at": last_visit,
        "alerts": new_alerts,
        "new_in_screens": [{"screen": k, "symbols": v} for k, v in screens.items()],
        "positions": _moves(c, open_positions, day),
        "announcements": news,
    }


@router.get("/dashboard")
def dashboard() -> dict:
    open_positions = positions_api.list_positions("open")
    with db.read() as c:  # one connection for the small reads: each one is a round trip on Vercel (§17.5)
        unseen = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM alerts WHERE seen_at IS NULL ORDER BY created_at DESC, id DESC LIMIT 100"
            )
        ]
        last_visit = db.get_setting("last_visit_at", c)
        since = _since(c, last_visit, open_positions) if last_visit else None
    unseen.sort(key=lambda a: SEVERITY.get(a["severity"], 3))  # stable: newest first within a severity
    return {
        "shortlist": screens_api.shortlist(10),
        "alerts": unseen[:10],
        "positions": _positions_summary(open_positions),
        "data": _data_status(),
        "since": since,
    }


@router.post("/dashboard/visit")
def visit() -> dict:
    now = timeutil.now_iso()
    db.set_setting("last_visit_at", now)
    return {"last_visit_at": now}
