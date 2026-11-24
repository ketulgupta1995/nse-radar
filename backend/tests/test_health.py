import sys

from app import plugins, timeutil


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["time"].endswith("+05:30")


def test_now_is_ist():
    assert timeutil.now().utcoffset().total_seconds() == 5.5 * 3600


def test_non_api_path_returns_200(client):
    assert client.get("/some/page").status_code == 200


def test_unknown_api_path_404(client):
    assert client.get("/api/nope").status_code == 404


def test_import_all_skips_private(tmp_path, monkeypatch):
    pkg = tmp_path / "tpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "b.py").write_text("X = 'b'")
    (pkg / "a.py").write_text("X = 'a'")
    (pkg / "_hidden.py").write_text("X = 'h'")
    monkeypatch.syspath_prepend(str(tmp_path))
    mods = plugins.import_all("tpkg")
    assert [m.__name__ for m in mods] == ["tpkg.a", "tpkg.b"]
    sys.modules.pop("tpkg", None)
