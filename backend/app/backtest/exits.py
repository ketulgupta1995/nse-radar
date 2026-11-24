"""Exit rules for the backtester (SPEC §12.2). The engine only calls `setup` and `check`."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from app.analytics.indicators import Param
from app.analytics.rules import validate_rule

CheckResult = tuple[bool, float | None, str]


@dataclass(frozen=True)
class ExitDef:
    type: str
    label: str
    explain: str
    params: tuple[Param, ...]
    when: Literal["intraday", "close"]
    # (position at entry incl. entry_fill & atr14, resolved params) -> state (e.g. stop level)
    setup: Callable[[dict, dict], dict]
    # (state, today's bar row, {days_held, signals, idx}) -> (exit?, fill price or None = next open, reason)
    check: Callable[[dict, Mapping[str, float], dict], CheckResult]
    # optional validator for non-numeric params (e.g. a rule); returns the cleaned dict
    extra: Callable[[dict], dict] | None = None


EXITS: dict[str, ExitDef] = {}


def register(d: ExitDef) -> None:
    if d.type in EXITS:
        raise ValueError(f"exit already registered: {d.type}")
    EXITS[d.type] = d


def resolve_params(d: ExitDef, params: dict) -> dict:
    """Fill defaults and validate ranges (ValueError)."""
    known = {p.name for p in d.params}
    extras = {k: v for k, v in params.items() if k not in known}
    if extras and d.extra is None:
        raise ValueError(f"{d.type}: unknown parameter '{next(iter(extras))}'")
    out: dict = {}
    for p in d.params:
        try:
            v = float(params.get(p.name, p.default))
        except (TypeError, ValueError):
            raise ValueError(f"{d.type}.{p.name}: must be a number") from None
        if not p.min <= v <= p.max:
            raise ValueError(f"{d.type}.{p.name}: must be between {p.min:g} and {p.max:g}")
        out[p.name] = int(round(v)) if p.kind == "int" else v
    if d.extra is not None:
        out.update(d.extra(extras))
    return out


def catalogue() -> list[dict]:
    return [
        {
            "type": d.type,
            "label": d.label,
            "explain": d.explain,
            "when": d.when,
            "params": [
                {
                    "name": p.name,
                    "kind": p.kind,
                    "default": p.default,
                    "min": p.min,
                    "max": p.max,
                    "label": p.label,
                }
                for p in d.params
            ],
        }
        for d in EXITS.values()
    ]


def is_stop(type_: str) -> bool:
    return type_.startswith("stop_")


# ---- built-ins -----------------------------------------------------------------------------


def _check_stop(state: dict, bar: Mapping[str, float], ctx: dict) -> CheckResult:
    level = state["level"]
    if bar["open"] <= level:  # gapped through the stop: we get the open, which is worse
        return True, float(bar["open"]), "stop"
    if bar["low"] <= level:
        return True, level, "stop"
    return False, None, ""


def _check_trail(state: dict, bar: Mapping[str, float], ctx: dict) -> CheckResult:
    """Stop at (highest close since entry - k ATR). Today's close only raises tomorrow's level."""
    hit, price, reason = _check_stop(state, bar, ctx)
    if hit:
        return hit, price, "trailing stop"
    close = float(bar["close"])
    if close > state["hi"]:
        state["hi"] = close
        state["level"] = max(state["level"], close - state["k_atr"])
    return False, None, ""


def _check_target(state: dict, bar: Mapping[str, float], ctx: dict) -> CheckResult:
    level = state["level"]
    if bar["open"] >= level:
        return True, float(bar["open"]), "target"
    if bar["high"] >= level:
        return True, level, "target"
    return False, None, ""


def _check_time(state: dict, bar: Mapping[str, float], ctx: dict) -> CheckResult:
    if ctx["days_held"] >= state["days"]:
        return True, None, "time stop"
    return False, None, ""


def _check_rule(state: dict, bar: Mapping[str, float], ctx: dict) -> CheckResult:
    if ctx["signals"].get(ctx["idx"]):
        return True, None, "exit rule"
    return False, None, ""


def _rule_extra(extras: dict) -> dict:
    if "rule" not in extras:
        raise ValueError("rule_exit: 'rule' is required")
    validate_rule(extras["rule"])
    return {"rule": extras["rule"]}


def _atr_level(sign: int):
    return lambda pos, p: {"level": pos["entry_fill"] + sign * p["k"] * pos["atr14"]}


def _pct_level(sign: int):
    return lambda pos, p: {"level": pos["entry_fill"] * (1 + sign * p["pct"] / 100)}


def _k(default: float, label: str) -> tuple[Param, ...]:
    return (Param("k", "float", default, 0.1, 20, label),)


def _pct(default: float, label: str) -> tuple[Param, ...]:
    return (Param("pct", "float", default, 0.5, 100, label),)


for _d in (
    ExitDef(
        "stop_atr",
        "Stop-loss (ATR)",
        "Sell if the price falls this many ATRs (typical daily moves) below your buy price.",
        _k(2, "ATRs below entry"),
        "intraday",
        _atr_level(-1),
        _check_stop,
    ),
    ExitDef(
        "stop_trail_atr",
        "Trailing stop (ATR)",
        "Sell if the price falls this many ATRs below its highest close since you bought. "
        "Use 5 or so: 3 whipsawed in tests.",
        _k(5, "ATRs below the high"),
        "intraday",
        lambda pos, p: {
            "level": pos["entry_fill"] - p["k"] * pos["atr14"],
            "hi": pos["entry_fill"],
            "k_atr": p["k"] * pos["atr14"],
        },
        _check_trail,
    ),
    ExitDef(
        "stop_pct",
        "Stop-loss (%)",
        "Sell if the price falls this many percent below your buy price.",
        _pct(8, "% below entry"),
        "intraday",
        _pct_level(-1),
        _check_stop,
    ),
    ExitDef(
        "target_atr",
        "Profit target (ATR)",
        "Sell to lock in profit once the price rises this many ATRs above your buy price.",
        _k(4, "ATRs above entry"),
        "intraday",
        _atr_level(1),
        _check_target,
    ),
    ExitDef(
        "target_pct",
        "Profit target (%)",
        "Sell to lock in profit once the price rises this many percent above your buy price.",
        _pct(15, "% above entry"),
        "intraday",
        _pct_level(1),
        _check_target,
    ),
    ExitDef(
        "time_stop",
        "Time stop",
        "Sell after holding this many trading days, if nothing else triggered first.",
        (Param("days", "int", 40, 1, 500, "Trading days"),),
        "close",
        lambda pos, p: {"days": p["days"]},
        _check_time,
    ),
    ExitDef(
        "rule_exit",
        "Exit rule",
        "Sell when this rule turns true at the close (you sell at the next open).",
        (),
        "close",
        lambda pos, p: {},
        _check_rule,
        extra=_rule_extra,
    ),
):
    register(_d)
