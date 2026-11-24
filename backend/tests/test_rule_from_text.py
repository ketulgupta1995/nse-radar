import json

import pytest

from app import db
from app.ai import base
from app.ai.tasks import rule_from_text as t

GOOD = {
    "name": "Near highs",
    "description": "Close to the 52-week high.",
    "rule": {
        "all": [{"left": {"ind": "pct_from_high", "params": {"n": 252}}, "op": ">", "right": {"value": -5}}]
    },
}
BAD = {"name": "x", "rule": {"all": [{"left": {"ind": "nope"}, "op": ">", "right": {"value": 1}}]}}


class FakeProv(base.AIProvider):
    name = "fake"

    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def available(self):
        return True, ""

    def ask(self, prompt, *, model, timeout_s, stop_check=None):
        self.prompts.append(prompt)
        return self.replies.pop(0)


@pytest.fixture
def prov(monkeypatch):
    db.init_db()
    def make(replies):
        p = FakeProv(replies)
        monkeypatch.setattr(base, "provider", lambda name=None: p)
        return p

    return make


def test_prompt_contents():
    p = t.build_prompt({"text": "cheap stocks"})
    assert "cheap stocks" in p and "crosses_above" in p and "ONLY a JSON object" in p
    assert "rsi" in p and "debt_to_equity" in p and "Example 3" in p


def test_valid_rule(prov):
    prov([])
    r = t.postprocess("Sure!\n```json\n" + json.dumps(GOOD) + "\n```", {"text": "x"})
    assert r["ok"] and r["rule"] == GOOD["rule"] and r["name"] == "Near highs"
    assert r["describe"]


def test_invalid_then_valid(prov):
    p = prov([json.dumps(GOOD)])
    r = t.postprocess(json.dumps(BAD), {"text": "x"})
    assert r["ok"] and r["rule"] == GOOD["rule"]
    assert len(p.prompts) == 1 and "rejected" in p.prompts[0] and "nope" in p.prompts[0]


def test_invalid_twice(prov):
    prov([json.dumps(BAD)])
    r = t.postprocess(json.dumps(BAD), {"text": "x"})
    assert r["ok"] is False and "invalid" in r["error"]


def test_junk(prov):
    prov([])
    r = t.postprocess("I cannot help with that", {"text": "x"})
    assert r["ok"] is False and r["error"]


def test_need_custom_indicator(prov):
    prov([])
    need = {"name": "supertrend", "description": "Supertrend line"}
    r = t.postprocess(json.dumps({"need_custom_indicator": need}), {"text": "x"})
    assert r == {"ok": True, "need_custom_indicator": need}
