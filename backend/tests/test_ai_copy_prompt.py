"""SPEC §17.7: the copy_prompt provider and the pasted-answer endpoint (N010)."""

import json

import pytest

from app import db
from app.ai import base
from app.ai.providers import copy_prompt

GOOD = {
    "name": "Near highs",
    "description": "Close to the 52-week high.",
    "rule": {
        "all": [{"left": {"ind": "pct_from_high", "params": {"n": 252}}, "op": ">", "right": {"value": -5}}]
    },
}
BAD = {"name": "x", "rule": {"all": [{"left": {"ind": "nope"}, "op": ">", "right": {"value": 1}}]}}


@pytest.fixture
def cp(client):
    db.set_setting("ai_provider", "copy_prompt")
    return client


def job_count() -> int:
    with db.tx() as c:
        return c.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0]


def create(client, **body) -> dict:
    r = client.post("/api/ai/requests", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_provider_available_and_never_asks():
    p = base.provider("copy_prompt")
    assert p.available() == (True, "copy the prompt into Claude, then paste the answer back")
    with pytest.raises(base.AIError, match="paste the answer"):
        p.ask("x", model="sonnet", timeout_s=1)
    assert isinstance(p, copy_prompt.CopyPrompt)


def test_status_lists_copy_prompt(cp):
    s = cp.get("/api/ai/status").json()
    assert s["provider"] == "copy_prompt" and s["available"] is True
    assert "copy_prompt" in {p["name"] for p in s["providers"]}


def test_create_waits_for_answer_without_job(cp):
    before = job_count()
    ids = create(cp, kind="raw", payload={"prompt": "hello there"})
    assert ids["run_id"] is None and ids["status"] == "awaiting_answer"
    assert ids["prompt"] == "hello there"
    assert job_count() == before
    got = cp.get(f"/api/ai/requests/{ids['id']}").json()
    assert got["status"] == "awaiting_answer" and got["provider"] == "copy_prompt"
    assert cp.get("/api/ai/requests?kind=raw").json()[0]["status"] == "awaiting_answer"


def test_answer_plain_task(cp):
    ids = create(cp, kind="raw", payload={"prompt": "hi"})
    r = cp.post(f"/api/ai/requests/{ids['id']}/answer", json={"text": "  Hello **owner**  "})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["status"] == "done" and got["response"] == "Hello **owner**"
    assert got["result"] is None and got["error"] is None
    assert cp.get(f"/api/ai/requests/{ids['id']}").json()["status"] == "done"
    assert job_count() == 0


def test_answer_json_task_parsed_like_provider(cp):
    ids = create(cp, kind="rule_from_text", payload={"text": "near highs"})
    text = "Here you go:\n```json\n" + json.dumps(GOOD) + "\n```"
    got = cp.post(f"/api/ai/requests/{ids['id']}/answer", json={"text": text}).json()
    assert got["status"] == "done"
    assert got["result"]["ok"] is True and got["result"]["rule"] == GOOD["rule"]
    assert got["result"]["name"] == "Near highs"


def test_answer_json_task_invalid_rule_is_a_result_not_a_retry(cp):
    ids = create(cp, kind="rule_from_text", payload={"text": "near highs"})
    got = cp.post(f"/api/ai/requests/{ids['id']}/answer", json={"text": json.dumps(BAD)}).json()
    assert got["status"] == "done" and got["result"]["ok"] is False
    assert "paste the answer" in got["result"]["error"]
    # A corrected answer may be pasted over the old one.
    got = cp.post(f"/api/ai/requests/{ids['id']}/answer", json={"text": json.dumps(GOOD)}).json()
    assert got["result"]["ok"] is True


def test_postprocess_error_marks_failed(cp):
    def boom(resp, payload):
        raise base.AIError("bad answer")

    base.register_task(base.AITask("n010_post", "Post", lambda p: "q", postprocess=boom))
    ids = create(cp, kind="n010_post")
    got = cp.post(f"/api/ai/requests/{ids['id']}/answer", json={"text": "x"}).json()
    assert got["status"] == "failed" and got["error"] == "bad answer"


def test_answer_rejects_bad_requests(cp):
    assert cp.post("/api/ai/requests/999/answer", json={"text": "x"}).status_code == 404
    ids = create(cp, kind="raw", payload={"prompt": "hi"})
    assert cp.post(f"/api/ai/requests/{ids['id']}/answer", json={"text": "   "}).status_code == 400


def test_answer_refuses_job_run_request(client):
    class Fake(base.AIProvider):
        name = "n010_fake"

        def available(self):
            return True, ""

        def ask(self, prompt, *, model, timeout_s, stop_check=None):
            return "x"

    base.register_provider(Fake())
    db.set_setting("ai_provider", "n010_fake")
    ids = create(client, kind="raw", payload={"prompt": "hi"})
    assert ids["run_id"] is not None
    assert client.post(f"/api/ai/requests/{ids['id']}/answer", json={"text": "x"}).status_code == 409
