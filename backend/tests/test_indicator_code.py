import json

import pytest

from app import db
from app.ai import base
from app.ai.tasks import indicator_code as t

GOOD = {
    "name": "avg_close",
    "explain": "The average closing price over the last few days.",
    "params_schema": [{"name": "n", "kind": "int", "default": 20, "min": 2, "max": 100, "label": "Days"}],
    "code": "def compute(frame, bench, n=20):\n    return frame.close.rolling(n).mean()\n",
}
BLOCKED = {**GOOD, "code": "def compute(frame, bench, n=20):\n    return np.f2py\n"}
PAYLOAD = {"name": "avg_close", "description": "average close"}


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
    p = t.build_prompt(PAYLOAD)
    assert "def compute(frame, bench, **params)" in p and "pct_change" in p and "isinstance" in p
    assert "Nifty 500" in p and "params_schema" in p and "ONLY a JSON object" in p


def test_valid(prov):
    prov([])
    r = t.postprocess("Here:\n" + json.dumps(GOOD), PAYLOAD)
    assert r["ok"] and r["problems"] == [] and r["code"] == GOOD["code"] and r["name"] == "avg_close"


def test_blocked_then_valid(prov):
    p = prov([json.dumps(GOOD)])
    r = t.postprocess(json.dumps(BLOCKED), PAYLOAD)
    assert r["ok"] and r["code"] == GOOD["code"]
    assert len(p.prompts) == 1 and "rejected" in p.prompts[0] and "f2py" in p.prompts[0]


def test_junk(prov):
    prov(["still nothing"])
    r = t.postprocess("no json here", PAYLOAD)
    assert r["ok"] is False and r["error"]


def test_builtin_name_rejected(prov):
    prov([json.dumps({**GOOD, "name": "rsi"})])
    r = t.postprocess(json.dumps({**GOOD, "name": "rsi"}), PAYLOAD)
    assert r["ok"] is False and "built-in" in r["error"]


def test_never_executes(prov):
    prov([])
    code = "def compute(frame, bench):\n    return frame.close.iloc[10**9] + undefined_name\n"
    r = t.postprocess(json.dumps({**GOOD, "code": code, "params_schema": []}), PAYLOAD)
    assert r["ok"]


def test_task_listed(client):
    kinds = [x["kind"] for x in client.get("/api/ai/tasks").json()]
    assert "indicator_code" in kinds
