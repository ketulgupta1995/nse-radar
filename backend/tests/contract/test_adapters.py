"""Contract tests every data source must pass (SPEC §3.7). See docs/ADDING_A_SOURCE.md."""

import dataclasses
import importlib.util
import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest

from app.plugins import import_all
from app.sources import http, registry, store
from app.sources.base import (
    Action,
    Announcement,
    Bar,
    BaseSource,
    Event,
    FundSnapshot,
    IndexBar,
    NewsItem,
    NotFound,
    Quarter,
    SourceError,
    SourceRefused,
    SymbolChange,
    SymbolRow,
)

from .example_source import SOURCE as EXAMPLE

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sources"

import_all("app.sources.adapters")
SOURCES: dict[str, BaseSource] = {s.name: s for s in registry.all_sources()}
SOURCES[EXAMPLE.name] = EXAMPLE
EXCEPTIONS = {"NotFound": NotFound, "SourceError": SourceError, "SourceRefused": SourceRefused}
RECORD_TYPES = {
    "universe": SymbolRow, "bars": Bar, "actions": Action, "index": IndexBar,
    "quarters": Quarter, "announcements": Announcement, "news": NewsItem,
    "symbol_changes": SymbolChange, "events": Event,
}  # fmt: skip


def cases_path(name: str) -> Path:
    return FIXTURES / name / "cases.json"


def load_cases(name: str) -> dict:
    return json.loads(cases_path(name).read_text())


def _case_params() -> list:
    out = []
    for name in sorted(SOURCES):
        if cases_path(name).exists():
            for i, c in enumerate(load_cases(name)["cases"]):
                out.append(pytest.param(name, c, id=f"{name}:{c['capability']}:{i}"))
    return out


# ---- transport map ----


def make_transport(mapping: dict, base: Path, *, refuse: bool = False):
    """Exact URL first, then the longest matching prefix; anything unmapped -> 404."""

    def serve(url: str, params: dict | None, headers: dict) -> tuple[int, bytes]:
        if refuse:
            return 403, b""
        candidates = [url + "?" + urlencode(params), url] if params else [url]
        entry = next((mapping[c] for c in candidates if c in mapping), None)
        if entry is None:
            prefixes = [k for k in mapping if any(c.startswith(k) for c in candidates)]
            if prefixes:
                entry = mapping[max(prefixes, key=len)]
        if entry is None:
            return 404, b""
        if "file" in entry:
            return entry.get("status", 200), (base / entry["file"]).read_bytes()
        return entry.get("status", 200), entry.get("body", "").encode()

    return serve


def _fake_module(name: str):
    path = FIXTURES / name / "fake.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"fake_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def install(monkeypatch, name: str, *, refuse: bool = False) -> bool:
    """Make the source's network access come from fixtures. False if it can't be done."""
    base = FIXTURES / name
    fake = _fake_module(name)
    if fake is not None:
        if refuse:
            if not hasattr(fake, "install_refusal"):
                return False
            fake.install_refusal(monkeypatch, base)
        else:
            fake.install(monkeypatch, base)
        return True
    mapping = load_cases(name).get("transport", {})
    monkeypatch.setattr(http, "_transport", make_transport(mapping, base, refuse=refuse))
    return True


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)  # rate limits and back-off cost no time
    saved = dict(registry._sources)
    for s in SOURCES.values():
        if s.name not in registry._sources:
            registry.register(s)
    yield
    http.set_transport(None)
    registry._sources.clear()
    registry._sources.update(saved)


# ---- running a case ----


def call(src: BaseSource, capability: str, args: dict):
    a = dict(args)
    for k in ("d", "start", "end", "since"):
        if k in a:
            a[k] = date.fromisoformat(a[k])
    if "known" in a:
        a["known"] = set(a["known"])
    if capability == "universe":
        return src.universe()
    if capability == "bars":
        if "d" in a:
            return src.bars_for_date(a["d"])
        return src.bars_for_symbol(a["symbol"], a["start"], a["end"])
    if capability == "actions":
        return src.actions(a["symbol"])
    if capability == "index":
        return src.index_bars(a.get("index_name", "NIFTY 500"), a["start"])
    if capability == "fundamentals":
        return src.fundamentals(a["symbol"])
    if capability == "quarters":
        return src.quarters(a["symbol"], a.get("known", set()))
    if capability == "announcements":
        return src.announcements(a["symbol"], a["since"])
    if capability == "news":
        return src.news()
    if capability == "symbol_changes":
        return src.symbol_changes()
    if capability == "events":
        return src.events()
    raise AssertionError(f"unknown capability in cases.json: {capability}")


# ---- generic assertions ----


def finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def is_iso_date(s) -> bool:
    return isinstance(s, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s)) and bool(date.fromisoformat(s))


def has_offset(s) -> bool:
    return isinstance(s, str) and datetime.fromisoformat(s).tzinfo is not None


