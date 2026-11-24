"""Prices API (SPEC §7.5): adjusted bars, indicators and corporate-action markers."""

import math
from datetime import timedelta

import pandas as pd
from fastapi import APIRouter, HTTPException

from app import db, timeutil
from app.analytics import frames
from app.analytics import indicators as indcalc

router = APIRouter()


def _parse(spec: str) -> tuple[str, dict]:
    """'sma_slope:50:20' -> ('sma_slope', {'n': 50, 'k': 20}); params are positional."""
    name, *vals = spec.strip().split(":")
    d = indcalc.get(name)
    if len(vals) > len(d.params):
        raise ValueError(f"{name}: takes at most {len(d.params)} parameter(s)")
    params = {}
    for p, v in zip(d.params, vals, strict=False):
        try:
            params[p.name] = float(v)
        except ValueError:
            raise ValueError(f"{name}.{p.name}: '{v}' is not a number") from None
    return name, params


def _points(s: pd.Series) -> list[dict]:
    return [
        {"t": t.strftime("%Y-%m-%d"), "v": float(v)}
        for t, v in s.items()
        if v is not None and not math.isnan(v) and not math.isinf(v)
    ]


def _actions(sym: str, start: str) -> list[dict]:
    with db.tx() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT ex_date, subject, factor, source FROM corp_actions "
                "WHERE symbol=? AND kind IN ('split','bonus') AND ex_date>=? ORDER BY ex_date, source",
                (sym, start),
            )
        ]


@router.get("/prices/{sym}")
def prices(sym: str, start: str | None = None, indicators: str | None = None) -> dict:
    sym = sym.upper()
    start = start or (timeutil.today() - timedelta(days=730)).isoformat()
    try:
        pd.Timestamp(start)
    except ValueError:
        raise HTTPException(400, f"start: '{start}' is not a date") from None
    specs = [x for x in (indicators or "").split(",") if x.strip()]
    try:
        parsed = [(x.strip(), *_parse(x)) for x in specs]
    except ValueError as e:
        raise HTTPException(400, str(e)) from None

    frame = frames.load_frame(sym)  # full history so long averages are warmed up
    source = frame.attrs.get("source", "")
    bench = frames.load_benchmark() if any(n == "rel_strength" for _, n, _ in parsed) else None
    cut = pd.Timestamp(start)
    out_ind: dict[str, list[dict]] = {}
    if frame.empty:
        return {"symbol": sym, "source": source, "bars": [], "indicators": {k: [] for k, _, _ in parsed},
                "actions": _actions(sym, start)}  # fmt: skip
    for key, name, params in parsed:
        try:
            series = indcalc.compute(name, frame, bench, **params)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        out_ind[key] = _points(series[series.index >= cut])

    view = frame[frame.index >= cut]
    bars = [
        {
            "t": t.strftime("%Y-%m-%d"),
            "o": float(r.open), "h": float(r.high), "l": float(r.low), "c": float(r.close),
            "v": 0.0 if pd.isna(r.volume) else float(r.volume),
        }
        for t, r in view.iterrows()
    ]  # fmt: skip
    actions = _actions(sym, start)
    return {"symbol": sym, "source": source, "bars": bars, "indicators": out_ind, "actions": actions}
