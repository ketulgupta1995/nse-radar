"""Turso (libsql) behind the sqlite3 surface the app uses (SPEC §17.2, N002).

libsql rows are plain tuples and its errors are ValueErrors, and its `executemany` costs one network
round trip per row (docs/CLOUD_SPIKE.md). This wrapper gives callers `sqlite3.Row`-like rows, maps errors
to `sqlite3.IntegrityError` / `sqlite3.OperationalError`, and batches `executemany`.

Embedded replica (GitHub Actions): reads are local, but every write, BEGIN and COMMIT is a round trip to the
primary, and a read inside an open transaction goes to the primary too. So `db.tx()` on a replica opens a
*lazy* transaction (`begin_lazy`): reads run on the local file, writes are held back, and COMMIT sends them
as one `BEGIN IMMEDIATE; ...; COMMIT` batch, which is one round trip. A transaction that only reads never
leaves the runner. When the code needs a write's result before COMMIT (`rowcount`, `lastrowid`, rows from
RETURNING) or reads after writing, the held writes are sent inside a real remote transaction and the rest
of it runs statement by statement, as before.

libsql's replica `executescript` does not raise when a statement fails: it stops, the primary rolls the
batch back, and the connection's `in_transaction` stays True (checked against real Turso, 2026-11-25).
A batch is therefore always one whole transaction, and `in_transaction` after it tells success from
failure. On failure the statements are replayed one by one to raise the real error.
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
SCRIPT_CHUNK = 1000  # statements per executescript batch outside a transaction
MAX_BATCH_BYTES = 2_000_000  # a lazy transaction holding more SQL than this goes remote instead

_LEAD_RE = re.compile(r"^(?:\s+|--[^\n]*(?:\n|$)|/\*.*?\*/)*", re.DOTALL)
_WRITE_WORD_RE = re.compile(r"\b(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER)\b", re.IGNORECASE)

_INSERT_RE = re.compile(
    r"^\s*(INSERT\s+(?:OR\s+(?:IGNORE|REPLACE)\s+)?INTO\s+[\w\".]+\s*\([^()]*\)\s*VALUES)\s*"
    r"(\([^()'\"]*\))\s*(ON\s+CONFLICT\b[^?;]*?)?\s*;?\s*$",  # an upsert tail without params is fine
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
    """A libsql cursor with sqlite3 names. A write held in a lazy transaction gets a cursor with no result
    yet (`owner` set): asking for its result sends the held writes to the primary first."""

    def __init__(self, raw: Any = None, rowcount: int | None = None,
                 owner: "TursoConnection | None" = None) -> None:  # fmt: skip
        self._owner = owner
        self._batched = False  # its write went out in a COMMIT batch: no per-statement result
        self._rowcount = rowcount
        self._bind(raw)

    def _bind(self, raw: Any) -> None:
        self._raw = raw
        desc = getattr(raw, "description", None) if raw is not None else None
        if desc:
            desc = tuple((_col_name(d[0]), *d[1:]) for d in desc)
        self._description = desc
        self._cols: tuple[str, ...] = tuple(d[0] for d in desc) if desc else ()
        self._index = {c.lower(): i for i, c in reversed(list(enumerate(self._cols)))}

    def _ensure(self) -> None:
        if self._owner is not None:
            owner, self._owner = self._owner, None
            owner._go_remote()

    def _no_result(self, what: str) -> None:
        if self._batched:
            raise sqlite3.ProgrammingError(
                f"{what} is unknown: the write was sent in a COMMIT batch; read it inside the transaction"
            )

    @property
    def description(self) -> Any:
        self._ensure()
        return self._description

    @property
    def lastrowid(self) -> int | None:
        self._ensure()
        self._no_result("lastrowid")
        return getattr(self._raw, "lastrowid", None)

    @property
    def rowcount(self) -> int:
        self._ensure()
        if self._rowcount is not None:
            return self._rowcount
        self._no_result("rowcount")
        return getattr(self._raw, "rowcount", -1)

    def _wrap(self, values: Any) -> Row | None:
        return None if values is None else Row(values, self._cols, self._index)

    def fetchone(self) -> Row | None:
        self._ensure()
        if self._raw is None:
            return None
        return self._wrap(_call(self._raw.fetchone))

    def fetchall(self) -> list[Row]:
        self._ensure()
        if self._raw is None:
            return []
        return [Row(v, self._cols, self._index) for v in _call(self._raw.fetchall)]

    def fetchmany(self, size: int = 1) -> list[Row]:
        self._ensure()
        if self._raw is None:
            return []
        return [Row(v, self._cols, self._index) for v in _call(self._raw.fetchmany, size)]

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())

    def close(self) -> None:
        close = getattr(self._raw, "close", None)
        if close is not None:
            close()


def _first_word(sql: str) -> str:
    rest = sql[_LEAD_RE.match(sql).end():]  # type: ignore[union-attr]
    m = re.match(r"[A-Za-z]+", rest)
    return m.group(0).upper() if m else ""


def is_read(sql: str) -> bool:
    """True for statements that never write. Unsure cases count as writes (they then run remotely)."""
    word = _first_word(sql)
    if word in ("SELECT", "EXPLAIN", "VALUES"):
        return True
    if word == "PRAGMA":
        return "=" not in sql and "(" not in sql
    if word == "WITH":
        return not _WRITE_WORD_RE.search(sql)
    return False


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

    def __init__(self, raw: Any, replica: bool = False, reopen: Any = None) -> None:
        self._raw = raw
        self.replica = replica
        self._reopen_raw = reopen  # makes a fresh raw connection (after a failed batch)
        self._held: list[tuple[str, Cursor | None]] | None = None  # None: no lazy transaction open
        self._held_bytes = 0
        self._remote = False  # the lazy transaction went remote: statements run one by one

    # -- lazy transactions (replica only) ---------------------------------------------------------
    def begin_lazy(self) -> None:
        if self._held is not None:
            raise sqlite3.OperationalError("cannot start a transaction within a transaction")
        self._held, self._held_bytes, self._remote = [], 0, False

    def _holding(self) -> bool:
        return self._held is not None and not self._remote

    def _hold(self, text: str, cursor: Cursor | None) -> None:
        assert self._held is not None
        self._held.append((text.strip().rstrip(";"), cursor))
        self._held_bytes += len(text)
        if self._held_bytes > MAX_BATCH_BYTES:
            self._go_remote()

    def _go_remote(self) -> None:
        """Send the held writes in a real remote transaction; the rest of it runs statement by statement."""
        if not self._holding():
            return
        held, self._held = self._held or [], []
        self._remote = True
        _call(self._raw.execute, "BEGIN IMMEDIATE")
        for text, cur in held:
            raw = _call(self._raw.execute, text)
            if cur is not None:
                cur._owner = None
                cur._bind(raw)

    def _end_lazy(self) -> tuple[list[tuple[str, Cursor | None]], bool]:
        held, remote = self._held or [], self._remote
        self._held, self._held_bytes, self._remote = None, 0, False
        for _, cur in held:
            if cur is not None:
                cur._owner = None
                cur._batched = True
        return held, remote

    def _commit_lazy(self) -> None:
        held, remote = self._end_lazy()
        if remote:
            _call(self._raw.execute, "COMMIT")
        elif held:
            self._run_batch([t for t, _ in held])

    def _rollback_lazy(self) -> None:
        _, remote = self._end_lazy()
        if remote:
            try:
                _call(self._raw.execute, "ROLLBACK")
            except sqlite3.OperationalError as e:
                if "no transaction" not in str(e):
                    raise

    def _run_batch(self, statements: list[str]) -> None:
        """Run the statements as one transaction in one round trip; raise the real error if it fails."""
        script = "BEGIN IMMEDIATE\n;\n" + "\n;\n".join(statements) + "\n;\nCOMMIT;"
        try:
            _call(self._raw.executescript, script)
            failed = bool(getattr(self._raw, "in_transaction", False))
        except sqlite3.Error:
            self._fresh_raw()
            raise
        if failed:  # the primary rolled the batch back; replay it to find (and raise) the failing statement
            self._fresh_raw()
            self._replay(statements)

    def _replay(self, statements: list[str]) -> None:
        _call(self._raw.execute, "BEGIN IMMEDIATE")
        try:
            for text in statements:
                _call(self._raw.execute, text)
        except BaseException:
            try:
                _call(self._raw.execute, "ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        _call(self._raw.execute, "COMMIT")

    def _fresh_raw(self) -> None:
        if self._reopen_raw is None:
            return
        close = getattr(self._raw, "close", None)
        if close is not None:
            try:
                close()
            except Exception:  # noqa: BLE001 - the old connection is being thrown away
                pass
        self._raw = self._reopen_raw()

    # -- the sqlite3 surface ----------------------------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Cursor:
        if self._held is not None:
            word = _first_word(sql)
            if word in ("COMMIT", "END"):
                self._commit_lazy()
                return Cursor()
            if word == "ROLLBACK":
                self._rollback_lazy()
                return Cursor()
            if word == "BEGIN":
                raise sqlite3.OperationalError("cannot start a transaction within a transaction")
            if self._holding():
                if is_read(sql):
                    if self._held:  # read-your-writes: the held writes must reach the primary first
                        self._go_remote()
                elif isinstance(params, dict):
                    self._go_remote()
                else:
                    cur = Cursor(owner=self)
                    self._hold(inline_params(sql, params) if params else sql, cur)
                    return cur
        return Cursor(_call(self._raw.execute, sql, tuple(params) if isinstance(params, list) else params))

    def executescript(self, script: str) -> Cursor:
        self._go_remote()  # a script inside a lazy transaction can't be held statement by statement
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
            return self._insert_many(m.group(1), m.group(2), rows, m.group(3) or "")
        return self._script_many(sql, rows)

    def _insert_many(self, head: str, values: str, rows: list[tuple], tail: str = "") -> Cursor:
        per = max(1, MAX_PARAMS // max(1, len(rows[0])))
        total = 0
        for start in range(0, len(rows), per):
            chunk = rows[start : start + per]
            if any(len(r) != len(rows[0]) for r in chunk):
                raise sqlite3.ProgrammingError("rows have different numbers of parameters")
            sql = f"{head} {','.join([values] * len(chunk))}" + (f" {tail.strip()}" if tail else "")
            params = [v for r in chunk for v in r]
            if self._holding():
                self._hold(inline_params(sql, params), None)
                total = -1
                continue
            cur = self.execute(sql, params)
            if total >= 0:
                total += max(cur.rowcount, 0)
        return Cursor(rowcount=total)

    def _script_many(self, sql: str, rows: list[tuple]) -> Cursor:
        stmt = sql.strip().rstrip(";")
        if self._holding():
            for r in rows:
                self._hold(inline_params(stmt, r), None)
            return Cursor(rowcount=-1)
        if self._held is not None:  # remote transaction: no batch can run inside it safely
            for r in rows:
                self.execute(stmt, r)
            return Cursor(rowcount=-1)
        for start in range(0, len(rows), SCRIPT_CHUNK):
            chunk = rows[start : start + SCRIPT_CHUNK]
            statements = [inline_params(stmt, r) for r in chunk]
            if self.replica:
                self._run_batch(statements)  # errors are only visible this way on a replica
            else:
                self.executescript(";\n".join(statements) + ";")
        return Cursor(rowcount=-1)  # a batch reports no per-statement counts

    def commit(self) -> None:
        _call(self._raw.commit)

    def rollback(self) -> None:
        _call(self._raw.rollback)

    def sync(self) -> None:
        if self.replica:
            _call(self._raw.sync)

    def close(self) -> None:
        if self._held is not None:  # closed with a lazy transaction open: nothing held is sent
            self._rollback_lazy()
        close = getattr(self._raw, "close", None)
        if close is not None:
            close()

    def __enter__(self) -> "TursoConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def connect_turso() -> TursoConnection:
    """Remote Turso, or an embedded replica when `REPLICA_PATH` is set (SPEC §17.2).

    No PRAGMAs: Turso refuses the file ones, and it enforces foreign keys (and ON DELETE CASCADE) without
    `PRAGMA foreign_keys=ON` (checked 2026-11-25), which would cost a round trip per connection.
    """
    import libsql  # local mode never needs the package

    if config.REPLICA_PATH:
        Path(config.REPLICA_PATH).parent.mkdir(parents=True, exist_ok=True)

        def open_replica() -> Any:
            return libsql.connect(
                config.REPLICA_PATH,
                sync_url=config.TURSO_URL,
                auth_token=config.TURSO_TOKEN,
                isolation_level=None,
            )

        return TursoConnection(open_replica(), replica=True, reopen=open_replica)

    def open_remote() -> Any:
        return libsql.connect(config.TURSO_URL, auth_token=config.TURSO_TOKEN, isolation_level=None)

    return TursoConnection(open_remote(), reopen=open_remote)