def check_record(r) -> None:
    json.dumps(dataclasses.asdict(r))  # JSON-serialisable
    if isinstance(r, SymbolRow):
        assert r.symbol == r.symbol.upper() and r.symbol and r.name
    elif isinstance(r, Bar):
        assert r.symbol == r.symbol.upper() and is_iso_date(r.date), r
        assert all(finite(x) for x in (r.open, r.high, r.low, r.close)), r
        assert r.low <= min(r.open, r.close) and max(r.open, r.close) <= r.high, r
        assert r.volume is None or (finite(r.volume) and r.volume >= 0), r
    elif isinstance(r, Action):
        assert r.symbol == r.symbol.upper() and is_iso_date(r.ex_date), r
        assert r.kind in ("split", "bonus", "other", "unparsed"), r
        if r.kind in ("split", "bonus"):
            assert r.factor is not None and finite(r.factor) and 0 < r.factor <= 1, r
    elif isinstance(r, SymbolChange):
        assert r.old_symbol and r.new_symbol and is_iso_date(r.effective_date), r
    elif isinstance(r, Event):
        assert r.symbol == r.symbol.upper() and r.purpose and is_iso_date(r.date), r
    elif isinstance(r, IndexBar):
        assert is_iso_date(r.date) and finite(r.close) and r.close > 0, r
    elif isinstance(r, Quarter):
        assert r.symbol == r.symbol.upper() and is_iso_date(r.period_end), r
        for v in (r.revenue, r.other_income, r.total_expenses, r.pbt, r.net_profit, r.eps):
            assert v is None or finite(v), r
    elif isinstance(r, Announcement):
        assert r.symbol == r.symbol.upper() and has_offset(r.ts) and r.headline, r
    elif isinstance(r, NewsItem):
        assert has_offset(r.ts) and r.title and r.url, r
    elif isinstance(r, FundSnapshot):
        assert r.symbol == r.symbol.upper(), r
        extra = set(r.fields) - store.FUND_FIELD_NAMES
        assert not extra, f"unknown fundamentals fields: {sorted(extra)}"
        assert all(v is None or isinstance(v, str) or finite(v) for v in r.fields.values()), r
    else:
        raise AssertionError(f"adapters may only return normalized records, got {type(r).__name__}")


# ---- tests ----


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_has_cases_file(name):
    assert cases_path(name).exists(), (
        f"add tests/fixtures/sources/{name}/cases.json (see docs/ADDING_A_SOURCE.md)"
    )


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_declaration(name):
    src = SOURCES[name]
    assert re.fullmatch(r"[a-z][a-z0-9_]{1,30}", src.name)
    assert src.label and src.description and src.homepage
    assert src.capabilities, "declare at least one CapabilitySpec"
    seen = set()
    for cs in src.capabilities:
        assert cs.capability not in seen, f"capability {cs.capability} declared twice"
        seen.add(cs.capability)
        if cs.capability == "bars":
            assert cs.adjusted is not None, "bars must say whether prices are already adjusted"
        if cs.mode == "by_date":
            assert cs.history_start and is_iso_date(cs.history_start)
        assert cs.jobs, f"{cs.capability} needs at least one JobVariant"
        for v in cs.jobs:
            assert v.schedule.get("kind") in ("interval", "daily", "weekly", "manual")


@pytest.mark.parametrize(("name", "case"), _case_params())
def test_case(monkeypatch, name, case):
    src = SOURCES[name]
    assert install(monkeypatch, name)
    expect = case.get("expect", {})
    if "raises" in expect:
        with pytest.raises(EXCEPTIONS[expect["raises"]]):
            call(src, case["capability"], case["args"])
        return
    result = call(src, case["capability"], case["args"])
    records = [result] if isinstance(result, FundSnapshot) else result
    assert isinstance(records, list)
    assert len(records) >= expect.get("min_rows", 1)
    cap = case["capability"]
    for r in records:
        if cap != "fundamentals":
            assert isinstance(r, RECORD_TYPES[cap]), f"{cap} must return {RECORD_TYPES[cap].__name__}"
        check_record(r)
    wanted = set(expect.get("symbols", []))
    if wanted:
        assert wanted <= {getattr(r, "symbol", None) for r in records}


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_every_capability_has_a_case(name):
    if not cases_path(name).exists():
        pytest.skip("missing cases.json is reported by test_has_cases_file")
    covered = {c["capability"] for c in load_cases(name)["cases"] if "raises" not in c.get("expect", {})}
    missing = {cs.capability for cs in SOURCES[name].capabilities} - covered
    assert not missing, f"cases.json needs a passing case for: {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_refusal_raises_source_refused(monkeypatch, name):
    if not cases_path(name).exists():
        pytest.skip("missing cases.json is reported by test_has_cases_file")
    refusal = load_cases(name).get("refusal")
    fake = _fake_module(name)
    if fake is not None and not hasattr(fake, "install_refusal"):
        pytest.skip("fake adapter without install_refusal()")
    assert refusal, f"add a 'refusal' entry to tests/fixtures/sources/{name}/cases.json"
    assert install(monkeypatch, name, refuse=True)
    with pytest.raises(SourceRefused):
        call(SOURCES[name], refusal["capability"], refusal["args"])
