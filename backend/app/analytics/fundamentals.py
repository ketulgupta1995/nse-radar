"""Fundamental fields (SPEC §9.4). T034 adds the merge logic; for now only `FIELDS`."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app import db, timeutil
from app.sources import registry as sources


def _f(field: str, label: str, explain: str, unit: str, numeric: bool = True) -> dict:
    return {"field": field, "label": label, "explain": explain, "unit": unit, "numeric": numeric}


FIELDS: list[dict] = [
    _f("market_cap_cr", "Market cap (₹ cr)", "Company size in ₹ crore.", "₹ cr"),
    _f("pe", "P/E", "Price ÷ yearly profit per share: how expensive the stock is.", "x"),
    _f("pb", "P/B", "Price ÷ book value per share.", "x"),
    _f("roce_pct", "ROCE %", "Profit earned on all the capital the business uses. Above 15% is good.", "%"),
    _f("roe_pct", "ROE %", "Profit earned on shareholders' money.", "%"),
    _f("debt_to_equity", "Debt to equity", "Borrowings ÷ shareholders' money. Below 0.5 is comfortable.",
       "x"),
    _f("sales_growth_3y_pct", "Sales growth 3y %", "Yearly sales growth, compounded over 3 years.", "%"),
    _f("profit_growth_3y_pct", "Profit growth 3y %", "Yearly profit growth, compounded over 3 years.", "%"),
    _f("sales_growth_yoy_pct", "Sales growth YoY %",
       "Latest quarter's sales vs the same quarter last year.", "%"),
    _f("profit_growth_yoy_pct", "Profit growth YoY %",
       "Latest quarter's profit vs the same quarter last year.", "%"),
    _f("profit_positive_4q", "Profit in last 4 quarters",
       "1 if the company made a profit in each of the last 4 quarters.", "flag"),
    _f("promoter_pct", "Promoter holding %",
       "Share of the company owned by its promoters (founders/parent).", "%"),
    _f("promoter_change_1y_pp", "Promoter change 1y (pp)",
       "Change in promoter holding over the last year, in % points.", "pp"),
    _f("dividend_yield_pct", "Dividend yield %", "Yearly dividend as % of price.", "%"),
    _f("sector", "Sector", "Broad business sector (text, not usable in numeric rules).", "text", False),
    _f("industry", "Industry", "Specific industry (text, not usable in numeric rules).", "text", False),
]  # fmt: skip

FIELD_BY_NAME: dict[str, dict] = {f["field"]: f for f in FIELDS}


# ---- merge (T034) ---------------------------------------------------------------------------

MIN_QUARTERS = 5
YOY_TOLERANCE_DAYS = 20
# Results are due within ~45-60 days of quarter end, so a latest quarter older than this means the
# source has stopped updating; its YoY/profit fields would be stale and must not beat fresher sources.
MAX_QUARTER_AGE_DAYS = 200


def _quarter_rows(source: str, symbol: str, conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Usable rows for one source: consolidated if it has enough, else standalone. Oldest first."""
    rows = conn.execute(
        "SELECT * FROM quarters WHERE source=? AND symbol=? AND parse_error IS NULL ORDER BY period_end",
        (source, symbol),
    ).fetchall()
    for want in (1, 0):
        picked = [r for r in rows if r["consolidated"] == want]
        if len(picked) >= MIN_QUARTERS:
            return picked
    return []


def _growth(now: float | None, then: float | None) -> float | None:
    if now is None or then is None or then <= 0:
        return None
    return round((now / then - 1) * 100, 2)


