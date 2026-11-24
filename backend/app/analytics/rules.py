"""Rule DSL: validate, evaluate and describe screening rules (SPEC §8.2).

Op names and wording live only in `OPS`; adding an operator is one dict entry.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from app.analytics import explain, indicators
from app.analytics.fundamentals import FIELD_BY_NAME

MAX_DEPTH = 4
MAX_CONDITIONS = 20
RANK_MIN_STOCKS = 20


class RuleError(ValueError):
    """Invalid rule; the message starts with the JSON path of the problem."""


@dataclass(frozen=True)
class OpDef:
    name: str
    words: str
    fn: Callable[[pd.Series, pd.Series], pd.Series]


def _crosses_above(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def _crosses_below(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))


OPS: dict[str, OpDef] = {
    d.name: d
    for d in (
        OpDef(">", "is above", lambda a, b: a > b),
        OpDef(">=", "is at least", lambda a, b: a >= b),
        OpDef("<", "is below", lambda a, b: a < b),
        OpDef("<=", "is at most", lambda a, b: a <= b),
        OpDef("crosses_above", "crosses above", _crosses_above),
        OpDef("crosses_below", "crosses below", _crosses_below),
    )
}


class Operand(BaseModel):
    model_config = ConfigDict(frozen=True)
    ind: str | None = None
    params: dict[str, float] = {}
    offset: int = 0
    fund: str | None = None
    value: float | None = None
    times: float | None = None
    rank: bool = False

    def as_dict(self) -> dict:
        d = self.model_dump(exclude_none=True)
        if not d.get("params"):
            d.pop("params", None)
        if not d.get("offset"):
            d.pop("offset", None)
        if not d.get("rank"):
            d.pop("rank", None)
        return d


class Cond(BaseModel):
    model_config = ConfigDict(frozen=True)
    left: Operand
    op: str
    right: Operand


class Group(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str  # "all" | "any" | "not"
    items: tuple[Group | Cond, ...]


Rule = Group

_OPERAND_KEYS = {"ind", "params", "offset", "fund", "value", "times", "rank"}


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v)


def _parse_operand(o: object, path: str) -> Operand:
    if not isinstance(o, dict):
        raise RuleError(f"{path}: operand must be an object")
    extra = set(o) - _OPERAND_KEYS
    if extra:
        raise RuleError(f"{path}: unknown key '{sorted(extra)[0]}'")
    forms = [k for k in ("ind", "fund", "value") if k in o]
    if len(forms) != 1:
        raise RuleError(f"{path}: operand needs exactly one of 'ind', 'fund' or 'value'")
    form = forms[0]
    rank = o.get("rank", False)
    if "rank" in o:
        if form != "ind":
            raise RuleError(f"{path}.rank: only allowed on 'ind' operands")
        if not isinstance(rank, bool):
            raise RuleError(f"{path}.rank: must be true or false")
    times = o.get("times")
    if times is not None:
        if form == "value":
            raise RuleError(f"{path}.times: only allowed on 'ind' and 'fund' operands")
        if not _num(times) or times <= 0:
            raise RuleError(f"{path}.times: must be a number greater than 0")
    offset = o.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise RuleError(f"{path}.offset: must be a whole number, 0 or more")
    if form != "ind" and ("params" in o or offset):
        raise RuleError(f"{path}: 'params' and 'offset' only apply to 'ind' operands")
    if form == "ind":
        name = o["ind"]
        try:
            d = indicators.get(name)
        except (ValueError, TypeError):
            raise RuleError(f"{path}.ind: unknown indicator {name!r}") from None
        params = o.get("params") or {}
        if not isinstance(params, dict):
            raise RuleError(f"{path}.params: must be an object")
        try:
            indicators.resolve_params(d, params)
        except ValueError as e:
            raise RuleError(f"{path}.params: {e}") from None
        return Operand(ind=name, params=params, offset=offset, times=times, rank=rank)
    if form == "fund":
        field = o["fund"]
        meta = FIELD_BY_NAME.get(field) if isinstance(field, str) else None
        if meta is None:
            raise RuleError(f"{path}.fund: unknown fundamental field {field!r}")
        if not meta["numeric"]:
            raise RuleError(f"{path}.fund: {field!r} is text and cannot be used in a rule")
        return Operand(fund=field, times=times)
    if not _num(o["value"]):
        raise RuleError(f"{path}.value: must be a number")
    return Operand(value=o["value"])


def _parse_node(o: object, path: str, depth: int, count: list[int]) -> Group | Cond:
    if not isinstance(o, dict):
        raise RuleError(f"{path}: must be an object")
    if "op" in o or "left" in o or "right" in o:
        extra = set(o) - {"left", "op", "right"}
        if extra:
            raise RuleError(f"{path}: unknown key '{sorted(extra)[0]}'")
        for k in ("left", "op", "right"):
            if k not in o:
                raise RuleError(f"{path}.{k}: missing")
        if o["op"] not in OPS:
            raise RuleError(f"{path}.op: unknown operator {o['op']!r}")
        count[0] += 1
        if count[0] > MAX_CONDITIONS:
            raise RuleError(f"{path}: too many conditions (max {MAX_CONDITIONS})")
        return Cond(
            left=_parse_operand(o["left"], f"{path}.left"),
            op=o["op"],
            right=_parse_operand(o["right"], f"{path}.right"),
        )
    kinds = [k for k in ("all", "any", "not") if k in o]
    if len(kinds) != 1 or len(o) != 1:
        raise RuleError(f"{path}: must be a condition or have exactly one of 'all', 'any', 'not'")
    kind = kinds[0]
    if depth > MAX_DEPTH:
        raise RuleError(f"{path}: groups nested too deeply (max {MAX_DEPTH})")
    if kind == "not":
        return Group(kind=kind, items=(_parse_node(o["not"], f"{path}.not", depth + 1, count),))
    seq = o[kind]
    if not isinstance(seq, list):
        raise RuleError(f"{path}.{kind}: must be a list")
    if not seq:
        raise RuleError(f"{path}.{kind}: group is empty")
    items = tuple(_parse_node(x, f"{path}.{kind}[{i}]", depth + 1, count) for i, x in enumerate(seq))
    return Group(kind=kind, items=items)


def validate_rule(obj: dict) -> Rule:
    """Check a rule and return it as models. Raises RuleError with the JSON path."""
    node = _parse_node(obj, "rule", 1, [0])
    if not isinstance(node, Group):
        raise RuleError("rule: top level must be a group ('all', 'any' or 'not')")
    return node


# ---- evaluation ----------------------------------------------------------------------------


class _Ctx:
    def __init__(self, frame, bench, fund, ranks=None, memo: dict | None = None) -> None:
        self.frame, self.bench, self.fund = frame, bench, fund or {}
        self.ranks = ranks
        self.memo = memo
        self.cache: dict[tuple, pd.Series] = {}
        self.missing: list[str] = []
        self.values: dict[str, float | None] = {}

    def series(self, o: Operand) -> pd.Series:
        idx = self.frame.index
        if o.ind is not None:
            key = rank_key(o)
            if o.rank:
                got = (self.ranks or {}).get(key)
                if got is None:
                    s = pd.Series(np.nan, index=idx)
                    label = f"rank: {explain.label_operand(o.as_dict())}"
                    if label not in self.missing:
                        self.missing.append(label)
                else:
                    s = got.reindex(idx).astype(float)
                if o.offset:
                    s = s.shift(o.offset)
                return s * o.times if o.times is not None else s
            if key not in self.cache:
                self.cache[key] = indicators.compute(o.ind, self.frame, self.bench, **o.params)
            s = self.cache[key]
            if o.offset:
                s = s.shift(o.offset)
        elif o.fund is not None:
            v = self.fund.get(o.fund)
            if isinstance(v, pd.Series):
                s = v.reindex(idx).astype(float)
                ok = bool(s.notna().any())
            else:
                ok = _num(v)
                s = pd.Series(float(v) if ok else np.nan, index=idx)
            if not ok and o.fund not in self.missing:
                self.missing.append(o.fund)
        else:
            s = pd.Series(float(o.value), index=idx)  # type: ignore[arg-type]
        return s * o.times if o.times is not None else s


def _memo_key(cond: Cond, ctx: _Ctx) -> tuple[str, str]:
    canon = json.dumps(
        {"left": cond.left.as_dict(), "op": cond.op, "right": cond.right.as_dict()}, sort_keys=True
    )
    return canon, ctx.frame.attrs.get("symbol") or f"frame#{id(ctx.frame)}"


def _eval(node: Group | Cond, ctx: _Ctx) -> tuple[pd.Series, pd.Series]:
    """Return (result, valid); `valid` is False where an operand was NaN, so `not` can't flip it."""
    if isinstance(node, Cond):
        memo = ctx.memo
        key = _memo_key(node, ctx) if memo is not None else None
        if memo is not None and key in memo:
            return memo[key]
        left, right = ctx.series(node.left), ctx.series(node.right)
        valid = left.notna() & right.notna()
        res = OPS[node.op].fn(left, right).fillna(False).astype(bool) & valid
        if memo is not None:
            memo[key] = (res, valid)
        return res, valid
    parts = [_eval(x, ctx) for x in node.items]
    if node.kind == "not":
        res, valid = parts[0]
        return ~res & valid, valid
    # Every part is a bool Series on the frame's index, so combine the arrays directly.
    idx = parts[0][0].index
    combine = np.logical_and.reduce if node.kind == "all" else np.logical_or.reduce
    res = combine([p[0].to_numpy(dtype=bool) for p in parts])
    valid = combine([p[1].to_numpy(dtype=bool) for p in parts])
    return pd.Series(res, index=idx), pd.Series(valid, index=idx)


