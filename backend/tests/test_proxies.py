"""Proxy list parsing, rotation, and Trendlyne falling back to the next proxy. No network."""

from pathlib import Path

import pytest

from app.sources import http, proxies
from app.sources.adapters import trendlyne
from app.sources.base import SourceError, SourceRefused
from app.sources.http import FetchError

PAGE = (Path(__file__).parent / "fixtures" / "sources" / "trendlyne" / "list.html").read_bytes()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    proxies._cache = None
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    yield
    proxies._cache = None
    http.set_transport(None)


def test_parse_list_keeps_only_ip_port_lines() -> None:
    text = "1.2.3.4:8080\n\nnot a proxy\n5.6.7.8:3128\n999.1.1.1:80 extra\n"
    assert proxies.parse_list(text) == ["1.2.3.4:8080", "5.6.7.8:3128"]


def test_candidates_keep_only_proxies_that_pass_the_probe(monkeypatch) -> None:
    monkeypatch.setattr(proxies, "_fetch_lists", lambda: ["1.1.1.1:80", "2.2.2.2:80", "3.3.3.3:80"])
    monkeypatch.setattr(proxies, "_alive", lambda p: not p.startswith("http://2."))
    assert sorted(proxies.candidates()) == ["http://1.1.1.1:80", "http://3.3.3.3:80"]


def test_candidates_stop_once_enough_work(monkeypatch) -> None:
    monkeypatch.setattr(proxies, "_fetch_lists", lambda: [f"1.1.1.{i}:80" for i in range(1, 101)])
    monkeypatch.setattr(proxies, "_alive", lambda p: True)
    assert len(proxies.candidates(want=5)) >= 5


def test_alive_is_false_on_fetch_error_and_uses_the_proxy(monkeypatch) -> None:
    seen = []

    def fake_get(url, *, params=None, headers=None, accept="*/*", proxy=None, policy=None):
        seen.append((url, proxy, policy))
        raise FetchError("boom", url=url)

    monkeypatch.setattr(http, "get", fake_get)
    assert proxies._alive("http://9.9.9.9:1") is False
    assert seen == [(proxies.PROBE_URL, "http://9.9.9.9:1", proxies.PROBE_POLICY)]


def test_empty_list_gives_no_candidates(monkeypatch) -> None:
    monkeypatch.setattr(proxies, "_fetch_lists", lambda: [])
    assert proxies.candidates() == []


def test_rotation_is_sticky_then_advances_and_stops_at_limit() -> None:
    pool = proxies.Rotation(["http://a:1", "http://b:2", "http://c:3"], limit=2)
    assert pool.current == "http://a:1"
    assert pool.advance() is True
    assert pool.current == "http://b:2"
    assert pool.advance() is False  # limit of 2 reached


def test_trendlyne_moves_to_next_proxy_when_one_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(proxies, "candidates", lambda: ["http://bad:1", "http://good:2"])
    used: list[str | None] = []

    def fake_get(url, *, params=None, headers=None, accept="*/*", proxy=None, policy=None):
        used.append(proxy)
        if proxy == "http://bad:1":
            raise FetchError("HTTP 405", status=405, url=url)
        return PAGE

    monkeypatch.setattr(http, "get", fake_get)
    reports = trendlyne.Trendlyne().research()
    assert reports  # got rows from the good proxy
    assert used[0] == "http://bad:1" and used[1] == "http://good:2"
    assert all(p == "http://good:2" for p in used[1:])  # sticks with the working one


def test_all_proxies_refused_is_a_retryable_error_not_a_pause(monkeypatch) -> None:
    monkeypatch.setattr(proxies, "candidates", lambda: ["http://a:1", "http://b:2"])

    def refuse(url, *, params=None, headers=None, accept="*/*", proxy=None, policy=None):
        raise FetchError("HTTP 405", status=405, url=url)

    monkeypatch.setattr(http, "get", refuse)
    with pytest.raises(SourceError) as e:
        trendlyne.Trendlyne().research()
    assert not isinstance(e.value, SourceRefused)


def test_direct_refusal_still_pauses_the_source(monkeypatch) -> None:
    monkeypatch.setattr(proxies, "candidates", lambda: [])  # no proxies: direct request

    def refuse(url, *, params=None, headers=None, accept="*/*", proxy=None, policy=None):
        assert proxy is None
        raise FetchError("HTTP 405", status=405, url=url)

    monkeypatch.setattr(http, "get", refuse)
    with pytest.raises(SourceRefused):
        trendlyne.Trendlyne().research()