def _derive(rows: list[sqlite3.Row], as_of: date | None = None) -> dict:
    latest = rows[-1]
    end = date.fromisoformat(latest["period_end"])
    if ((as_of or timeutil.today()) - end).days > MAX_QUARTER_AGE_DAYS:
        return {}
    prior = None
    best = YOY_TOLERANCE_DAYS + 1
    for r in rows[:-1]:
        off = abs((end - date.fromisoformat(r["period_end"])).days - 365)
        if off < best:
            prior, best = r, off
    out: dict[str, float | None] = {}
    if prior is not None:
        out["sales_growth_yoy_pct"] = _growth(latest["revenue"], prior["revenue"])
        out["profit_growth_yoy_pct"] = _growth(latest["net_profit"], prior["net_profit"])
    profits = [r["net_profit"] for r in rows[-4:]]
    if all(p is not None for p in profits):
        out["profit_positive_4q"] = 1.0 if all(p > 0 for p in profits) else 0.0
    return {k: v for k, v in out.items() if v is not None}


def _from_quarters(symbol: str, conn: sqlite3.Connection) -> tuple[dict, str | None]:
    for src in sources.ordered("quarters", conn):
        derived = _derive(rows) if (rows := _quarter_rows(src.name, symbol, conn)) else {}
        if derived:  # a source whose latest quarter is stale yields nothing; try the next one
            return derived, src.name
    return {}, None


def from_quarters(symbol: str, conn: sqlite3.Connection) -> dict:
    """Fields derived from stored quarterly results (YoY growth, profit in each of the last 4)."""
    return _from_quarters(symbol, conn)[0]


QUARTER_FIELDS = ("sales_growth_yoy_pct", "profit_growth_yoy_pct", "profit_positive_4q")
AVAILABLE_LAG_DAYS = 1  # results are usually filed after the close, so trade on them from the next day
NO_FILING_LAG_DAYS = 60


def _known_on(row: sqlite3.Row) -> date:
    filed = row["filing_date"]
    if filed:
        return date.fromisoformat(filed[:10]) + timedelta(days=AVAILABLE_LAG_DAYS)
    return date.fromisoformat(row["period_end"]) + timedelta(days=NO_FILING_LAG_DAYS)


def known_on_dates(symbol: str, conn: sqlite3.Connection) -> list[date]:
    """Dates each quarterly result became tradable, from the first source that has rows."""
    for src in sources.ordered("quarters", conn):
        if rows := _quarter_rows(src.name, symbol.upper(), conn):
            return sorted({_known_on(r) for r in rows})
    return []


def pit_quarter_series(
    symbol: str, index: pd.DatetimeIndex, conn: sqlite3.Connection
) -> dict[str, pd.Series]:
    """Per date, the quarter-derived fields from results already published by then (no look-ahead)."""
    symbol = symbol.upper()
    rows: list[sqlite3.Row] = []
    for src in sources.ordered("quarters", conn):
        if rows := _quarter_rows(src.name, symbol, conn):
            break
    known = [(_known_on(r), r) for r in rows]
    # a value can change when a quarter is filed, or when the latest quarter turns stale
    events = {d for d, _ in known}
    events |= {date.fromisoformat(r["period_end"]) + timedelta(days=MAX_QUARTER_AGE_DAYS + 1) for r in rows}
    stamps: list[pd.Timestamp] = []
    table: dict[str, list[float]] = {f: [] for f in QUARTER_FIELDS}
    for d in sorted(events):
        by_now = sorted((r for k, r in known if k <= d), key=lambda r: r["period_end"])
        derived = _derive(by_now, as_of=d) if len(by_now) >= MIN_QUARTERS else {}
        stamps.append(pd.Timestamp(d))
        for f in QUARTER_FIELDS:
            v = derived.get(f)
            table[f].append(np.nan if v is None else float(v))
    out: dict[str, pd.Series] = {}
    for f in QUARTER_FIELDS:
        if not stamps:
            out[f] = pd.Series(np.nan, index=index, dtype=float)
            continue
        ev = pd.Series(table[f], index=pd.DatetimeIndex(stamps), dtype=float)
        out[f] = ev.reindex(index, method="ffill").astype(float)  # a NaN event stays NaN (stale)
    return out


