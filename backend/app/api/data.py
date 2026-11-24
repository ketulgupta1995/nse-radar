"""Data health, price checks and manual adjustments (SPEC §7.5)."""

import json
import re
from datetime import date as _date
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import bardb, db, timeutil
from app.analytics import adjust, frames

router = APIRouter()
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CheckAction(BaseModel):
    action: Literal["ignore", "apply_factor"]
    factor: float | None = Field(default=None, gt=0)


class ManualAdjustment(BaseModel):
    symbol: str = Field(min_length=1)
    ex_date: str
    factor: float = Field(gt=0)
    note: str | None = None


class SymbolChangeBody(BaseModel):
    old_symbol: str = Field(min_length=1)
    new_symbol: str = Field(min_length=1)
    effective_date: str
    note: str | None = None


def _check(row) -> dict:
    d = dict(row)
    d["detail"] = json.loads(d["detail"]) if d["detail"] else {}
    return d


def _count(c, sql: str, *args) -> int:
    return c.execute(sql, args).fetchone()[0]


@router.get("/data/health")
def health() -> dict:
    # also read by the dashboard; on Vercel the answer is reused for a few minutes (SPEC §17.2)
    return frames.memo("data.health", _health)


# Per source: how many symbols have bars, and the newest day. One key seek per (source, symbol)
# instead of a scan of every bar (SPEC §17.5).
_BARS_SQL = (
    "SELECT name source, COUNT(d) n, MAX(d) last FROM (SELECT s.id, s.name, (SELECT MAX(b.day) "
    "FROM bars b WHERE b.source_id = s.id AND b.sym_id = y.id) d FROM bar_sources s, bar_symbols y) "
    "WHERE d IS NOT NULL GROUP BY id"
)


def _health() -> dict:
    week = (timeutil.today() - timedelta(days=7)).isoformat()
    with db.read() as c:  # read-only: must not hold the write lock
        return {
            "last_trading_date": frames.last_trading_date(c),
            "symbols": _count(c, "SELECT COUNT(*) FROM symbols"),
            "universe": _count(c, "SELECT COUNT(*) FROM symbols WHERE in_universe=1"),
            "checks_open": _count(c, "SELECT COUNT(*) FROM price_checks WHERE status='open'"),
            "unparsed_actions": _count(c, "SELECT COUNT(*) FROM corp_actions WHERE kind='unparsed'"),
            "bars": {
                r["source"]: {"symbols": r["n"], "last_date": bardb.iso(r["last"])}
                for r in c.execute(_BARS_SQL)
            },
            "fundamentals": {
                **{
                    r["source"]: r["n"]
                    for r in c.execute("SELECT source, COUNT(*) n FROM fund_snapshots GROUP BY source")
                },
                "merged": _count(c, "SELECT COUNT(*) FROM fundamentals"),
            },
            "quarters": {
                r["source"]: r["n"]
                for r in c.execute("SELECT source, COUNT(*) n FROM quarters GROUP BY source")
            },
            "news": {
                "announcements_7d": _count(
                    c, "SELECT COUNT(*) FROM announcements WHERE substr(ts,1,10) >= ?", week
                ),
                "news_7d": _count(c, "SELECT COUNT(*) FROM news_items WHERE substr(ts,1,10) >= ?", week),
            },
        }


@router.get("/data/checks")
def checks(status: str = "open") -> list[dict]:
    with db.tx() as c:
        rows = c.execute(
            "SELECT * FROM price_checks WHERE status=? ORDER BY date DESC, id DESC", (status,)
        ).fetchall()
    return [_check(r) for r in rows]


