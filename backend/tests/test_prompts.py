from datetime import date

import pandas as pd
import pytest

from app import db, timeutil
from app.ai import base
from app.ai.tasks import _context
from app.analytics import frames
from app.sources import registry
from app.sources.base import Announcement, Bar, BaseSource, CapabilitySpec
from app.sources.store import save_announcements, save_bars

DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-06", periods=300)]


def px_source():
    caps = (CapabilitySpec("bars", "by_symbol", (), adjusted=True),)
    return type("px", (BaseSource,), {"name": "px", "label": "px", "description": "d", "homepage": "h",
                                      "capabilities": caps})()  # fmt: skip


@pytest.fixture
def seeded(client, monkeypatch):
    monkeypatch.setattr(timeutil, "today", lambda: date(2026, 11, 9))
    registry.clear()
    registry.register(px_source())
    bars = [Bar("ABC", d, 100 + i * 0.1, 102 + i * 0.1, 99 + i * 0.1, 100 + i * 0.1, 1000.0)
            for i, d in enumerate(DAYS)]  # fmt: skip
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('ABC','ABC',1)")
        save_bars("px", bars, c)
    frames.invalidate()
    yield "ABC"
    registry.clear()
    frames.invalidate()


def add_announcements(n: int, size: int) -> None:
    items = [
        Announcement("ABC", f"2026-10-{(i % 28) + 1:02d}T10:{i % 60:02d}:00+05:30",
                     f"headline {i} " + "x" * size, category="other")
        for i in range(n)
    ]  # fmt: skip
    with db.tx() as c:
        save_announcements("test", items, c)


def test_every_heading_present(seeded):
    text = _context.stock_context("ABC")
    headings = ("Price", "Fundamentals", "Quarterly results", "Recent announcements", "Recent news")
    for h in headings:
        h = f"## {h}"
        assert h in text
    assert "2026-11-09" in text
    assert "Last close" in text


def test_length_cap(seeded):
    add_announcements(30, size=3000)
    text = _context.stock_context("ABC")
    assert len(text) <= 25_000
    assert "## Recent news" in text
    assert "headline" in text  # newest ones survive


def test_routine_excluded(seeded):
    with db.tx() as c:
        c.execute(
            "INSERT INTO announcements(source,symbol,ts,category,headline) VALUES "
            "('t','ABC','2026-10-01T10:00:00+05:30','routine','trading window closure')"
        )
    assert "trading window closure" not in _context.stock_context("ABC")


def test_challenge_includes_answers(seeded):
    answers = {"thesis": "margins will expand"}
    p = base.task("checklist_challenge").build_prompt({"symbol": "ABC", "answers": answers})
    assert "margins will expand" in p
    assert "exactly 3" in p


def test_tasks_and_prompt_endpoints(client, seeded):
    kinds = {t["kind"]: t for t in client.get("/api/ai/tasks").json()}
    for k in ("stock_brief", "thesis_draft", "checklist_challenge"):
        assert kinds[k]["needs_symbol"] is True
        r = client.get("/api/ai/prompt", params={"kind": k, "symbol": "ABC"})
        assert r.status_code == 200
        body = r.json()["prompt"]
        assert "not financial advice" in body and "## Price" in body
    brief = client.get("/api/ai/prompt", params={"kind": "stock_brief", "symbol": "ABC"}).json()["prompt"]
    assert "250 words" in brief
    thesis = client.get("/api/ai/prompt", params={"kind": "thesis_draft", "symbol": "ABC"}).json()["prompt"]
    assert "300 words" in thesis
