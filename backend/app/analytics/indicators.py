"""Indicator registry and built-in indicators (SPEC §8.1).

Every indicator is `fn(frame, bench, **params) -> Series aligned to frame.index`.
Add one with a single `register(IndicatorDef(...))` call.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Param:
    name: str
    kind: Literal["int", "float"]
    default: float
    min: float
    max: float
    label: str


@dataclass(frozen=True)
class IndicatorDef:
    name: str
    label: str
    explain: str  # plain English, <= 140 chars, may use {n}/{k}
    params: tuple[Param, ...]
    fn: Callable[..., pd.Series]
    pane: Literal["price", "separate", "none"]
    custom: bool = False


_REGISTRY: dict[str, IndicatorDef] = {}


def register(d: IndicatorDef) -> None:
    if d.name in _REGISTRY:
        raise ValueError(f"indicator already registered: {d.name}")
    _REGISTRY[d.name] = d


def unregister(name: str) -> None:
    """Remove an indicator (used for custom indicators that get disabled or deleted)."""
    _REGISTRY.pop(name, None)


def get(name: str) -> IndicatorDef:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown indicator '{name}'") from None


def catalogue() -> list[dict]:
    out = []
    for d in _REGISTRY.values():
        defaults = {p.name: p.default for p in d.params}
        out.append(
            {
                "name": d.name,
                "label": d.label,
                "explain": d.explain,
                "explain_default": d.explain.format(**{k: _fmt(v) for k, v in defaults.items()}),
                "params": [asdict(p) for p in d.params],
                "pane": d.pane,
                "custom": d.custom,
            }
        )
    return out


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def resolve_params(d: IndicatorDef, params: dict) -> dict:
    """Fill defaults, coerce types and validate ranges (ValueError)."""
    known = {p.name: p for p in d.params}
    for key in params:
        if key not in known:
            raise ValueError(f"{d.name}: unknown parameter '{key}'")
    out: dict = {}
    for p in d.params:
        raw = params.get(p.name, p.default)
        try:
            v = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{d.name}.{p.name}: must be a number") from None
        if np.isnan(v) or not p.min <= v <= p.max:
            raise ValueError(f"{d.name}.{p.name}: must be between {_fmt(p.min)} and {_fmt(p.max)}")
        out[p.name] = int(round(v)) if p.kind == "int" else v
    return out


# Results memo for repeat backtests and screens. Only frames tagged by `frames.load_frame` (attrs
# "cache_key") take part, and `frames.invalidate()` clears it after any price write. Indicators that
# read other tables, and custom ones (their code can change under the same name), are never memoised.
MEMO_SIZE = 15000  # ~21 KB each (the index is shared with the frame); a liquid500 run uses ~6 per symbol
_DB_BACKED = {"breadth_above_sma", "results_move", "industry_rs", "industry_strength", "days_since_results"}
_memo: OrderedDict[tuple, pd.Series] = OrderedDict()
_memo_lock = threading.Lock()


def clear_memo() -> None:
    with _memo_lock:
        _memo.clear()


def _memo_key(d: IndicatorDef, frame: pd.DataFrame, bench: pd.Series | None, params: dict) -> tuple | None:
    token = frame.attrs.get("cache_key")
    if token is None or d.custom or d.name in _DB_BACKED or not len(frame):
        return None
    idx = frame.index  # attrs survive slicing, so the shape is part of the key
    b = None
    if bench is not None and len(bench):
        b = (len(bench), bench.index[0], bench.index[-1], float(bench.iloc[-1]))
    return (token, len(idx), idx[0], idx[-1], d.name, tuple(sorted(params.items())), b)


def compute(name: str, frame: pd.DataFrame, bench: pd.Series | None = None, **params) -> pd.Series:
    d = get(name)
    resolved = resolve_params(d, params)
    key = _memo_key(d, frame, bench, resolved)
    if key is not None:
        with _memo_lock:
            hit = _memo.get(key)
            if hit is not None:
                _memo.move_to_end(key)
                return hit.copy()
    s = d.fn(frame, bench, **resolved)
    s = s.reindex(frame.index) if not s.index.equals(frame.index) else s
    if key is not None:
        with _memo_lock:
            _memo[key] = s
            while len(_memo) > MEMO_SIZE:
                _memo.popitem(last=False)
        return s.copy()
    return s


# ---- built-ins -----------------------------------------------------------------------------


def _col(column: str) -> Callable[..., pd.Series]:
    return lambda f, b: f[column].astype(float)


def _sma(f, b, n):
    return f["close"].rolling(n).mean()


def _ema(f, b, n):
    return f["close"].ewm(span=n, adjust=False).mean()


def _rsi(f, b, n):
    delta = f["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    out[(loss == 0) & (gain > 0)] = 100.0  # only gains: avoid 0-division NaN
    return out.where(delta.notna().cummax())


def _atr(f, b, n):
    prev = f["close"].shift(1)
    parts = [f["high"] - f["low"], (f["high"] - prev).abs(), (f["low"] - prev).abs()]
    tr = pd.concat(parts, axis=1).max(axis=1)
    tr.iloc[0] = f["high"].iloc[0] - f["low"].iloc[0] if len(f) else np.nan
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _atr_pct(f, b, n):
    return _atr(f, b, n) / f["close"] * 100


def _return_pct(f, b, n):
    return (f["close"] / f["close"].shift(n) - 1) * 100


def _rel_strength(f, b, n):
    if b is None or len(b) == 0:
        return pd.Series(np.nan, index=f.index)
    bench = b.astype(float).reindex(f.index, method="ffill")
    return _return_pct(f, None, n) - (bench / bench.shift(n) - 1) * 100


def _index_vs_sma(f, b, n):
    if b is None or len(b) == 0:
        return pd.Series(np.nan, index=f.index)
    bench = b.astype(float)
    vs = (bench / bench.rolling(n).mean() - 1) * 100
    return vs.reindex(f.index, method="ffill")


def _breadth_above_sma(f, b, n):
    from app.analytics import frames  # lazy: frames needs the database, indicators stay pure

    s = frames.load_breadth(n)
    if len(s) == 0:
        return pd.Series(np.nan, index=f.index)
    return s.reindex(f.index, method="ffill")


def _industry_column(f, n, relative_to_market):
    """Stock-vs-industry or industry-vs-market difference, aligned to f. All-NaN if unknown."""
    nan = pd.Series(np.nan, index=f.index)
    sym = f.attrs.get("symbol")
    if not sym:
        return nan
    from app.analytics import frames  # lazy: frames needs the database, indicators stay pure

    name = frames.industry_of(sym)
    if not name:
        return nan
    table = frames.load_industry_returns(n)
    if name not in table.columns:
        return nan
    ind = table[name].reindex(f.index, method="ffill")
    if relative_to_market:
        return ind - table[frames.MARKET_COLUMN].reindex(f.index, method="ffill")
    return _return_pct(f, None, n) - ind


def _industry_rs(f, b, n):
    return _industry_column(f, n, False)


def _industry_strength(f, b, n):
    return _industry_column(f, n, True)


RESULTS_STALE_BARS = 120


def _result_dates(f) -> list[pd.Timestamp]:
    sym = f.attrs.get("symbol")
    if not sym:
        return []
    from app.analytics import frames  # lazy: frames needs the database, indicators stay pure

    return frames.results_dates(sym)


def _result_bars(f) -> list[int]:
    """Position of the first bar on/after each known-on date (de-duplicated, sorted)."""
    dates = _result_dates(f)
    if not dates or not len(f):
        return []
    return sorted({int(i) for i in f.index.searchsorted(pd.DatetimeIndex(dates), side="left")})


def _results_move(f, b, k):
    out = np.full(len(f), np.nan)
    close = f["close"].astype(float).to_numpy()
    pts = [i for i in _result_bars(f) if i < len(f)]
    for j, i in enumerate(pts):
        at = i + k - 1
        if i < 1 or at >= len(f):
            continue
        nxt = pts[j + 1] + k - 1 if j + 1 < len(pts) else len(f)
        out[at : min(nxt, i + RESULTS_STALE_BARS, len(f))] = (close[at] / close[i - 1] - 1) * 100
    return pd.Series(out, index=f.index)


def _days_since_results(f, b):
    out = np.full(len(f), np.nan)
    last = np.full(len(f), -1)
    for i in _result_bars(f):
        if i < len(f):
            last[i:] = i
    ok = last >= 0
    out[ok] = (np.arange(len(f)) - last)[ok]
    return pd.Series(out, index=f.index)


def _pct_from_high(f, b, n):
    return (f["close"] / f["high"].rolling(n).max() - 1) * 100


def _pct_from_low(f, b, n):
    return (f["close"] / f["low"].rolling(n).min() - 1) * 100


def _highest(f, b, n):
    return f["high"].shift(1).rolling(n).max()


def _lowest(f, b, n):
    return f["low"].shift(1).rolling(n).min()


def _volume_ratio(f, b, n):
    return f["volume"] / f["volume"].shift(1).rolling(n).mean()


def _sma_slope(f, b, n, k):
    s = _sma(f, b, n)
    return (s / s.shift(k) - 1) * 100


def _range_pct(f, b, n):
    return (f["high"].rolling(n).max() / f["low"].rolling(n).min() - 1) * 100


def _mom_smooth(f, b, n):
    vol = f["close"].pct_change().rolling(n).std() * np.sqrt(n) * 100
    return (_return_pct(f, b, n) / vol.where(vol > 0)).astype(float)


def _adx(f, b, n):
    up = f["high"].diff()
    down = -f["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    prev = f["close"].shift(1)
    parts = [f["high"] - f["low"], (f["high"] - prev).abs(), (f["low"] - prev).abs()]
    tr = pd.concat(parts, axis=1).max(axis=1)
    a = 1 / n
    tr_s = tr.ewm(alpha=a, adjust=False).mean()
    di_plus = 100 * plus_dm.ewm(alpha=a, adjust=False).mean() / tr_s
    di_minus = 100 * minus_dm.ewm(alpha=a, adjust=False).mean() / tr_s
    total = (di_plus + di_minus).where(lambda s: s > 0)
    dx = 100 * (di_plus - di_minus).abs() / total
    out = dx.ewm(alpha=a, adjust=False).mean().astype(float)
    out.iloc[: 2 * n] = np.nan
    return out


def _efficiency(f, b, n):
    c = f["close"].astype(float)
    path = c.diff().abs().rolling(n).sum()
    return ((c - c.shift(n)).abs() / path.where(path > 0) * 100).astype(float)


def _days_since_high(f, b, n):
    return f["high"].astype(float).rolling(n).apply(lambda w: n - 1 - np.argmax(w), raw=True)


def _traded_value_cr(f, b, n):
    return (f["close"] * f["volume"]).rolling(n).mean() / 1e7


def _p(name: str, default: int, lo: int, hi: int, label: str) -> Param:
    return Param(name, "int", default, lo, hi, label)


_N = "Number of days"
_BUILTINS = [
    *(
        IndicatorDef(
            c, c.capitalize(), f"The day's {c} {'volume' if c == 'volume' else 'price'}.", (), _col(c),
            "separate" if c == "volume" else "price",
        )
        for c in ("close", "open", "high", "low", "volume")
    ),
    IndicatorDef("sma", "Simple average",
                 "Average closing price of the last {n} days. Smooths out daily noise.",
                 (_p("n", 20, 2, 400, _N),), _sma, "price"),
    IndicatorDef("ema", "Exponential average",
                 "Like the {n}-day average, but recent days count more, so it reacts faster.",
                 (_p("n", 20, 2, 400, _N),), _ema, "price"),
    IndicatorDef("rsi", "RSI",
                 "Momentum gauge from 0–100. Above 70 often means overheated, below 30 beaten down.",
                 (_p("n", 14, 2, 50, _N),), _rsi, "separate"),
    IndicatorDef("atr", "ATR", "How many rupees the stock typically moves in a day ({n}-day average).",
                 (_p("n", 14, 2, 50, _N),), _atr, "separate"),
    IndicatorDef("atr_pct", "ATR %",
                 "Typical daily move as % of price. Higher means a more volatile stock.",
                 (_p("n", 14, 2, 50, _N),), _atr_pct, "separate"),
    IndicatorDef("return_pct", "Return %",
                 "% price change over the last {n} trading days (63 ≈ 3 months, 126 ≈ 6, 252 ≈ 1 year).",
                 (_p("n", 63, 1, 756, _N),), _return_pct, "none"),
    IndicatorDef("rel_strength", "Relative strength",
                 "How many % points the stock beat (or lagged) the Nifty 500 over {n} days.",
                 (_p("n", 63, 5, 756, _N),), _rel_strength, "none"),
    IndicatorDef("index_vs_sma", "Market vs its average",
                 "How far the Nifty 500 is above (+) or below (−) its {n}-day average. "
                 "Above 0 means the overall market is in an uptrend.",
                 (_p("n", 200, 20, 400, _N),), _index_vs_sma, "none"),
    IndicatorDef("breadth_above_sma", "Market breadth",
                 "% of all stocks trading above their {n}-day average. Below 50 means most stocks are "
                 "already falling, even when the index looks fine.",
                 (_p("n", 200, 20, 400, _N),), _breadth_above_sma, "none"),
    IndicatorDef("pct_from_high", "% from high",
                 "How far below its {n}-day high the price is (0 = at the high).",
                 (_p("n", 252, 20, 756, _N),), _pct_from_high, "none"),
    IndicatorDef("pct_from_low", "% from low", "How far above its {n}-day low the price is.",
                 (_p("n", 252, 20, 756, _N),), _pct_from_low, "none"),
    IndicatorDef("highest", "Highest high",
                 "Highest high of the previous {n} days (excluding today). Used for breakouts.",
                 (_p("n", 20, 2, 756, _N),), _highest, "price"),
    IndicatorDef("lowest", "Lowest low",
                 "Lowest low of the previous {n} days (excluding today). Used for breakdowns.",
                 (_p("n", 20, 2, 756, _N),), _lowest, "price"),
    IndicatorDef("volume_ratio", "Volume ratio",
                 "Today's volume vs its {n}-day average. 2 means twice the usual.",
                 (_p("n", 20, 2, 400, _N),), _volume_ratio, "separate"),
    IndicatorDef("sma_slope", "Average slope",
                 "Is the {n}-day average rising? % change over the last {k} days.",
                 (_p("n", 50, 2, 400, _N), _p("k", 20, 1, 252, "Look-back days")), _sma_slope, "none"),
    IndicatorDef("range_pct", "Range %",
                 "Size of the price range over {n} days. Small means a tight, quiet base.",
                 (_p("n", 63, 5, 756, _N),), _range_pct, "none"),
    IndicatorDef("mom_smooth", "Smooth momentum",
                 "{n}-day return divided by how bumpy the ride was. Higher means a steadier climb.",
                 (_p("n", 126, 20, 504, _N),), _mom_smooth, "none"),
    IndicatorDef("adx", "ADX",
                 "Trend strength from 0–100, ignoring direction. Above 25 usually means a clear trend.",
                 (_p("n", 14, 5, 50, _N),), _adx, "separate"),
    IndicatorDef("efficiency", "Trend efficiency",
                 "How straight the last {n} days' path was, 0–100. 100 = moved in a straight line.",
                 (_p("n", 20, 5, 252, _N),), _efficiency, "none"),
    IndicatorDef("days_since_high", "Days since high",
                 "Trading days since the {n}-day high. Small means the stock is making fresh highs.",
                 (_p("n", 252, 20, 756, _N),), _days_since_high, "none"),
    IndicatorDef("traded_value_cr", "Traded value (₹ cr)",
                 "Average rupees traded per day over {n} days, in crore. "
                 "Below 5 can be hard to sell quickly.",
                 (_p("n", 20, 5, 252, _N),), _traded_value_cr, "separate"),
    IndicatorDef("results_move", "Results reaction %",
                 "How much the price moved in the {k} days after the latest quarterly results. "
                 "Big positive moves often keep drifting up.",
                 (_p("k", 2, 1, 10, "Days after results"),), _results_move, "none"),
    IndicatorDef("industry_rs", "Beats its industry by",
                 "How many % points the stock beat (or lagged) the typical stock in its industry "
                 "over {n} days.",
                 (_p("n", 63, 5, 252, _N),), _industry_rs, "none"),
    IndicatorDef("industry_strength", "Industry vs market",
                 "How many % points the stock's industry beat the typical stock over {n} days. "
                 "Positive = a leading industry.",
                 (_p("n", 63, 5, 252, _N),), _industry_strength, "none"),
    IndicatorDef("days_since_results", "Days since results",
                 "Trading days since the latest quarterly results became public (0 = that day).",
                 (), _days_since_results, "none"),
]
for _d in _BUILTINS:
    register(_d)