def _snapshots(symbol: str, conn: sqlite3.Connection) -> dict[str, dict]:
    out = {}
    for r in conn.execute("SELECT source, fields FROM fund_snapshots WHERE symbol=?", (symbol,)):
        out[r["source"]] = json.loads(r["fields"])
    return out


def merge(symbol: str, conn: sqlite3.Connection) -> tuple[dict, dict]:
    """(data, sources): per field the first non-null value in priority order.

    Order is `fundamentals_field_priority[field]` if set, else the enabled `fundamentals` sources
    in priority order. The name "quarters" means values derived from the quarters table.
    """
    symbol = symbol.upper()
    try:
        override = db.get_setting("fundamentals_field_priority", conn)
    except KeyError:
        override = {}
    default_order = [s.name for s in sources.ordered("fundamentals", conn)]
    snaps = _snapshots(symbol, conn)
    derived, derived_source = _from_quarters(symbol, conn)
    data: dict = {}
    origin: dict = {}
    for meta in FIELDS:
        field = meta["field"]
        for name in override.get(field) or default_order:
            if name == "quarters":
                value = derived.get(field)
                label = f"quarters:{derived_source}"
            else:
                value = snaps.get(name, {}).get(field)
                label = name
            if value is not None:
                data[field], origin[field] = value, label
                break
    return data, origin


# ---- point-in-time yearly fundamentals and promoter holding (T115) --------------------------

HISTORY_FIELDS = (
    "roce_pct", "roe_pct", "debt_to_equity", "sales_growth_3y_pct",
    "profit_growth_3y_pct", "promoter_pct", "promoter_change_1y_pp",
)  # fmt: skip
YEARLY_FIELDS = HISTORY_FIELDS[:5]
HOLDING_FIELDS = HISTORY_FIELDS[5:]
ANNUAL_LAG_DAYS = 60  # SEBI: audited annual results within 60 days of the year end
SHAREHOLDING_LAG_DAYS = 21  # SEBI: shareholding pattern within 21 days of the quarter end
ANNUAL_MAX_AGE_DAYS = 550  # latest year older than this (from its period end) = the source stopped; NaN
HOLDING_MAX_AGE_DAYS = 200
_PRIOR_TOLERANCE_DAYS = 20

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
    )
}


def _period_end(label: str) -> date | None:
    """'Mar 2015' -> 2015-03-31; anything else ('TTM', blank) -> None."""
    parts = str(label).split()
    if len(parts) != 2 or parts[0][:3].lower() not in _MONTHS or not parts[1].isdigit():
        return None
    year, month = int(parts[1]), _MONTHS[parts[0][:3].lower()]
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _table(detail: dict, name: str) -> dict[date, dict[str, float | None]]:
    """{period_end: {row label: value}} for the columns whose label is a month and year."""
    tbl = detail.get(name) or {}
    rows = tbl.get("rows") or {}
    out: dict[date, dict[str, float | None]] = {}
    for i, label in enumerate(tbl.get("periods") or []):
        end = _period_end(label)
        if end is None:
            continue
        out[end] = {
            k: (vals[i] if i < len(vals) else None) for k, vals in rows.items() if isinstance(vals, list)
        }
    return out


