import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from app import db
from app.ai import base
from app.ai.providers import claude_cli
from app.jobs import runner
from app.jobs.context import StopRequested

FAKE = Path(__file__).parent / "fixtures" / "fake_claude.py"


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """Put a `claude` on PATH that runs fake_claude.py."""
    d = tmp_path / "bin"
    d.mkdir()
    script = d / "claude"
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("FAKE_CLAUDE_MODE", raising=False)
    prov = base.provider("claude_cli")
    prov._cache = None
    yield prov
    prov._cache = None


def ask(prov, stop_check=None, timeout_s=20):
    return prov.ask("hello world, this is long", model="sonnet", timeout_s=timeout_s, stop_check=stop_check)


def test_ask_returns_result(fake_claude):
    assert ask(fake_claude) == "echo: hello world, this is"


def test_available_and_cached(fake_claude, monkeypatch):
    ok, detail = fake_claude.available()
    assert ok and "9.9.9" in detail
    monkeypatch.setenv("PATH", "/nonexistent")
    assert fake_claude.available()[0] is True  # cached for 60 s
    fake_claude._cache = None
    ok, detail = fake_claude.available()
    assert not ok and "not found" in detail


def test_fail_gives_stderr_tail(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    with pytest.raises(base.AIError, match="boom: fake failure"):
        ask(fake_claude)


def test_timeout(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    with pytest.raises(base.AIError, match="longer than"):
        ask(fake_claude, timeout_s=1)


def test_stop_kills_process(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    t0 = time.monotonic()
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(StopRequested):
        ask(fake_claude, stop_check=stop)
    assert time.monotonic() - t0 < 10


def test_api_key_not_passed_to_child(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "env")
    for k in claude_cli.STRIPPED_ENV:
        monkeypatch.setenv(k, "secret")
    env = json.loads(ask(fake_claude))
    assert all(k not in env for k in claude_cli.STRIPPED_ENV)
    assert env["FAKE_CLAUDE_MODE"] == "env"


def make_request(client, **body):
    r = client.post("/api/ai/requests", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_job_flow_updates_row(client, fake_claude):
    ids = make_request(client, kind="raw", payload={"prompt": "ping pong ping pong ping"})
    got = client.get(f"/api/ai/requests/{ids['id']}").json()
    assert got["status"] == "queued" and got["provider"] == "claude_cli" and got["model"] == "sonnet"
    assert runner.run_one("interactive") == ids["run_id"]
    got = client.get(f"/api/ai/requests/{ids['id']}").json()
    assert got["status"] == "done"
    assert got["response"] == "echo: ping pong ping pong "
    assert got["duration_s"] is not None and got["error"] is None
    assert client.get("/api/ai/requests?kind=raw").json()[0]["id"] == ids["id"]


def test_job_flow_failure(client, fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    ids = make_request(client, kind="raw", payload={"prompt": "x"})
    runner.run_one("interactive")
    got = client.get(f"/api/ai/requests/{ids['id']}").json()
    assert got["status"] == "failed" and "boom" in got["error"]


def test_job_stop_while_running(client, fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    ids = make_request(client, kind="raw", payload={"prompt": "x"})
    runner.request_stop(ids["run_id"])  # queued -> cancelled at once
    got = client.get(f"/api/ai/requests/{ids['id']}").json()
    assert got["status"] == "cancelled"


def test_status_and_tasks(client, fake_claude):
    s = client.get("/api/ai/status").json()
    assert s["provider"] == "claude_cli" and s["available"] and s["model"] == "sonnet"
    assert {"name": "claude_cli", "label": claude_cli.ClaudeCli.label} in s["providers"]
    assert {"kind": "raw", "label": "Raw prompt", "needs_symbol": False} in client.get("/api/ai/tasks").json()


def test_unknown_provider_status(client):
    db.set_setting("ai_provider", "nope")
    s = client.get("/api/ai/status").json()
    assert s["available"] is False and "unknown provider" in s["detail"]
    assert client.post("/api/ai/requests", json={"kind": "raw"}).status_code == 400


def test_prompt_endpoints(client):
    assert client.get("/api/ai/prompt?kind=raw").json() == {"prompt": ""}
    r = client.post("/api/ai/prompt", json={"kind": "raw", "payload": {"prompt": "hi"}})
    assert r.json() == {"prompt": "hi"}
    assert client.get("/api/ai/prompt?kind=missing").status_code == 404


class FakeProvider(base.AIProvider):
    name = "fake2"
    label = "Second fake"

    def available(self):
        return True, "v2"

    def ask(self, prompt, *, model, timeout_s, stop_check=None):
        return f"second:{model}:{prompt}"


def test_second_provider_selectable(client):
    base.register_provider(FakeProvider())
    db.set_setting("ai_provider", "fake2")
    assert client.get("/api/ai/status").json()["detail"] == "v2"
    ids = make_request(client, kind="raw", payload={"prompt": "yo"})
    runner.run_one("interactive")
    got = client.get(f"/api/ai/requests/{ids['id']}").json()
    assert got["provider"] == "fake2" and got["response"] == "second:sonnet:yo"


def test_postprocess_error_fails_request(client):
    def boom(resp, payload):
        raise base.AIError("bad answer")

    base.register_task(base.AITask("t044_post", "Post", lambda p: "q", postprocess=boom))
    base.register_provider(FakeProvider())
    db.set_setting("ai_provider", "fake2")
    ids = make_request(client, kind="t044_post")
    runner.run_one("interactive")
    got = client.get(f"/api/ai/requests/{ids['id']}").json()
    assert got["status"] == "failed" and got["error"] == "bad answer"
