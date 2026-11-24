import pytest

from app import db
from app.sources import http, registry
from app.sources.base import (
    BaseSource,
    CapabilitySpec,
    FetchError,
    NotFound,
    SourceError,
    SourceRefused,
    from_fetch_error,
)
from app.sources.http import HttpPolicy


class _Fake(BaseSource):
    label = "Fake"
    description = "fake"
    homepage = "https://example.com"


def _src(name, caps=("bars",), enabled=True, policies=None):
    cls = type(
        name,
        (_Fake,),
        {
            "name": name,
            "capabilities": tuple(CapabilitySpec(c, "whole", ()) for c in caps),
            "default_enabled": enabled,
            "http_policies": policies or {},
        },
    )
    return cls()


@pytest.fixture(autouse=True)
def _clean():
    db.init_db()
    registry.clear()
    yield
    registry.clear()


def test_ordered_priority_disabled_and_unlisted():
    for n in ("alpha", "beta", "gamma", "delta"):
        registry.register(_src(n))
    registry.register(_src("zeta", caps=("news",)))  # lacks 'bars'
    registry.set_enabled("beta", False, "test")
    db.set_setting("source_priority", {"bars": ["gamma", "beta", "missing", "zeta"]})
    assert [s.name for s in registry.ordered("bars")] == ["gamma", "alpha", "delta"]


def test_default_enabled_false_row_created():
    registry.register(_src("off", enabled=False))
    assert registry.is_enabled("off") is False
    assert registry.ordered("bars") == []


def test_duplicate_and_bad_names():
    registry.register(_src("alpha"))
    with pytest.raises(ValueError):
        registry.register(_src("alpha"))
    for bad in ("A1", "1abc", "a", "has-dash"):
        with pytest.raises(ValueError):
            registry.register(_src(bad))


def test_register_adds_http_policy():
    p = HttpPolicy(3.0, 10, 1)
    registry.register(_src("pol", policies={"example.test": p}))
    assert http.POLICIES["example.test"] == p
    http.POLICIES.pop("example.test")


def test_spec_lookup():
    registry.register(_src("alpha"))
    assert registry.spec("alpha", "bars") is not None
    assert registry.spec("alpha", "news") is None
    assert registry.spec("nope", "bars") is None


@pytest.mark.parametrize(
    "status,exc",
    [(403, SourceRefused), (401, SourceRefused), (429, SourceRefused), (404, NotFound),
     (500, SourceError), (None, SourceError)],
)
def test_from_fetch_error(status, exc):
    assert type(from_fetch_error(FetchError("x", status=status))) is exc


def test_unimplemented_methods_raise():
    with pytest.raises(NotImplementedError):
        _Fake().news()
