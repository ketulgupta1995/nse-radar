"""The Vercel entry point (`api/index.py`) in vercel mode: light start, no threads (SPEC §17.2, §17.5)."""

import importlib
import importlib.util
import sys
import threading

from fastapi.testclient import TestClient

from app import config

_INDEX = config.ROOT / "api" / "index.py"


def _load_entry(monkeypatch):
    """Import api/index.py freshly with STOCK_RUNTIME=vercel; restore the local app.main afterwards."""
    import app
    import app.main  # the local-mode app, put back by monkeypatch's undo

    monkeypatch.setattr(app, "main", app.main)
    monkeypatch.delitem(sys.modules, "app.main")
    monkeypatch.setenv("STOCK_RUNTIME", "vercel")
    importlib.reload(config)
    spec = importlib.util.spec_from_file_location("nse_radar_vercel_entry", _INDEX)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vercel_entry_is_light(monkeypatch):
    from app import db
    from app.analytics import custom_indicators
    from app.jobs import runner, scheduler

    db.init_db()  # the DB was set up beforehand (by the drain, in the cloud)
    called: list[str] = []
    monkeypatch.setattr(db, "init_db", lambda: called.append("init_db"))
    monkeypatch.setattr(runner, "start_worker", lambda *a, **k: called.append("worker"))
    monkeypatch.setattr(runner, "recover_on_startup", lambda *a, **k: called.append("recover"))
    monkeypatch.setattr(scheduler, "startup", lambda *a, **k: called.append("scheduler"))
    monkeypatch.setattr(custom_indicators, "load_approved", lambda: called.append("custom") or 0)
    threads_before = {t.name for t in threading.enumerate()}

    entry = _load_entry(monkeypatch)
    assert config.RUNTIME == "vercel"
    with TestClient(entry.app) as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        assert r.json()["runtime"] == "vercel"
        assert r.json()["schema"] == "ok"
        assert c.get("/some/page").status_code == 404  # no SPA fallback: Vercel serves the build
        assert c.get("/api/nope").status_code == 404

        new = {t.name for t in threading.enumerate()} - threads_before
        assert not [n for n in new if n == "scheduler" or n.startswith("job-worker")]

    assert called == []
    assert not any(getattr(r, "path", None) == "/assets" for r in entry.app.routes)


def test_local_app_still_has_spa(client):
    assert client.get("/some/page").status_code == 200
