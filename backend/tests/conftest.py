import importlib
import os
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SHM = Path("/dev/shm")


def pytest_configure(config):
    """Put tmp_path in RAM when possible: SQLite's fsyncs on WSL's virtual disk cost ~10x the test."""
    if config.option.basetemp or not (_SHM.is_dir() and os.access(_SHM, os.W_OK)):
        return
    config._shm_basetemp = tempfile.mkdtemp(prefix="stock-tools-pytest-", dir=_SHM)  # per run: no clashes
    config.option.basetemp = config._shm_basetemp


def pytest_unconfigure(config):
    path = getattr(config, "_shm_basetemp", None)
    if path:
        shutil.rmtree(path, ignore_errors=True)  # RAM-backed: never leave it behind


@pytest.fixture(autouse=True)
def _no_http_waits(monkeypatch):
    """Tests use fake transports, so rate-limit gaps and retry back-off only burn wall time.

    Swaps the `time` module seen by `http` alone (not the global one), so tests that record
    `http.time.sleep` calls still work.
    """
    from app.sources import http

    fake = types.SimpleNamespace(sleep=lambda _s: None, monotonic=time.monotonic)
    monkeypatch.setattr(http, "time", fake)
    yf = sys.modules.get("app.sources.adapters.yfinance")  # own rate limit; patch only if loaded
    if yf is not None:
        monkeypatch.setattr(yf, "time", fake)


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_NO_THREADS", "1")
    import app.config

    importlib.reload(app.config)
    yield
    monkeypatch.undo()
    importlib.reload(app.config)


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c