def _as_rule(rule: Rule | dict) -> Rule:
    return validate_rule(rule) if isinstance(rule, dict) else rule


def evaluate(
    rule, frame, bench=None, fund: dict | None = None, ranks: dict | None = None, memo: dict | None = None
) -> pd.Series:
    """Bool per bar (NaN -> False). Indicator series are computed once per call.

    `memo` (owned by the caller) caches each condition's result per symbol across calls; only share
    it between calls that use the same frames, benchmark, fundamentals and ranks.
    """
    res, _ = _eval(_as_rule(rule), _Ctx(frame, bench, fund, ranks, memo))
    return res.astype(bool)


def _walk(node: Group | Cond):
    if isinstance(node, Cond):
        yield node
    else:
        for x in node.items:
            yield from _walk(x)


def evaluate_latest(
    rule, frame, bench=None, fund: dict | None = None, ranks: dict | None = None
) -> tuple[bool, dict]:
    """(pass on the last bar, {operand label: value}); missing fundamentals show as 'missing: <field>'."""
    rule = _as_rule(rule)
    ctx = _Ctx(frame, bench, fund, ranks)
    res, _ = _eval(rule, ctx)
    ok = bool(res.iloc[-1]) if len(res) else False
    values: dict = {}
    for cond in _walk(rule):
        for o in (cond.left, cond.right):
            if o.value is not None:
                continue
            v = ctx.series(o).iloc[-1] if len(frame) else np.nan
            values[explain.label_operand(o.as_dict())] = None if pd.isna(v) else float(v)
    for field in ctx.missing:
        values[field if field.startswith("rank: ") else f"missing: {field}"] = None
    return ok, values


