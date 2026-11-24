"""Score components and the ranked shortlist (SPEC §10).

To add a score part: write one `ScoreComponent` (a `compute` that turns the candidates frame into
0-100 per symbol, and a `reasons` that explains one row), add it to `COMPONENTS` below, and give it
a weight in the `score_weights` setting. Nothing else needs to change. A component with weight 0, or
no weight at all, is skipped.
"""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from app import db, timeutil
from app.analytics import frames, indicators

HISTORY_DAYS = 730
MAX_REASONS = 4
FUND_FIELDS = ("roce_pct", "debt_to_equity", "profit_growth_3y_pct", "profit_growth_yoy_pct")


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    label: str
    explain: str
    compute: Callable[[pd.DataFrame], pd.Series]  # candidates frame -> 0-100 per symbol
    reasons: Callable[[pd.Series], list[tuple[float, str]]]  # one candidate row -> [(strength, text)]


def _pct(s: pd.Series) -> pd.Series:
    """Percentile among candidates, 0-100 (NaN stays NaN)."""
    return s.rank(pct=True) * 100


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(df[name], errors="coerce") if name in df else pd.Series(np.nan, index=df.index)


def _mean_or_50(parts: list[pd.Series], index: pd.Index) -> pd.Series:
    if not parts:
        return pd.Series(50.0, index=index)
    return pd.concat(parts, axis=1).mean(axis=1, skipna=True).fillna(50.0)


def _ok(v: Any) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v)) and not pd.isna(v)


def _clip(x: float) -> float:
    return float(min(100.0, max(0.0, x)))


# ---- rs ------------------------------------------------------------------------------------


def _rs(df: pd.DataFrame) -> pd.Series:
    return _mean_or_50([_pct(_col(df, "rs63")), _pct(_col(df, "rs126"))], df.index)


def _rs_reasons(r: pd.Series) -> list[tuple[float, str]]:
    out = []
    for col, months in (("rs63", 3), ("rs126", 6)):
        v = r.get(col)
        if _ok(v) and v > 0:
            out.append((_clip(v * 3), f"Beat the Nifty 500 by {v:.0f} pts over {months} months"))
    return out


# ---- trend ---------------------------------------------------------------------------------


def _trend(df: pd.DataFrame) -> pd.Series:
    close, s50, s200 = _col(df, "close"), _col(df, "sma50"), _col(df, "sma200")
    flags = [(close > s50), (close > s200), (s50 > s200)]
    parts = [f.astype(float) * 100 for f in flags] + [_pct(_col(df, "sma_slope"))]
    return pd.concat(parts, axis=1).mean(axis=1, skipna=True)


def _trend_reasons(r: pd.Series) -> list[tuple[float, str]]:
    out = []
    close, s50, s200, pfh = r.get("close"), r.get("sma50"), r.get("sma200"), r.get("pct_from_high")
    if _ok(close) and _ok(s200) and close > s200:
        out.append((40.0, "Above its 200-day average price"))
    if _ok(s50) and _ok(s200) and s50 > s200:
        out.append((40.0, "50-day average is above the 200-day average (uptrend)"))
    if _ok(pfh):
        out.append((_clip(100 - abs(pfh) * 5), f"{abs(pfh):.0f}% below its 52-week high"))
    return out


# ---- fundamentals --------------------------------------------------------------------------


def _fundamentals(df: pd.DataFrame) -> pd.Series:
    parts = []
    for name in FUND_FIELDS:
        s = _col(df, name)
        if s.notna().any():
            parts.append(_pct(-s if name == "debt_to_equity" else s))
    return _mean_or_50(parts, df.index)


def _fund_reasons(r: pd.Series) -> list[tuple[float, str]]:
    if not any(_ok(r.get(f)) for f in FUND_FIELDS):
        return [(20.0, "fundamentals missing")]
    out = []
    roce, de = r.get("roce_pct"), r.get("debt_to_equity")
    g3, gy = r.get("profit_growth_3y_pct"), r.get("profit_growth_yoy_pct")
    if _ok(roce) and roce > 0:
        out.append((_clip(roce * 3), f"ROCE {roce:.0f}%"))
    if _ok(de) and de <= 0.5:
        out.append((60.0, f"Low debt (debt to equity {de:.2f})"))
    if _ok(g3) and g3 > 0:
        out.append((_clip(g3 * 3), f"Profit growing {g3:.0f}% a year over 3 years"))
    if _ok(gy) and gy > 0:
        out.append((_clip(gy * 2), f"Profit up {gy:.0f}% on last year"))
    return out


# ---- backtest ------------------------------------------------------------------------------


def _backtest(df: pd.DataFrame) -> pd.Series:
    s = _col(df, "best_screen_oos_excess")
    return _pct(s).fillna(50.0)


def _backtest_reasons(r: pd.Series) -> list[tuple[float, str]]:
    v = r.get("best_screen_oos_excess")
    if not _ok(v):
        return [(20.0, "screen not backtested")]
    if v > 0:
        return [(_clip(v * 5), f"Its screen beat the index by {v:.0f}%/yr out-of-sample")]
    return []


COMPONENTS: dict[str, ScoreComponent] = {
    c.name: c
    for c in (
        ScoreComponent(
            "rs", "Relative strength",
            "How much the stock beat the Nifty 500 over 3 and 6 months, compared with the other candidates.",
            _rs, _rs_reasons,
        ),
        ScoreComponent(
            "trend", "Trend",
            "Is the price above its 50- and 200-day averages, and is the average still rising?",
            _trend, _trend_reasons,
        ),
        ScoreComponent(
            "fundamentals", "Business quality",
            "Return on capital, low debt and profit growth, against the other candidates. 50 if missing.",
            _fundamentals, _fund_reasons,
        ),
        ScoreComponent(
            "backtest", "Screen track record",
            "How far the screen that picked it beat the index in its hidden test. 50 if untested.",
            _backtest, _backtest_reasons,
        ),
    )
}  # fmt: skip


