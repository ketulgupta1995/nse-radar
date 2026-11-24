"""Turso (libsql) behind the sqlite3 surface the app uses (SPEC §17.2, N002).

libsql rows are plain tuples and its errors are ValueErrors, and its `executemany` costs one network
round trip per row (docs/CLOUD_SPIKE.md). This wrapper gives callers `sqlite3.Row`-like rows, maps errors
to `sqlite3.IntegrityError` / `sqlite3.OperationalError`, and batches `executemany`.
"""

import logging
import math
import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

from app import config

log = logging.getLogger(__name__)

MAX_PARAMS = 30000  # per multi-row INSERT statement
SCRIPT_CHUNK = 1000  # statements per executescript batch

_INSERT_RE = re.compile(
    r"^\s*(INSERT\s+(?:OR\s+(?:IGNORE|REPLACE)\s+)?INTO\s+[\w\".]+\s*\([^()]*\)\s*VALUES)\s*"
    r"(\([^()'\"]*\))\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)


class Row(tuple):
    """Like sqlite3.Row: `row["col"]` (case-insensitive), `row[0]`, `keys()`, `dict(row)`."""

    _cols: tuple[str, ...]
    _index: dict[str, int]

    def __new__(cls, values: Iterable[Any], cols: tuple[str, ...], index: dict[str, int]) -> "Row":
        row = super().__new__(cls, values)
        row._cols = cols
        row._index = index
        return row

    def __getitem__(self, key: Any) -> Any:  # type: ignore[override]
        if isinstance(key, str):
            try:
                key = self._index[key.lower()]
            except KeyError:
                raise IndexError("No item with that key") from None
        return tuple.__getitem__(self, key)

    def keys(self) -> list[str]:
        return list(self._cols)


def _col_name(name: str) -> str:
    """Turso's SQL parser uppercases keyword column names in DDL it runs (`key` -> `KEY`, also `rows`,
    `explain`, `trigger`), so a table created through Turso reports them in capitals (N002 real-Turso
    check, 2026-11-24). The code never uses all-caps names, so give them back in lower case."""
    return name.lower() if name.isupper() else name


def _map_error(e: Exception) -> sqlite3.Error:
    msg = str(e)
    if "SQLITE_CONSTRAINT" in msg or "constraint failed" in msg.lower():
        return sqlite3.IntegrityError(msg)
    return sqlite3.OperationalError(msg)


def _call(fn, *args: Any) -> Any:
    try:
        return fn(*args)
    except sqlite3.Error:
        raise
    except Exception as e:  # libsql raises ValueError (and friends) for every SQL error
        raise _map_error(e) from e


class Cursor:
    def __init__(self, raw: Any = None, rowcount: int | None = None) -> None:
        self._raw = raw
        self._rowcount = rowcount
        desc = getattr(raw, "description", None) if raw is not None else None
        if desc:
            desc = tuple((_col_name(d[0]), *d[1:]) for d in desc)
        self.description = desc
        self._cols: tuple[str, ...] = tuple(d[0] for d in desc) if desc else ()
        self._index = {c.lower(): i for i, c in reversed(list(enumerate(self._cols)))}

    @property
    def lastrowid(self) -> int | None:
        return getattr(self._raw, "lastrowid", None)

    @property
    def rowcount(self) -> int:
        if self._rowcount is not None:
            return self._rowcount
        return getattr(self._raw, "rowcount", -1)

    def _wrap(self, values: Any) -> Row | None:
        return None if values is None else Row(values, self._cols, self._index)

    def fetchone(self) -> Row | None:
        if self._raw is None:
            return None
        return self._wrap(_call(self._raw.fetchone))

    def fetchall(self) -> list[Row]:
        if self._raw is None:
            return []
        return [Row(v, self._cols, self._index) for v in _call(self._raw.fetchall)]

    def fetchmany(self, size: int = 1) -> list[Row]:
        if self._raw is None:
            return []
        return [Row(v, self._cols, self._index) for v in _call(self._raw.fetchmany, size)]

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())

    def close(self) -> None:
        close = getattr(self._raw, "close", None)
        if close is not None:
            close()