def rank_key(o: Operand) -> tuple:
    return (o.ind, tuple(sorted(o.params.items())))


def rank_operands(rule) -> list[Operand]:
    """Unique (by `rank_key`) ranked operands in the rule, in order."""
    seen: dict[tuple, Operand] = {}
    for c in _walk(_as_rule(rule)):
        for o in (c.left, c.right):
            if o.rank and rank_key(o) not in seen:
                seen[rank_key(o)] = o
    return list(seen.values())


def cross_rank(values: pd.DataFrame) -> pd.DataFrame:
    """Percentile (0-100, 100 = best) per date across symbols; dates with too few values are all-NaN."""
    out = values.rank(axis=1, pct=True, method="average") * 100
    out.loc[values.notna().sum(axis=1) < RANK_MIN_STOCKS] = np.nan
    return out


def fund_fields(rule) -> set[str]:
    """Names of the fundamental fields a rule uses."""
    return {o.fund for c in _walk(_as_rule(rule)) for o in (c.left, c.right) if o.fund is not None}


def uses_fundamentals(rule) -> bool:
    return any(o.fund is not None for c in _walk(_as_rule(rule)) for o in (c.left, c.right))


# ---- plain English -------------------------------------------------------------------------


def _operand_text(o: Operand) -> str:
    text = explain.label_operand(o.as_dict())
    return f"the {text}" if re.match(r"\d+-day (average|EMA)", text) else text


def _describe(node: Group | Cond, nested: bool) -> str:
    if isinstance(node, Cond):
        return f"{_operand_text(node.left)} {OPS[node.op].words} {_operand_text(node.right)}"
    if node.kind == "not":
        return f"NOT ({_describe(node.items[0], False)})"
    word = {"all": "AND", "any": "OR"}[node.kind]
    text = f" {word} ".join(_describe(x, True) for x in node.items)
    return f"({text})" if nested and len(node.items) > 1 else text


def describe(rule) -> str:
    """e.g. "Close is above the 200-day average AND (RSI (14) is below 45 OR ...)"."""
    return _describe(_as_rule(rule), False)
