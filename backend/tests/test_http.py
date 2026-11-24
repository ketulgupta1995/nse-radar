import pytest

from app import config
from app.sources import http


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    http._last_request.clear()
    yield sleeps
    http.set_transport(None)
    http._last_request.clear()


def fake(responses, calls=None):
    it = iter(responses)

    def fn(url, params, headers):
        if calls is not None:
            calls.append((url, headers))
        return next(it)

    http.set_transport(fn)


def test_same_host_waits_other_host_does_not(_clean):
    fake([(200, b"a")] * 3)
    http.get("https://a.example/1")
    http.get("https://b.example/1")
    assert _clean == []
    http.get("https://a.example/2")
    assert len(_clean) == 1 and 0 < _clean[0] <= 1.0


def test_retries_503_then_ok(_clean):
    calls = []
    fake([(503, b""), (503, b""), (200, b"ok")], calls)
    assert http.get("https://a.example/x") == b"ok"
    assert len(calls) == 3
    assert 2 in _clean and 4 in _clean


def test_403_no_retry():
    calls = []
    fake([(403, b"")], calls)
    with pytest.raises(http.FetchError) as e:
        http.get("https://a.example/x")
    assert e.value.status == 403 and len(calls) == 1


def test_404_no_retry_and_exhausted_retries():
    calls = []
    fake([(404, b"")], calls)
    with pytest.raises(http.FetchError) as e:
        http.get("https://a.example/x")
    assert e.value.status == 404 and len(calls) == 1
    calls.clear()
    fake([(500, b"")] * 3, calls)
    with pytest.raises(http.FetchError) as e:
        http.get("https://a.example/x")
    assert e.value.status == 500 and len(calls) == 3


def test_get_json():
    fake([(200, b'{"a": 1}'), (200, b"nope")])
    assert http.get_json("https://a.example/j") == {"a": 1}
    with pytest.raises(http.FetchError) as e:
        http.get_json("https://a.example/j2")
    assert e.value.status is None


def test_user_agent():
    calls = []
    fake([(200, b"")], calls)
    http.get("https://a.example/x")
    assert calls[0][1]["User-Agent"] == config.USER_AGENT


def test_add_policy():
    http.add_policy("c.example", http.HttpPolicy(5.0, 10, 0))
    assert http.POLICIES["c.example"].min_interval_s == 5.0
    http.POLICIES.pop("c.example")
