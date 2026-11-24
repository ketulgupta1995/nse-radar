"""Credential store: data/secrets.json, mode 0600 (SPEC §3.6).

Values are never logged, returned by an API, put in prompts or stored in SQLite.
"""

import json
import os
import tempfile
import threading

from app import config

_lock = threading.Lock()


def _load() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(config.SECRETS_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, dict[str, str]]) -> None:
    path = config.SECRETS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".secrets-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def get(source: str, key: str) -> str | None:
    value = _load().get(source, {}).get(key)
    return value or None


def set(source: str, key: str, value: str | None) -> None:  # noqa: A001
    with _lock:
        data = _load()
        if value is None:
            data.get(source, {}).pop(key, None)
            if source in data and not data[source]:
                del data[source]
        else:
            data.setdefault(source, {})[key] = value
        _save(data)


def status(source: str) -> dict[str, bool]:
    """Key -> is set. Includes the keys the registered source declares, never any value."""
    from app.sources import registry

    stored = _load().get(source, {})
    try:
        declared = registry.get(source).secrets
    except KeyError:
        declared = ()
    keys = list(dict.fromkeys([*declared, *stored]))
    return {k: bool(stored.get(k)) for k in keys}
