"""Turn the owner's words into a screen rule (SPEC §11 `rule_from_text`)."""

from __future__ import annotations

import logging

from app import db
from app.ai import base
from app.ai.base import AIError, AITask, register_task
from app.ai.tasks._json import extract_json
from app.analytics import fundamentals, indicators, rules

log = logging.getLogger(__name__)

EXAMPLES = """\
Example 1: "stocks trading above their 200-day average"
{"name":"Above 200-day average","description":"Price is above its 200-day average.",
 "rule":{"all":[{"left":{"ind":"close"},"op":">","right":{"ind":"sma","params":{"n":200}}}]}}

Example 2: "oversold but profitable with low debt"
{"name":"Oversold quality","description":"Weak short-term price but a healthy business.",
 "rule":{"all":[{"left":{"ind":"rsi","params":{"n":14}},"op":"<","right":{"value":35}},
  {"left":{"fund":"roce_pct"},"op":">=","right":{"value":15}},
  {"left":{"fund":"debt_to_equity"},"op":"<","right":{"value":0.5}}]}}

Example 3: "either a fresh 50-day average cross up, or very strong momentum, but not overheated"
{"name":"Momentum picks","description":"Trend turning up or strong, and not stretched.",
 "rule":{"all":[{"any":[{"left":{"ind":"close"},"op":"crosses_above","right":{"ind":"sma","params":{"n":50}}},
  {"left":{"ind":"return_pct","params":{"n":63}},"op":">","right":{"value":30}}]},
  {"not":{"left":{"ind":"rsi","params":{"n":14}},"op":">","right":{"value":75}}}]}}
"""


def _catalogue_text() -> str:
    lines = []
    for ind in indicators.catalogue():
        if ind["params"]:
            params = ", ".join(
                f"{p['name']} ({p['kind']}, {p['min']:g} to {p['max']:g}, default {p['default']:g})"
                for p in ind["params"]
            )
        else:
            params = "no params"
        lines.append(f"- {ind['name']} [{params}]: {ind['explain_default']}")
    return "\n".join(lines)


def _fields_text() -> str:
    return "\n".join(f"- {f['field']}: {f['explain']}" for f in fundamentals.FIELDS if f["numeric"])


def build_prompt(payload: dict) -> str:
    ops = "\n".join(f'- "{name}": {d.words}' for name, d in rules.OPS.items())
    return (
        "You turn a retail investor's plain-English request into a stock-screen rule in a JSON format.\n\n"
        "## Grammar\n"
        'A rule is a group: {"all":[node,...]} (every node true), {"any":[node,...]} (at least one true) '
        'or {"not": node}. A node is a group or a condition {"left":operand,"op":OP,"right":operand}. '
        f"Groups nest at most {rules.MAX_DEPTH} deep and the whole rule has at most "
        f"{rules.MAX_CONDITIONS} conditions. The top level must be a group.\n"
        'An operand is one of: {"ind":NAME,"params":{...}} (an indicator; optional "offset":N days ago '
        'and "times":multiplier), {"fund":FIELD} (a fundamental number; optional "times"), '
        "or {\"value\":NUMBER}.\n\n"
        f"## Operators (OP)\n{ops}\n\n"
        f"## Indicators\n{_catalogue_text()}\n\n"
        f"## Fundamental fields\n{_fields_text()}\n\n"
        f"## Worked examples\n{EXAMPLES}\n"
        "## Task\n"
        f'The investor wrote: "{str(payload.get("text", "")).strip()}"\n\n'
        'Reply with ONLY a JSON object: {"name":short name,"description":one plain sentence,"rule":{...}}. '
        "Use only the indicators, fields and operators listed above. "
        "If the request needs an indicator that is not listed, reply instead with "
        '{"need_custom_indicator":{"name":snake_case_name,'
        '"description":what it should compute}}. No other text, no code fences.'
    )


def _reask(prompt: str, bad: str, error: str) -> str:
    again = (
        f"{prompt}\n\nYour previous reply was:\n{bad}\n\n"
        f"It was rejected: {error}\nFix it and reply with ONLY a JSON object."
    )
    model, timeout = db.get_setting("ai_model"), int(db.get_setting("ai_timeout_s"))
    return base.provider().ask(again, model=model, timeout_s=timeout)


def _normalise(obj: dict) -> dict:
    """Validate `obj['rule']`; raise rules.RuleError if invalid."""
    rule = obj.get("rule")
    if not isinstance(rule, dict):
        raise rules.RuleError("$: the reply has no 'rule' object")
    rules.validate_rule(rule)
    return {
        "ok": True,
        "rule": rule,
        "name": str(obj.get("name") or "AI screen").strip()[:80],
        "description": str(obj.get("description") or "").strip(),
        "describe": rules.describe(rule),
    }


def _need_custom(obj: dict) -> dict | None:
    need = obj.get("need_custom_indicator")
    if "rule" in obj or not isinstance(need, dict):
        return None
    return {"ok": True, "need_custom_indicator": need}


def postprocess(response: str, payload: dict) -> dict:
    obj = extract_json(response)
    if obj is None:
        return {"ok": False, "error": "Claude's reply did not contain a rule. Try rewording the request."}
    custom = _need_custom(obj)
    if custom:
        return custom
    try:
        return _normalise(obj)
    except rules.RuleError as first:
        error = str(first)
    try:
        retry = extract_json(_reask(build_prompt(payload), response, error))
    except AIError as e:
        return {"ok": False, "error": f"The rule was invalid ({error}) and the retry failed: {e}"}
    if retry is None:
        return {"ok": False, "error": f"The rule was invalid: {error}"}
    custom = _need_custom(retry)
    if custom:
        return custom
    try:
        return _normalise(retry)
    except rules.RuleError as second:
        return {"ok": False, "error": f"The rule was invalid: {second}"}


register_task(
    AITask(
        kind="rule_from_text",
        label="Describe a screen in words",
        build_prompt=build_prompt,
        postprocess=postprocess,
    )
)
