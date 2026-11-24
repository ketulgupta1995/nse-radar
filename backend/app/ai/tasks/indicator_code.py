"""Ask Claude to write a custom indicator (SPEC §11 `indicator_code`).

The reply is only checked statically here. Nothing is executed, trial-run or imported.
"""

from __future__ import annotations

import logging

from app import db
from app.ai import base
from app.ai.base import AIError, AITask, register_task
from app.ai.tasks._json import extract_json
from app.analytics import custom_indicators as ci

log = logging.getLogger(__name__)

EXAMPLES = r"""
Example 1: "average true range as a percent of price"
{"name":"atr_pct","explain":"How much the stock typically moves in a day, as a percent of its price.",
 "params_schema":[{"name":"n","kind":"int","default":14,"min":2,"max":100,"label":"Days to average"}],
 "code":"def compute(frame, bench, n=14):\n    r = frame.high - frame.low\n    return 100 * r.rolling(n).mean() / frame.close"}

Example 2: "how much better the stock did than the market over n days"
{"name":"rel_strength","explain":"Whether the stock beat the Nifty 500 over the last few weeks.",
 "params_schema":[{"name":"n","kind":"int","default":63,"min":5,"max":252,"label":"Days to look back"}],
 "code":"def compute(frame, bench, n=63):\n    return 100 * ((frame.close / bench).pct_change(n))"}
"""  # noqa: E501


def build_prompt(payload: dict) -> str:
    return (
        "You write a small custom stock indicator in Python for a retail investor's tool.\n\n"
        "## Code shape\n"
        "Exactly one function: `def compute(frame, bench, **params)` returning a pandas Series with "
        "the same length as `frame`. Nothing else at the top level.\n"
        "`frame` is a DataFrame of daily bars with columns open, high, low, close, volume and a date "
        "index. `bench` is the Nifty 500 close Series on the same index.\n"
        "Only `pd`, `np` and `math` exist. Do not import anything.\n\n"
        "## Allowed attribute names (anything else is rejected)\n"
        f"{' '.join(ci.allowed_vocabulary())}\n\n"
        "## Allowed built-in functions\n"
        f"{' '.join(sorted(ci.SAFE_BUILTINS))}\n"
        "Names and attributes starting with an underscore are never allowed.\n\n"
        "## params_schema\n"
        "A list of parameters, one per keyword argument of compute (each with a default). Each item: "
        '{"name":identifier,"kind":"int" or "float","default":number,"min":number,"max":number,'
        '"label":plain-English label}. Use [] if there are no parameters.\n\n'
        f"## Worked examples\n{EXAMPLES}\n"
        "## Task\n"
        f"Indicator name: {payload.get('name', '')}\n"
        f"What it should compute: {payload.get('description', '')}\n\n"
        'Reply with ONLY a JSON object {"name":snake_case_name,"explain":one plain-English sentence '
        'for a reader who is not a maths person,"params_schema":[...],"code":"..."}. '
        "No other text, no code fences."
    )


def _check(obj: dict | None) -> tuple[dict | None, str]:
    """Return (result, "") if the reply is usable, else (None, problems text). Never runs the code."""
    if obj is None:
        return None, "The reply did not contain a JSON object."
    name, code, explain = obj.get("name"), obj.get("code"), obj.get("explain")
    problems: list[str] = []
    if (bad := ci.validate_name(name)) is not None:
        problems.append(bad)
    if not isinstance(explain, str) or not explain.strip():
        problems.append("`explain` must be one plain-English sentence.")
    schema = obj.get("params_schema", [])
    try:
        ci.validate_params_schema(schema)
    except ValueError as e:
        problems.append(str(e))
    problems.extend(ci.static_check(code))
    if problems:
        return None, "; ".join(problems)
    return {
        "ok": True,
        "name": name,
        "explain": explain.strip(),
        "params_schema": schema,
        "code": code,
        "problems": [],
    }, ""


def _reask(prompt: str, bad: str, problems: str) -> str:
    again = (
        f"{prompt}\n\nYour previous reply was:\n{bad}\n\n"
        f"It was rejected: {problems}\nFix it and reply with ONLY a JSON object."
    )
    model, timeout = db.get_setting("ai_model"), int(db.get_setting("ai_timeout_s"))
    return base.provider().ask(again, model=model, timeout_s=timeout)


def postprocess(response: str, payload: dict) -> dict:
    ok, problems = _check(extract_json(response))
    if ok:
        return ok
    try:
        retry = _reask(build_prompt(payload), response, problems)
    except AIError as e:
        return {"ok": False, "error": f"The indicator was rejected ({problems}) and the retry failed: {e}"}
    ok, problems = _check(extract_json(retry))
    if ok:
        return ok
    return {"ok": False, "error": f"The indicator was rejected: {problems}"}


register_task(
    AITask(
        kind="indicator_code",
        label="Write a custom indicator",
        build_prompt=build_prompt,
        postprocess=postprocess,
        needs_symbol=False,
    )
)
