import sys

import pytest

from app.plugins import import_all


def _pkg(tmp_path, monkeypatch, files: dict[str, str]) -> str:
    root = tmp_path / "plugpkg"
    root.mkdir()
    (root / "__init__.py").write_text("")
    for name, body in files.items():
        (root / f"{name}.py").write_text(body)
    monkeypatch.syspath_prepend(str(tmp_path))
    for k in [k for k in sys.modules if k.startswith("plugpkg")]:
        monkeypatch.delitem(sys.modules, k)
    return "plugpkg"


def test_missing_third_party_library_is_skipped(tmp_path, monkeypatch, caplog):
    pkg = _pkg(tmp_path, monkeypatch, {"a_ok": "X = 1", "b_lib": "import no_such_lib_xyz"})
    mods = import_all(pkg)
    assert [m.__name__ for m in mods] == ["plugpkg.a_ok"]
    assert "no_such_lib_xyz" in caplog.text


def test_missing_app_module_still_raises(tmp_path, monkeypatch):
    pkg = _pkg(tmp_path, monkeypatch, {"bad": "import app.no_such_module_xyz"})
    with pytest.raises(ModuleNotFoundError):
        import_all(pkg)


def test_missing_package_is_quiet():
    assert import_all("app.no_such_package_xyz") == []