def sql_literal(v: Any) -> str:
    """Inline a parameter safely as an SQL literal (only for the batched executemany path)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "NULL"  # sqlite3 stores NaN as NULL
        if math.isinf(v):
            return "1e999" if v > 0 else "-1e999"
        return repr(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    if isinstance(v, bytes | bytearray | memoryview):
        return "X'" + bytes(v).hex() + "'"
    raise sqlite3.ProgrammingError(f"unsupported parameter type {type(v).__name__}")


def inline_params(sql: str, params: Sequence[Any]) -> str:
    """Replace each `?` outside quotes and comments with its literal."""
    out: list[str] = []
    it = iter(params)
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in "'\"`[":
            end_ch = "]" if ch == "[" else ch
            j = sql.find(end_ch, i + 1)
            j = n - 1 if j < 0 else j
            out.append(sql[i : j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(sql[i:j])
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(sql[i:j])
            i = j
        elif ch == "?":
            try:
                out.append(sql_literal(next(it)))
            except StopIteration:
                raise sqlite3.ProgrammingError("not enough parameters") from None
            i += 1
        else:
            out.append(ch)
            i += 1
    if next(it, _END) is not _END:
        raise sqlite3.ProgrammingError("too many parameters")
    return "".join(out)


_END = object()


class TursoConnection:
    """The sqlite3.Connection surface the app uses, over a libsql connection."""

    row_factory: Any = sqlite3.Row  # accepted and ignored: rows are always Row

    def __init__(self, raw: Any, replica: bool = False) -> None:
        self._raw = raw
        self.replica = replica

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Cursor:
        return Cursor(_call(self._raw.execute, sql, tuple(params) if isinstance(params, list) else params))

    def executescript(self, script: str) -> Cursor:
        _call(self._raw.executescript, script)
        return Cursor()

    def executemany(self, sql: str, seq_of_params: Iterable[Any]) -> Cursor:
        rows = [tuple(p) if not isinstance(p, dict) else p for p in seq_of_params]
        if not rows:
            return Cursor(rowcount=0)
        if any(isinstance(p, dict) for p in rows):  # named params: rare, keep it simple
            total = sum(max(self.execute(sql, p).rowcount, 0) for p in rows)
            return Cursor(rowcount=total)
        m = _INSERT_RE.match(sql)
        if m and m.group(2).count("?") == len(rows[0]):
            return self._insert_many(m.group(1), m.group(2), rows)
        return self._script_many(sql, rows)

    def _insert_many(self, head: str, values: str, rows: list[tuple]) -> Cursor:
        per = max(1, MAX_PARAMS // max(1, len(rows[0])))
        total = 0
        for start in range(0, len(rows), per):
            chunk = rows[start : start + per]
            if any(len(r) != len(rows[0]) for r in chunk):
                raise sqlite3.ProgrammingError("rows have different numbers of parameters")
            sql = f"{head} {','.join([values] * len(chunk))}"
            cur = self.execute(sql, [v for r in chunk for v in r])
            total += max(cur.rowcount, 0)
        return Cursor(rowcount=total)

    def _script_many(self, sql: str, rows: list[tuple]) -> Cursor:
        stmt = sql.strip().rstrip(";")
        for start in range(0, len(rows), SCRIPT_CHUNK):
            chunk = rows[start : start + SCRIPT_CHUNK]
            self.executescript(";\n".join(inline_params(stmt, r) for r in chunk) + ";")
        return Cursor(rowcount=-1)  # a batch reports no per-statement counts

    def commit(self) -> None:
        _call(self._raw.commit)

    def rollback(self) -> None:
        _call(self._raw.rollback)

    def sync(self) -> None:
        if self.replica:
            _call(self._raw.sync)

    def close(self) -> None:
        close = getattr(self._raw, "close", None)
        if close is not None:
            close()

    def __enter__(self) -> "TursoConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def connect_turso() -> TursoConnection:
    """Remote Turso, or an embedded replica when `REPLICA_PATH` is set (SPEC §17.2)."""
    import libsql  # local mode never needs the package

    if config.REPLICA_PATH:
        Path(config.REPLICA_PATH).parent.mkdir(parents=True, exist_ok=True)
        raw = libsql.connect(
            config.REPLICA_PATH,
            sync_url=config.TURSO_URL,
            auth_token=config.TURSO_TOKEN,
            isolation_level=None,
        )
        conn = TursoConnection(raw, replica=True)
    else:
        raw = libsql.connect(config.TURSO_URL, auth_token=config.TURSO_TOKEN, isolation_level=None)
        conn = TursoConnection(raw)
    try:  # the file PRAGMAs (WAL, synchronous, cache_size, ...) are refused remotely; skip them
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error:
        log.warning("Turso refused PRAGMA foreign_keys=ON; continuing without it")
    return conn
