"""Plain-English wording for indicators and rule operands (SPEC §8.1, §8.2)."""

from __future__ import annotations

from app.analytics import indicators
from app.analytics.fundamentals import FIELD_BY_NAME

_ACRONYMS = {"roce", "roe", "pe", "eps", "ebitda", "pb", "ev", "npm", "opm", "rs"}
_PLAIN = {"close": "Close", "open": "Open", "high": "High", "low": "Low", "volume": "Volume"}


def _num(v) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def explain_indicator(name: str, params: dict | None = None) -> str:
    d = indicators.get(name)
    return d.explain.format(**{k: _num(v) for k, v in indicators.resolve_params(d, params or {}).items()})


def _fund_label(field: str) -> str:
    if field in FIELD_BY_NAME:
        return FIELD_BY_NAME[field]["label"]
    words = field.split("_")
    out = []
    for i, w in enumerate(words):
        if w == "pct":
            out.append("%")
        elif w in _ACRONYMS:
            out.append(w.upper())
        else:
            out.append(w.capitalize() if i == 0 else w)
    return " ".join(out)


def _ind_label(name: str, params: dict) -> str:
    if name in _PLAIN:
        return _PLAIN[name]
    d = indicators.get(name)
    p = indicators.resolve_params(d, params)
    if name == "sma":
        return f"{p['n']}-day average"
    if name == "ema":
        return f"{p['n']}-day EMA"
    if name == "rsi":
        return f"RSI ({p['n']})"
    if name == "sma_slope":
        return f"{p['n']}-day average slope ({p['k']} days)"
    return f"{d.label} ({', '.join(str(v) for v in p.values())})" if p else d.label


def label_operand(op: dict) -> str:
    """Short label for a rule operand, e.g. "200-day average", "RSI (14)", "Volume ×2", "ROCE %"."""
    if "ind" in op:
        text = _ind_label(op["ind"], op.get("params") or {})
    elif "fund" in op:
        text = _fund_label(op["fund"])
    elif "value" in op:
        v = op["value"]
        return _num(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
    else:
        raise ValueError("operand must have 'ind', 'fund' or 'value'")
    if op.get("rank"):
        text += ", rank"
    if op.get("times") not in (None, 1, 1.0):
        text += f" ×{_num(op['times'])}"
    if op.get("offset"):
        text += f", {_num(op['offset'])} days ago"
    return text
