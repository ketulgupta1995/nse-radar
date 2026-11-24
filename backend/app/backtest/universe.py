"""Point-in-time "liquid 500" universe: who was among the most-traded stocks each month (SPEC §12.5)."""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from app import bardb
from app.analytics import adjust, price_store
from app.analytics import frames as frames_mod
from app.sources import registry

WINDOW = 6
MIN_MONTHS = 3

_ranks_cache: dict[tuple, pd.DataFrame] = frames_mod.register_cache({})


def _prev_month(key: str) -> str:
    return str(pd.Period(key, "M") - 1)


def liquidity_ranks(conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    """Index 'YYYY-MM' (sorted), columns symbols; 1 = most traded. NaN = unknown / not trading.

    Cached per bars-source order and newest bar date; `frames.invalidate()` (any price write)
    clears it, and the date covers a run that races the nightly ingest.
    """
    with adjust.use_conn(conn) as c:
        sources = registry.ordered("bars", c)
        newest = c.execute(bardb.LAST_DAY_SQL).fetchone()[0]
        key = (tuple(src.name for src in sources), newest)
        hit = _ranks_cache.get(key)
        if hit is None:
            hit = _ranks_cache[key] = _compute_ranks(c, sources)
    return hit.copy()


def _monthly_sql(c: sqlite3.Connection, sources: list) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    seen: set[str] = set()
    for src in sources:
        rows = c.execute(
            f"SELECT y.symbol, m, v FROM (SELECT sym_id, {bardb.MONTH_SQL} AS m, "
            f"AVG({bardb.TRADED_SQL}) AS v FROM bars WHERE source_id={bardb.SRC_ID} GROUP BY sym_id, m) "
            "JOIN bar_symbols y ON y.id = sym_id",
            (src.name,),
        ).fetchall()
        df = pd.DataFrame([tuple(r) for r in rows], columns=["symbol", "m", "v"])
        mine = df[~df["symbol"].isin(seen)]
        seen.update(mine["symbol"])
        parts.append(mine[mine["v"].notna()])
    return pd.concat(parts) if parts else pd.DataFrame(columns=["symbol", "m", "v"])


def _compute_ranks(c: sqlite3.Connection, sources: list) -> pd.DataFrame:
    ctx = price_store.ensure_valid(c)
    allv = _monthly_sql(c, sources) if ctx is None else price_store.monthly_average(c, ctx, sources)
    skip = {
        r[0]
        for r in c.execute(
            "SELECT symbol FROM instruments WHERE isin LIKE 'INF%' OR series IN ('RR','IV')"
        )
    }
    allv = allv[~allv["symbol"].isin(skip)]
    if allv.empty:
        return pd.DataFrame(index=pd.Index([], dtype=object))
    monthly = allv.pivot(index="m", columns="symbol", values="v").sort_index()
    full = pd.period_range(monthly.index[0], monthly.index[-1], freq="M").astype(str)
    monthly = monthly.reindex(full)
    smooth = monthly.rolling(WINDOW, min_periods=MIN_MONTHS).mean()
    smooth = smooth.where(monthly.notna())
    return smooth.rank(axis=1, ascending=False, method="min")


def eligible_mask(ranks: pd.DataFrame, dates: pd.DatetimeIndex, symbol: str, top_n: int = 500) -> pd.Series:
    """True on dates where the symbol's rank in the previous calendar month is <= top_n."""
    if symbol not in ranks.columns or not len(dates):
        return pd.Series(False, index=dates)
    months = np.array([int(k[:4]) * 12 + int(k[5:7]) - 1 for k in ranks.index])
    prev = dates.year.to_numpy() * 12 + dates.month.to_numpy() - 2  # previous calendar month
    pos = pd.Index(months).get_indexer(prev)
    col = ranks[symbol].to_numpy(dtype=float)
    got = np.where(pos >= 0, col[pos], np.nan)
    return pd.Series(got <= top_n, index=dates)  # NaN compares False


def candidate_symbols(ranks: pd.DataFrame, start: str, top_n: int = 500) -> list[str]:
    """Today's universe plus every symbol ranked <= top_n in some month >= start minus one month."""
    first = _prev_month(pd.Timestamp(start).strftime("%Y-%m"))
    out = set(frames_mod.universe())
    if len(ranks):
        sub = ranks[ranks.index >= first]
        out |= set(sub.columns[(sub <= top_n).any(axis=0)])
    return sorted(out)