@router.post("/data/checks/{check_id}")
def act_on_check(check_id: int, body: CheckAction) -> dict:
    with db.tx() as c:
        row = c.execute("SELECT * FROM price_checks WHERE id=?", (check_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "check not found")
        check = _check(row)
        if body.action == "ignore":
            c.execute("UPDATE price_checks SET status='ignored' WHERE id=?", (check_id,))
        else:
            detail = check["detail"]
            factor = body.factor if body.factor is not None else detail.get("suggested_factor")
            ex_date = detail.get("ex_date") if check["kind"] == "mismatch" else check["date"]
            if factor is None:
                raise HTTPException(400, "this check has no suggested factor: send one")
            if not ex_date:
                raise HTTPException(400, "cannot tell the ex-date for this check: add a manual adjustment")
            c.execute(
                "INSERT OR REPLACE INTO manual_adjustments(symbol, ex_date, factor, note) VALUES (?,?,?,?)",
                (check["symbol"], ex_date, factor, f"from price check #{check_id}"),
            )
            c.execute("UPDATE price_checks SET status='fixed' WHERE id=?", (check_id,))
            # the same missed event also shows up as a jump: close those checks too
            c.execute(
                "UPDATE price_checks SET status='fixed' WHERE symbol=? AND kind='unexplained_gap' "
                "AND status='open' AND abs(julianday(date) - julianday(?)) <= 3",
                (check["symbol"], ex_date),
            )
        out = _check(c.execute("SELECT * FROM price_checks WHERE id=?", (check_id,)).fetchone())
    frames.invalidate()
    return out


@router.get("/data/unparsed-actions")
def unparsed_actions() -> list[dict]:
    with db.tx() as c:
        rows = c.execute(
            "SELECT source, symbol, ex_date, subject FROM corp_actions WHERE kind='unparsed' "
            "ORDER BY ex_date DESC, symbol"
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/data/event-factors")
def event_factors() -> list[dict]:
    with db.tx() as c:
        rows = c.execute(
            "SELECT symbol, ex_date, kind, factor, method, detail FROM event_factors "
            "ORDER BY ex_date DESC, symbol, kind"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["detail"] = json.loads(d["detail"]) if d["detail"] else {}
        out.append(d)
    return out


@router.post("/data/manual-adjustment")
def manual_adjustment(body: ManualAdjustment) -> dict:
    if not _DATE.match(body.ex_date):
        raise HTTPException(400, "ex_date must be YYYY-MM-DD")
    symbol = body.symbol.strip().upper()
    with db.tx() as c:
        c.execute(
            "INSERT OR REPLACE INTO manual_adjustments(symbol, ex_date, factor, note) VALUES (?,?,?,?)",
            (symbol, body.ex_date, body.factor, body.note),
        )
        row = c.execute(
            "SELECT * FROM manual_adjustments WHERE symbol=? AND ex_date=?", (symbol, body.ex_date)
        ).fetchone()
    frames.invalidate()
    return dict(row)


@router.get("/data/symbol-changes")
def symbol_changes(symbol: str) -> dict:
    sym = symbol.strip().upper()
    with db.read() as c:
        lin = adjust.lineage(sym, c)
        tickers = [t for t, _, _ in lin]
        marks = ",".join("?" * len(tickers))
        rows = c.execute(
            "SELECT source, old_symbol, new_symbol, effective_date, name, note FROM symbol_changes "
            f"WHERE old_symbol IN ({marks}) OR new_symbol IN ({marks}) "
            "ORDER BY effective_date, old_symbol, new_symbol, source",
            [*tickers, *tickers],
        ).fetchall()
    return {
        "symbol": sym,
        "lineage": [{"ticker": t, "from_date": f, "until_date": u} for t, f, u in lin],
        "rows": [dict(r) for r in rows],
    }


@router.post("/data/symbol-change")
def add_symbol_change(body: SymbolChangeBody) -> dict:
    old, new = body.old_symbol.strip().upper(), body.new_symbol.strip().upper()
    if old == new:
        raise HTTPException(400, "old and new symbol must differ")
    try:
        if not _DATE.match(body.effective_date):
            raise ValueError
        _date.fromisoformat(body.effective_date)
    except ValueError:
        raise HTTPException(400, "effective_date must be YYYY-MM-DD") from None
    with db.tx() as c:
        c.execute(
            "INSERT OR REPLACE INTO symbol_changes"
            "(source, old_symbol, new_symbol, effective_date, name, note) VALUES ('manual',?,?,?,NULL,?)",
            (old, new, body.effective_date, body.note),
        )
        row = c.execute(
            "SELECT source, old_symbol, new_symbol, effective_date, name, note FROM symbol_changes "
            "WHERE source='manual' AND old_symbol=? AND new_symbol=? AND effective_date=?",
            (old, new, body.effective_date),
        ).fetchone()
    frames.invalidate()
    return dict(row)
