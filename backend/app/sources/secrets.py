"""Credential store (SPEC §3.6, N021).

Locally: data/secrets.json, mode 0600. In the cloud (`vercel`, `actions`) the function's file system is
read-only and the runner's is thrown away, so values live in the `source_secrets` table in Turso, which
is private. Values are never logged, returned by an API or put in prompts.
"""

import json
import os
import tempfile
import threading

from app import config, db

_lock = threading.Lock()


def _in_db() -> bool:
    return config.RUNTIME in ("vercel", "actions")


# ---- local: the JSON file ------------------------------------------------------------------


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


def _file_set(source: str, key: str, value: str | None) -> None:
    with _lock:
        data = _load()
        if value is None:
            data.get(source, {}).pop(key, None)
            if source in data and not data[source]:
                del data[source]
        else:
            data.setdefault(source, {})[key] = value
        _save(data)


# ---- cloud: the source_secrets table -------------------------------------------------------


def _db_source(source: str) -> dict[str, str]:
    with db.read() as c:
        rows = c.execute("SELECT key, value FROM source_secrets WHERE source=?", (source,)).fetchall()
    return {r["key"]: r["value"] for r in rows}


def _db_set(source: str, key: str, value: str | None) -> None:
    with db.tx() as c:
        if value is None:
            c.execute("DELETE FROM source_secrets WHERE source=? AND key=?", (source, key))
        else:
            c.execute(
                "INSERT INTO source_secrets(source, key, value) VALUES (?,?,?) "
                "ON CONFLICT(source, key) DO UPDATE SET value=excluded.value",
                (source, key, value),
            )


# ---- public API ----------------------------------------------------------------------------


def _stored(source: str) -> dict[str, str]:
    return _db_source(source) if _in_db() else _load().get(source, {})


def get(source: str, key: str) -> str | None:
    value = _stored(source).get(key)
    return value or None


def set(source: str, key: str, value: str | None) -> None:  # noqa: A001
    if _in_db():
        _db_set(source, key, value)
    else:
        _file_set(source, key, value)


def status(source: str) -> dict[str, bool]:
    """Key -> is set. Includes the keys the registered source declares, never any value."""
    from app.sources import registry

    stored = _stored(source)
    try:
        declared = registry.get(source).secrets
    except KeyError:
        declared = ()
    keys = list(dict.fromkeys([*declared, *stored]))
    return {k: bool(stored.get(k)) for k in keys}