# ---- candidates ----------------------------------------------------------------------------


def canonical(rule: dict) -> str:
    return json.dumps(rule, sort_keys=True, separators=(",", ":"))


def _screen_excess(c) -> dict[int, float]:
    """screen id -> out-of-sample excess of the latest done backtest with the same entry rule."""
    screens = {r["id"]: canonical(json.loads(r["rule"])) for r in c.execute("SELECT id, rule FROM screens")}
    latest: dict[str, float | None] = {}
    rows = c.execute(
        "SELECT config, metrics FROM backtests WHERE status='done' AND kind IN ('final','legacy') ORDER BY id"
    ).fetchall()
    for r in rows:  # later rows overwrite earlier ones, so the newest backtest wins
        try:
            rule = canonical(json.loads(r["config"])["entry_rule"])
            latest[rule] = ((json.loads(r["metrics"]) or {}).get("oos") or {}).get("excess")
        except (KeyError, TypeError, ValueError):
            continue
    return {sid: latest[rule] for sid, rule in screens.items() if latest.get(rule) is not None}  # type: ignore[misc]


def _read_tables() -> tuple[
    dict[str, list[tuple[int, str]]], dict[int, float], dict[str, dict], dict[str, str]
]:
    with db.tx() as c:
        rows = c.execute(
            "SELECT r.symbol, r.screen_id, s.name FROM screen_results r JOIN screens s ON s.id=r.screen_id"
        ).fetchall()
        excess = _screen_excess(c)
        fund = {
            r["symbol"]: json.loads(r["data"]) for r in c.execute("SELECT symbol, data FROM fundamentals")
        }
        names = {r["symbol"]: r["name"] for r in c.execute("SELECT symbol, name FROM symbols")}
    by_symbol: dict[str, list[tuple[int, str]]] = {}
    for r in rows:
        by_symbol.setdefault(r["symbol"], []).append((r["screen_id"], r["name"]))
    return by_symbol, excess, fund, names


def _ind(f: pd.DataFrame, bench: pd.Series, name: str, **p) -> float:
    v = indicators.compute(name, f, bench, **p).iloc[-1]
    return float(v) if _ok(v) else float("nan")


def candidates_frame(conn=None) -> pd.DataFrame:
    """One row per symbol in any screen's latest results, with the columns the components use.

    Loads price frames, so never call it inside a write transaction. `conn` is accepted for the
    SPEC signature and ignored (tables are read in a short transaction of their own).
    """
    by_symbol, excess, fund, names = _read_tables()
    start = (timeutil.today() - timedelta(days=HISTORY_DAYS)).isoformat()
    bench = frames.load_benchmark()
    rows = []
    for sym, screens in sorted(by_symbol.items()):
        f = frames.load_frame(sym, start)
        if len(f) == 0:
            continue

        ex = [excess[sid] for sid, _ in screens if sid in excess]
        row: dict[str, Any] = {
            "symbol": sym, "name": names.get(sym), "close": float(f["close"].iloc[-1]),
            "rs63": _ind(f, bench, "rel_strength", n=63), "rs126": _ind(f, bench, "rel_strength", n=126),
            "sma50": _ind(f, bench, "sma", n=50), "sma200": _ind(f, bench, "sma", n=200),
            "sma_slope": _ind(f, bench, "sma_slope", n=50, k=20),
            "pct_from_high": _ind(f, bench, "pct_from_high", n=252),
            "best_screen_oos_excess": max(ex) if ex else float("nan"),
            "screens": [n for _, n in screens],
        }  # fmt: skip
        for name in FUND_FIELDS:
            v = fund.get(sym, {}).get(name)
            row[name] = float(v) if isinstance(v, (int, float)) else float("nan")
        rows.append(row)
    df = pd.DataFrame(rows)
    return df.set_index("symbol", drop=False) if len(df) else df


def score_frame(df: pd.DataFrame, weights: dict[str, float]) -> list[dict]:
    """Rank a candidates frame: total = sum(w*c) / sum(w) over components with weight > 0."""
    if len(df) == 0:
        return []
    active = [c for n, c in COMPONENTS.items() if float(weights.get(n, 0) or 0) > 0]
    values = {c.name: c.compute(df).clip(0, 100) for c in active}
    wsum = sum(float(weights[c.name]) for c in active)
    out = []
    for sym, row in df.iterrows():
        comp = {n: round(float(v[sym]), 1) for n, v in values.items()}
        total = sum(float(weights[n]) * comp[n] for n in comp) / wsum if wsum else 0.0
        reasons: list[tuple[float, str]] = []
        for c in active:
            reasons += c.reasons(row)
        reasons.sort(key=lambda r: -r[0])
        out.append({
            "symbol": sym, "name": row.get("name"), "score": round(total, 1), "components": comp,
            "reasons": [t for _, t in reasons[:MAX_REASONS]], "screens": list(row.get("screens", [])),
            "last_close": row.get("close"),
        })  # fmt: skip
    return sorted(out, key=lambda r: (-r["score"], r["symbol"]))


def score_candidates(conn=None) -> list[dict]:
    """Today's ranked shortlist, best first."""
    df = candidates_frame(conn)
    return score_frame(df, db.get_setting("score_weights"))
