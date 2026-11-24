"""Backtest metrics, in-sample / out-of-sample split and honest warnings (SPEC §12.3)."""

import hashlib
import json
import math

import numpy as np
import pandas as pd

SURVIVORSHIP = (
    "Survivorship bias: tested on today's Nifty 500 list; companies that dropped out are missing, "
    "so results look better than reality."
)
UNIVERSE = (
    "Universe: the 500 most-traded stocks each month (a stand-in for the Nifty 500 at the time), "
    "including companies that were later delisted."
)
PRICE_ONLY = "Price-only returns; dividends ignored."
PAST = "Past results do not guarantee future returns."
FEW_TRADES = "Few trades (<30): results unreliable"
OVERFIT = "Out-of-sample result much worse than in-sample: likely overfit"
CHURN = (
    "Trades last under 5 days on average: the entry and exit rules may contradict each other "
    "(for example buying a dip, then selling because the price is below its average)."
)


def _r(x: float | None, n: int = 2) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), n)


def _cagr(values: list[float], dates: list[str]) -> float | None:
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        return None
    days = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days
    if days <= 0:
        return None
    return ((values[-1] / values[0]) ** (365.25 / days) - 1) * 100


def _exposure(dates: list[str], trades: list[dict]) -> float | None:
    if not dates:
        return None
    d = np.array(dates)
    diff = np.zeros(len(d) + 1)
    for t in trades:  # a position is held from its entry date up to (not including) its exit date
        lo = int(np.searchsorted(d, t["entry_date"], side="left"))
        hi = int(np.searchsorted(d, t["exit_date"], side="left"))
        if hi > lo:
            diff[lo] += 1
            diff[hi] -= 1
    return float((np.cumsum(diff)[:-1] > 0).mean() * 100)


def compute_metrics(equity: list[dict], trades: list[dict], start: str, end: str) -> dict:
    """Metrics for equity points and trades (exit date) inside [start, end]. Drawdown is negative."""
    eq = [e for e in equity if start <= e["t"] <= end]
    tr = [t for t in trades if start <= t["exit_date"] <= end]
    dates = [e["t"] for e in eq]
    vals = [e["v"] for e in eq]
    cagr = _cagr(vals, dates)
    bpts = [(e["t"], e["bench"]) for e in eq if e.get("bench") is not None]
    bench = _cagr([b for _, b in bpts], [t for t, _ in bpts]) if bpts else None
    s = pd.Series(vals, dtype=float)
    dd = float((s / s.cummax() - 1).min() * 100) if len(s) else None
    vol = float(s.pct_change().std() * math.sqrt(252) * 100) if len(s) > 2 else None
    wins = [t for t in tr if t["pnl"] > 0]
    losses = [t for t in tr if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    best = max(tr, key=lambda t: t["pnl_pct"], default=None)
    worst = min(tr, key=lambda t: t["pnl_pct"], default=None)
    return {
        "cagr": _r(cagr),
        "bench_cagr": _r(bench),
        "excess": _r(cagr - bench) if cagr is not None and bench is not None else None,
        "max_drawdown": _r(dd),
        "volatility": _r(vol),
        "trades": len(tr),
        "win_rate": _r(len(wins) / len(tr) * 100) if tr else None,
        "avg_win": _r(sum(t["pnl_pct"] for t in wins) / len(wins)) if wins else None,
        "avg_loss": _r(sum(t["pnl_pct"] for t in losses) / len(losses)) if losses else None,
        "profit_factor": _r(gross_win / gross_loss) if gross_loss > 0 else None,
        "avg_days": _r(sum(t["days"] for t in tr) / len(tr), 1) if tr else None,
        "exposure": _r(_exposure(dates, tr), 1),
        "best": {"symbol": best["symbol"], "pnl_pct": best["pnl_pct"]} if best else None,
        "worst": {"symbol": worst["symbol"], "pnl_pct": worst["pnl_pct"]} if worst else None,
    }


def fingerprint(cfg: dict) -> str:
    """Identify a strategy regardless of its dates: sha256 of the config minus start, oos_start and end."""
    core = {k: v for k, v in cfg.items() if k not in ("start", "oos_start", "end")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def split_metrics(result: dict, oos_start: str) -> dict:
    """{"all","is","oos"}: in-sample is everything before `oos_start`, out-of-sample from it on."""
    eq, tr = result["equity"], result["trades"]
    if not eq:
        empty = compute_metrics([], [], "", "")
        return {"all": empty, "is": empty, "oos": empty}
    first, last = eq[0]["t"], eq[-1]["t"]
    before = [e["t"] for e in eq if e["t"] < oos_start]
    is_end = before[-1] if before else first
    return {
        "all": compute_metrics(eq, tr, first, last),
        "is": compute_metrics(eq, tr, first, is_end),
        "oos": compute_metrics(eq, tr, oos_start, last),
    }


def warnings_for(result: dict, cfg=None) -> list[str]:
    """Always-on warnings, then the engine's own (fundamentals etc.), then data-driven ones."""
    universe = getattr(cfg, "universe", "current")
    first = UNIVERSE if universe == "liquid500" else SURVIVORSHIP
    out = [first, PRICE_ONLY, PAST, *result.get("warnings", [])]
    m = result.get("metrics") or {}
    whole = m.get("all") or m.get("is") or {}
    if whole.get("trades", len(result["trades"])) < 30:
        out.append(FEW_TRADES)
    avg_days = whole.get("avg_days")
    if avg_days is not None and avg_days < 5 and len(result["trades"]) >= 30:
        out.append(CHURN)
    is_x, oos_x = (m.get("is") or {}).get("excess"), (m.get("oos") or {}).get("excess")
    if is_x is not None and oos_x is not None and is_x > 0 and oos_x < 0.5 * is_x:
        out.append(OVERFIT)
    return list(dict.fromkeys(out))
