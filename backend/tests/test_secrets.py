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
