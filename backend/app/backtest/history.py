"""Split repair for price histories of stocks outside today's universe (SPEC §12.5)."""
from __future__ import annotations

import numpy as np
import pandas as pd

SPLIT_RATIOS = (1.25, 4 / 3, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 20, 25, 50, 100)

_RISE = 1.45
_DROP = 0.55
_TOL = 0.08
_MAX_FIXES = 6
_PRICE_COLS = ("open", "high", "low", "close")


def _match_ratio(inv: float) -> float | None:
    """Smallest ratio in SPLIT_RATIOS within ±8% of `inv`, or None."""
    for k in SPLIT_RATIOS:
        if round(abs(inv / k - 1), 9) < _TOL:
            return k
    return None


def _first_jump(close: pd.Series) -> int | None:
    """Position of the first bar whose close/previous close breaks the thresholds."""
    ratio = (close / close.shift(1)).to_numpy(dtype=float)
    hits = np.flatnonzero((ratio > _RISE) | (ratio < _DROP))  # NaN compares False
    return int(hits[0]) if len(hits) else None


def repair_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame | None, int]:
    """Return (repaired copy, fixes applied); (None, fixes) if the history can't be trusted."""
    out = frame.copy()
    out.attrs = dict(frame.attrs)
    if out.empty or "close" not in out.columns:
        return out, 0
    fixes = 0
    while True:
        pos = _first_jump(out["close"])
        if pos is None:
            return out, fixes
        ratio = float(out["close"].iloc[pos] / out["close"].iloc[pos - 1])
        if ratio > _RISE or fixes >= _MAX_FIXES:
            return None, fixes
        k = _match_ratio(1 / ratio)
        if k is None:
            return None, fixes
        cols = [c for c in _PRICE_COLS if c in out.columns]
        out[cols] = out[cols].astype(float)
        out.iloc[:pos, [out.columns.get_loc(c) for c in cols]] /= k
        if "volume" in out.columns:
            out["volume"] = out["volume"].astype(float)
            out.iloc[:pos, out.columns.get_loc("volume")] *= k
        fixes += 1
        out.attrs.pop("cache_key", None)  # values changed: no longer the cached frame
