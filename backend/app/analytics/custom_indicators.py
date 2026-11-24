"""Custom (AI-written, owner-approved) indicators (SPEC §8.3).

`static_check` only parses; nothing runs until the owner approves, and the first run
(`trial_run`) happens in a child process with a timeout.
"""

from __future__ import annotations

import ast
import logging
import math
import multiprocessing
import re
from typing import Any

import numpy as np
import pandas as pd

from app import db
from app.analytics import indicators
from app.analytics.indicators import IndicatorDef, Param

log = logging.getLogger(__name__)

MAX_CODE = 4000
TRIAL_TIMEOUT = 10.0
TRIAL_BARS = 300
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")

SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs, "min": min, "max": max, "len": len, "range": range, "float": float, "int": int,
    "round": round, "sum": sum, "zip": zip, "enumerate": enumerate, "isinstance": isinstance,
    "ValueError": ValueError,
}  # fmt: skip

BLOCKED_NAMES = frozenset(
    "open exec eval compile __import__ globals locals vars dir getattr setattr delattr input "
    "breakpoint type object super memoryview".split()
)
BLOCKED_ATTRS = frozenset(
    "load loads save savez savetxt loadtxt genfromtxt tofile memmap eval query pipe apply applymap "
    "map agg aggregate transform io lib os sys ctypes testing api core compat plotting options "
    "set_option system".split()
)
BLOCKED_ATTR_PREFIXES = ("_", "read_", "to_", "from")

ALLOWED_ATTRS = frozenset(
    # frame and bench data
    "open high low close volume index values iloc loc size empty "
    # Series and DataFrame maths
    "rolling ewm expanding mean median std var sum min max abs shift diff pct_change cumsum cumprod "
    "cummax cummin clip where mask fillna ffill bfill dropna isna notna astype round rank corr cov "
    "quantile idxmax idxmin any all gt lt ge le eq ne add sub mul div truediv pow between reindex "
    "align copy count nlargest nsmallest "
    # numpy functions
    "nan inf log log1p exp sqrt sign maximum minimum isnan isfinite arange zeros ones full nan_to_num "
    "square power floor ceil polyfit linspace percentile float64 array asarray "
    # pandas constructors
    "Series DataFrame concat "
    # math
    "pi e fabs".split()
)


def allowed_vocabulary() -> list[str]:
    return sorted(ALLOWED_ATTRS)


# ---- static check (never executes anything) ------------------------------------------------


def static_check(code: str) -> list[str]:
    """Return a list of problems; an empty list means the code passed."""
    if not isinstance(code, str) or not code.strip():
        return ["The code is empty."]
    if len(code) > MAX_CODE:
        return [f"The code is longer than {MAX_CODE} characters."]
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError) as e:
        return [f"The code isn't valid Python: {e}"]
    problems: list[str] = []
    body = tree.body
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef) or body[0].name != "compute":
        problems.append(
            "The code must be one function, `def compute(frame, bench, **params)`, and nothing else."
        )
    for node in ast.walk(tree):
        problems.extend(_node_problems(node))
    seen: set[str] = set()
    return [p for p in problems if not (p in seen or seen.add(p))]


def _node_problems(node: ast.AST) -> list[str]:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return ["Imports are not allowed."]
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return [f"`{type(node).__name__.lower()}` is not allowed."]
    if isinstance(node, ast.Name):
        if node.id in BLOCKED_NAMES or node.id.startswith("_"):
            return [f"The name `{node.id}` is not allowed."]
    elif isinstance(node, ast.Attribute):
        a = node.attr
        if a in BLOCKED_ATTRS or a.startswith(BLOCKED_ATTR_PREFIXES):
            return [f"The attribute `.{a}` is not allowed."]
        if a not in ALLOWED_ATTRS:
            return [f"`{a}` isn't on the allowed list"]
    elif isinstance(node, ast.arg):
        if node.arg.startswith("_"):
            return [f"The argument name `{node.arg}` is not allowed."]
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if node.name.startswith("_"):
            return [f"The name `{node.name}` is not allowed."]
    return []


# ---- metadata validation -------------------------------------------------------------------


def validate_name(name: str) -> str | None:
    if not isinstance(name, str) or not NAME_RE.match(name):
        return "The name must be 3-31 lowercase letters, digits or underscores, starting with a letter."
    try:
        existing = indicators.get(name)
    except ValueError:
        return None
    if not existing.custom:
        return f"'{name}' is already a built-in indicator."
    return None