def _div(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None or b <= 0 else a / b


def _cagr3(now: float | None, then: float | None) -> float | None:
    if now is None or then is None or now <= 0 or then <= 0:
        return None
    return round(((now / then) ** (1 / 3) - 1) * 100, 2)


def _earlier(table: dict[date, dict], end: date, days: int) -> dict | None:
    """The column whose period end is about `days` before `end`."""
    for e, vals in table.items():
        if abs((end - e).days - days) <= _PRIOR_TOLERANCE_DAYS:
            return vals
    return None


def _balance_fields(p: dict, b: dict, roce: float | None) -> dict[str, float | None]:
    cap, res, debt = b.get("Equity Capital"), b.get("Reserves"), b.get("Borrowings")
    equity = None if cap is None or res is None else cap + res
    d2e = _div(debt, equity)
    roe = _div(p.get("Net Profit"), equity)
    if roce is None and equity is not None and debt is not None:
        pbt, interest = p.get("Profit before tax"), p.get("Interest")
        r = _div(None if pbt is None or interest is None else pbt + interest, equity + debt)
        roce = None if r is None else round(r * 100, 2)
    return {
        "debt_to_equity": None if d2e is None else round(d2e, 3),
        "roe_pct": None if roe is None else round(roe * 100, 2),
        "roce_pct": roce,
    }


def _yearly_values(detail: dict) -> list[tuple[date, dict[str, float | None]]]:
    pl = _table(detail, "profit_loss")
    bs = _table(detail, "balance_sheet")
    ratios = _table(detail, "ratios_hist")
    out = []
    for end in sorted(pl):
        p = pl[end]
        vals: dict[str, float | None] = dict.fromkeys(YEARLY_FIELDS)
        roce = (ratios.get(end) or {}).get("ROCE %")
        if end in bs:
            vals.update(_balance_fields(p, bs[end], roce))
        else:
            vals["roce_pct"] = roce
        old = _earlier(pl, end, 1096)
        if old is not None:
            vals["sales_growth_3y_pct"] = _cagr3(p.get("Sales"), old.get("Sales"))
            vals["profit_growth_3y_pct"] = _cagr3(p.get("Net Profit"), old.get("Net Profit"))
        out.append((end, vals))
    return out


def _holding_values(detail: dict) -> list[tuple[date, dict[str, float | None]]]:
    sh = _table(detail, "shareholding")
    out = []
    for end in sorted(sh):
        now = sh[end].get("Promoters")
        then = (_earlier(sh, end, 365) or {}).get("Promoters")
        change = None if now is None or then is None else round(now - then, 2)
        out.append((end, {"promoter_pct": now, "promoter_change_1y_pp": change}))
    return out


def _step_series(
    index: pd.DatetimeIndex,
    columns: list[tuple[date, dict[str, float | None]]],
    field: str,
    lag: int,
    max_age: int,
) -> pd.Series:
    if not columns:
        return pd.Series(np.nan, index=index, dtype=float)
    stamps = [pd.Timestamp(end + timedelta(days=lag)) for end, _ in columns]
    values = [np.nan if v.get(field) is None else float(v[field]) for _, v in columns]
    stamps.append(pd.Timestamp(columns[-1][0] + timedelta(days=max_age + 1)))  # the source stopped
    values.append(np.nan)
    ev = pd.Series(values, index=pd.DatetimeIndex(stamps), dtype=float)
    ev = ev[~ev.index.duplicated(keep="last")].sort_index()
    return ev.reindex(index, method="ffill").astype(float)  # a NaN event stays NaN


def pit_history_series(
    symbol: str, index: pd.DatetimeIndex, conn: sqlite3.Connection
) -> dict[str, pd.Series]:
    """Per date, yearly fields and promoter holding from Screener history already public by then."""
    row = conn.execute(
        "SELECT detail FROM fund_snapshots WHERE source='screener' AND symbol=?", (symbol.upper(),)
    ).fetchone()
    try:
        detail = json.loads(row["detail"]) if row else {}
    except ValueError:
        detail = {}
    if not isinstance(detail, dict):
        detail = {}
    yearly, holding = _yearly_values(detail), _holding_values(detail)
    out = {f: _step_series(index, yearly, f, ANNUAL_LAG_DAYS, ANNUAL_MAX_AGE_DAYS) for f in YEARLY_FIELDS}
    for f in HOLDING_FIELDS:
        out[f] = _step_series(index, holding, f, SHAREHOLDING_LAG_DAYS, HOLDING_MAX_AGE_DAYS)
    return {f: out[f] for f in HISTORY_FIELDS}
