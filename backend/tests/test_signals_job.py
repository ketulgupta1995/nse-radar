from test_signals_outcome import DAYS, add_signal, world  # noqa: F401

from app import db
from app.analytics import score
from app.jobs import registry, runner
from app.jobs.defs import alerts_scan, screens_run, signals_track  # noqa: F401
from app.signals import log as signal_log


def item_status() -> dict[str, str]:
    with db.tx() as c:
        return {r["key"]: r["status"] for r in c.execute("SELECT key, status FROM job_items")}


def runs() -> list:
    with db.tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM job_runs ORDER BY id")]


def test_job_logs_and_updates_outcomes(world, monkeypatch):  # noqa: F811
    add_signal(DAYS[-3])
    monkeypatch.setattr(score, "score_candidates", lambda *a, **k: [])
    runner.enqueue("signals_track")
    runner.run_one()
    row = runs()[0]
    assert row["status"] == "done"
    assert row["message"] == "logged 0 new (0 screen, 0 shortlist); open 1, closed 0"
    assert item_status() == {"log": "ok", "outcomes": "ok"}
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0] == 1


def test_chain_screens_signals_alerts(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(score, "score_candidates", lambda *a, **k: [])
    assert registry.get("screens_run").followups == ("signals_track",)
    assert registry.get("signals_track").followups == ("alerts_scan",)
    runner.enqueue("screens_run")
    runner.run_one()
    runner.run_one()
    names = [r["job"] for r in runs()]
    assert names[:2] == ["screens_run", "signals_track"]
    assert "alerts_scan" in names


def test_logging_failure_still_runs_outcomes(world, monkeypatch):  # noqa: F811
    add_signal(DAYS[-3])

    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(signal_log, "log_signals", boom)
    monkeypatch.setattr(score, "score_candidates", lambda *a, **k: [])
    runner.enqueue("signals_track")
    runner.run_one()
    assert item_status() == {"log": "failed", "outcomes": "ok"}
    assert runs()[0]["message"].endswith("open 1, closed 0")