def validate_params_schema(schema: Any) -> list[Param]:
    """Parse a list of Param-like dicts; ValueError on the first problem."""
    if not isinstance(schema, list):
        raise ValueError("params_schema must be a list")
    out: list[Param] = []
    for i, raw in enumerate(schema):
        where = f"params_schema[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where}: must be an object")
        name, kind, label = raw.get("name"), raw.get("kind"), raw.get("label")
        if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
            raise ValueError(f"{where}.name: must be a plain identifier")
        if name in ("frame", "bench") or any(p.name == name for p in out):
            raise ValueError(f"{where}.name: '{name}' is reserved or repeated")
        if kind not in ("int", "float"):
            raise ValueError(f"{where}.kind: must be 'int' or 'float'")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"{where}.label: required")
        try:
            default, lo, hi = (float(raw[k]) for k in ("default", "min", "max"))
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{where}: default, min and max must be numbers") from None
        if not all(math.isfinite(v) for v in (default, lo, hi)) or not lo <= default <= hi:
            raise ValueError(f"{where}: need min <= default <= max")
        out.append(Param(name, kind, default, lo, hi, label.strip()))
    return out


# ---- running approved code -----------------------------------------------------------------


def _build_compute(code: str):
    env: dict[str, Any] = {"__builtins__": SAFE_BUILTINS, "pd": pd, "np": np, "math": math}
    exec(code, env)  # noqa: S102 - only after static_check and owner approval
    return env["compute"]


def _coerce(result: Any, frame: pd.DataFrame) -> pd.Series:
    if not isinstance(result, pd.Series):
        raise ValueError("compute() must return a pandas Series")
    if len(result) != len(frame):
        raise ValueError(f"compute() returned {len(result)} values for {len(frame)} bars")
    try:
        values = result.astype(float).to_numpy()
    except (TypeError, ValueError):
        raise ValueError("compute() must return numbers") from None
    return pd.Series(values, index=frame.index)


def _synthetic_frame(n: int = TRIAL_BARS) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2024-01-01", periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = rng.integers(100_000, 1_000_000, n).astype(float)
    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    )
    bench = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, n))), index=idx)
    return frame, bench


def _child(conn, code: str, params: dict) -> None:
    try:
        frame, bench = _synthetic_frame()
        series = _coerce(_build_compute(code)(frame, bench, **params), frame)
        tail = [None if math.isnan(v) else float(v) for v in series.tail(5)]
        conn.send({"ok": True, "sample": tail})
    except BaseException as e:  # noqa: BLE001 - report anything the code did wrong
        conn.send({"ok": False, "error": f"{type(e).__name__}: {e}"})
    finally:
        conn.close()


def trial_run(code: str, params: dict) -> dict:
    """Run `code` once on a synthetic frame in a child process (10 s timeout, killed after)."""
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(child, code, dict(params)), daemon=True)
    proc.start()
    child.close()
    try:
        if parent.poll(TRIAL_TIMEOUT):
            try:
                return parent.recv()
            except EOFError:
                return {"ok": False, "error": "The trial run stopped without an answer."}
        return {
            "ok": False,
            "error": f"The trial run took longer than {TRIAL_TIMEOUT:g} seconds and was stopped.",
        }
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join(5)
        parent.close()


# ---- registry ------------------------------------------------------------------------------


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize()


def register_row(row: dict) -> None:
    """Register one approved row as an IndicatorDef(custom=True)."""
    name = row["name"]
    if validate_name(name) is not None:
        raise ValueError(f"cannot register '{name}'")
    params = validate_params_schema(row["params_schema"])
    compute = _build_compute(row["code"])

    def fn(frame: pd.DataFrame, bench: pd.Series | None, **kw) -> pd.Series:
        return _coerce(compute(frame, bench, **kw), frame)

    indicators.unregister(name)
    indicators.register(
        IndicatorDef(name, _label(name), row["explain"], tuple(params), fn, "separate", custom=True)
    )


def unregister_custom(name: str) -> None:
    try:
        if indicators.get(name).custom:
            indicators.unregister(name)
    except ValueError:
        pass


def load_approved() -> int:
    """Register every approved row (re-checked statically). Returns how many were loaded."""
    import json

    with db.tx() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM custom_indicators WHERE status='approved'")]
    loaded = 0
    for row in rows:
        try:
            if problems := static_check(row["code"]):
                raise ValueError("; ".join(problems))
            row["params_schema"] = json.loads(row["params_schema"])
            register_row(row)
            loaded += 1
        except Exception:
            log.exception("could not load custom indicator %s", row.get("name"))
    return loaded
