from datetime import datetime, timedelta

import pytest

from app import config, db, timeutil
from app.cloud import dispatch
from app.jobs import runner

T0 = datetime(2026, 11, 24, 10, 0, tzinfo=config.TZ)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init_db()
    import app.jobs.defs.noop  # noqa: F401  (registers noop)

    clock = {"now": T0}
    monkeypatch.setattr(timeutil, "now", lambda: clock["now"])
    monkeypatch.setattr(config, "GITHUB_REPO", "owner/nse-radar")
    monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "tok-secret")
    yield clock
    dispatch.set_transport(None)


@pytest.fixture
def calls():
    sent: list[tuple] = []

    def fake(method, url, headers, body):
        sent.append((method, url, headers, body))
        return 204

    dispatch.set_transport(fake)
    return sent


def test_kick_posts_dispatch(calls):
    assert dispatch.kick("enqueue noop") is True
    [(method, url, headers, body)] = calls
    assert method == "POST"
    assert url == "https://api.github.com/repos/owner/nse-radar/actions/workflows/drain.yml/dispatches"
    assert body == {"ref": "main", "inputs": {"reason": "enqueue noop"}}
    assert headers["Authorization"] == "Bearer tok-secret"
    assert db.get_setting("last_dispatch_at") == T0.isoformat(timespec="seconds")


def test_kick_debounced_within_60s(calls, _setup):
    assert dispatch.kick("a") is True
    _setup["now"] = T0 + timedelta(seconds=59)
    assert dispatch.kick("b") is True
    assert len(calls) == 1
    _setup["now"] = T0 + timedelta(seconds=61)
    assert dispatch.kick("c") is True
    assert len(calls) == 2


def test_kick_not_configured(calls, monkeypatch):
    monkeypatch.delenv("GITHUB_DISPATCH_TOKEN")
    assert dispatch.kick("x") is False
    assert calls == []


def test_kick_failure_returns_false_and_job_stays_queued(monkeypatch, caplog):
    dispatch.set_transport(lambda *a: 401)
    monkeypatch.setattr(config, "RUNTIME", "vercel")
    rid = runner.enqueue("noop")
    with db.read() as c:
        assert c.execute("SELECT status FROM job_runs WHERE id=?", (rid,)).fetchone()["status"] == "queued"
    with pytest.raises(KeyError):
        db.get_setting("last_dispatch_at")  # not recorded, so the next enqueue tries again
    assert "tok-secret" not in caplog.text


def test_kick_network_error_returns_false(caplog):
    def boom(*a):
        raise OSError("tok-secret leaked?")

    dispatch.set_transport(boom)
    assert dispatch.kick("x") is False
    assert "tok-secret" not in caplog.text


def test_keepalive_at_most_weekly(calls, _setup):
    assert dispatch.keepalive() is True
    [(method, url, headers, body)] = calls
    assert method == "PUT"
    assert url == "https://api.github.com/repos/owner/nse-radar/actions/workflows/daily.yml/enable"
    assert body is None
    _setup["now"] = T0 + timedelta(days=6, hours=23)
    assert dispatch.keepalive() is False
    assert len(calls) == 1
    _setup["now"] = T0 + timedelta(days=7, minutes=1)
    assert dispatch.keepalive() is True
    assert len(calls) == 2


def test_enqueue_vercel_kicks_after_commit(calls, monkeypatch):
    monkeypatch.setattr(config, "RUNTIME", "vercel")
    seen: list[str] = []

    def fake(method, url, headers, body):
        with db.read() as c:  # the run must already be committed and visible
            seen.append(c.execute("SELECT status FROM job_runs").fetchone()["status"])
        return 204

    dispatch.set_transport(fake)
    rid = runner.enqueue("noop")
    assert seen == ["queued"]
    assert runner.enqueue("noop") == rid  # existing run: no new insert, no new kick
    assert seen == ["queued"]


def test_enqueue_local_does_not_kick(calls):
    assert config.RUNTIME == "local"
    runner.enqueue("noop")
    assert calls == []


def test_status_shape(client, calls):
    runner.enqueue("noop", params={"a": 1})
    runner.enqueue("noop", params={"a": 2})
    with db.tx() as c:
        c.execute("UPDATE job_runs SET status='running' WHERE id=(SELECT MAX(id) FROM job_runs)")
    body = client.get("/api/cloud/status").json()
    assert body == {
        "runtime": "local",
        "dispatch_configured": True,
        "last_dispatch_at": None,
        "queued": 1,
        "running": 1,
        "oldest_queued_at": T0.isoformat(timespec="seconds"),
    }
    assert [c[0] for c in calls] == ["PUT"]  # keepalive ran once
    client.get("/api/cloud/status")
    assert len(calls) == 1


def test_status_empty_not_configured(client, calls, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_REPO", "")
    body = client.get("/api/cloud/status").json()
    assert body["dispatch_configured"] is False
    assert (body["queued"], body["running"], body["oldest_queued_at"]) == (0, 0, None)
    assert calls == []
