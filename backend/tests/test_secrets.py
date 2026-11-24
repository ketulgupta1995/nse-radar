import json
import stat

from app import config
from app.sources import registry, secrets
from app.sources.base import BaseSource


def test_set_get_delete():
    assert secrets.get("s", "k") is None
    secrets.set("s", "k", "v1")
    assert secrets.get("s", "k") == "v1"
    secrets.set("s", "k", None)
    assert secrets.get("s", "k") is None
    assert json.loads(config.SECRETS_PATH.read_text()) == {}


def test_file_mode_0600():
    secrets.set("s", "k", "v")
    assert stat.S_IMODE(config.SECRETS_PATH.stat().st_mode) == 0o600
    secrets.set("s", "k2", "v")
    assert stat.S_IMODE(config.SECRETS_PATH.stat().st_mode) == 0o600


def test_status_booleans_never_values():
    class S(BaseSource):
        name, label, description, homepage = "sec", "S", "d", "h"
        capabilities = ()
        secrets = ("api_key", "other")

    registry.clear()
    registry.register(S())
    secrets.set("sec", "api_key", "TOP-SECRET")
    st = secrets.status("sec")
    assert st == {"api_key": True, "other": False}
    assert "TOP-SECRET" not in repr(st)
    assert S().secret("api_key") == "TOP-SECRET"
    registry.clear()


def test_cloud_mode_uses_the_table_not_the_file(monkeypatch):
    """Vercel's file system is read-only: in vercel/actions mode secrets live in source_secrets (N021)."""
    from app import db

    db.init_db()
    for mode in ("vercel", "actions"):
        monkeypatch.setattr(config, "RUNTIME", mode)
        secrets.set("cloud", "token", f"V-{mode}")
        assert secrets.get("cloud", "token") == f"V-{mode}"  # the second set overwrites
        assert secrets.status("cloud") == {"token": True}
    assert not config.SECRETS_PATH.exists()
    with db.read() as c:
        rows = c.execute("SELECT source, key, value FROM source_secrets").fetchall()
    assert [tuple(r) for r in rows] == [("cloud", "token", "V-actions")]
    secrets.set("cloud", "token", None)
    assert secrets.get("cloud", "token") is None and secrets.status("cloud") == {}
    monkeypatch.setattr(config, "RUNTIME", "local")
    secrets.set("cloud", "token", "local")
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM source_secrets").fetchone()[0] == 0  # local keeps the file
    assert json.loads(config.SECRETS_PATH.read_text()) == {"cloud": {"token": "local"}}
