"""Every source x capability x job variant becomes a job (SPEC §3.4)."""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, time, timedelta

from app import config, db, timeutil
from app.jobs import registry as jobs_registry
from app.jobs.context import JobContext
from app.jobs.registry import JobDef
from app.sources import registry, store
from app.sources.base import (
    JobVariant,
    NotFound,
    SourceRefused,
    from_fetch_error,
)
from app.sources.http import FetchError

log = logging.getLogger(__name__)

CAP_LABEL = {
    "universe": "stock list",
    "bars": "daily prices",
    "actions": "splits & bonuses",
    "index": "market index",
    "fundamentals": "fundamentals",
    "quarters": "quarterly results",
    "announcements": "announcements",
    "news": "news",
    "symbol_changes": "ticker changes",
    "events": "board meetings",
    "research": "broker research calls",
}

# capability -> (stage, follow-up jobs enqueued when the run stored >= 1 row)
STAGES: dict[str, tuple[int, tuple[str, ...]]] = {
    "universe": (0, ()),
    "symbol_changes": (0, ("price_checks", "screens_run")),
    "bars": (1, ("event_factors", "price_checks", "screens_run")),
    "index": (1, ("screens_run",)),
    "actions": (2, ("event_factors", "price_checks")),
    "events": (3, ()),
    "research": (3, ()),
    "announcements": (3, ("alerts_scan",)),
    "news": (3, ("alerts_scan",)),
    "fundamentals": (6, ("fundamentals_merge",)),
    "quarters": (6, ("fundamentals_merge",)),
}
BACKFILL_STAGE = 7
ANNOUNCEMENT_MAX_LOOKBACK_DAYS = 30
INDEX_NAME = "NIFTY 500"

Fetched = dict[str, tuple[str, str]]  # key -> (status, fetched_at ISO)


def job_name(source: str, capability: str, variant: JobVariant) -> str:
    return f"{capability}.{source}" + (f".{variant.suffix}" if variant.suffix else "")


# ---- pure key selection ----


def _age_ok(fetched_at: str, now: datetime, min_age_hours: float) -> bool:
    return now - datetime.fromisoformat(fetched_at) < timedelta(hours=min_age_hours)


def select_symbol_keys(
    keys: list[str],
    fetched: Fetched,
    now: datetime,
    min_age_hours: float,
    max_items: int,
    override: list[str] | None = None,
) -> list[str]:
    """Never-fetched keys first (input order), then oldest fetch first; fresh ok/not_found skipped."""
    if override:
        return list(override)
    never = [k for k in keys if k not in fetched]
    stale = [
        k
        for k in keys
        if k in fetched
        and not (fetched[k][0] in ("ok", "not_found") and _age_ok(fetched[k][1], now, min_age_hours))
    ]
    stale.sort(key=lambda k: datetime.fromisoformat(fetched[k][1]))
    return (never + stale)[:max_items]


def weekdays(start: date, end: date) -> list[date]:
    """Mon-Fri dates from start to end inclusive."""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def all_days(start: date, end: date) -> list[date]:
    """Every calendar date from start to end inclusive."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def select_date_keys(
    history_start: date,
    today: date,
    now_time: time,
    params: dict,
    fetched: dict[date, tuple[str, datetime]],
    max_items: int | None = None,
) -> list[date]:
    """Weekdays still to fetch. `recent_days` windows catch up every missing day; else a backfill."""
    now_dt = datetime.combine(today, now_time.replace(tzinfo=None), tzinfo=config.TZ)
    done = {d for d, (status, _) in fetched.items() if status in ("ok", "not_found")}
    if "recent_days" in params:
        not_before = time.fromisoformat(params.get("not_before", "00:00"))
        last = today if now_time.replace(tzinfo=None) >= not_before else today - timedelta(days=1)
        window = weekdays(today - timedelta(days=int(params["recent_days"]) * 2), last)
        window = window[-int(params["recent_days"]) :]
        if params.get("weekends") and window:
            window = sorted(window + [d for d in all_days(window[0], window[-1]) if d.weekday() >= 5])
        keys = [d for d in window if d not in done]
    else:
        keys = []
        span = all_days if params.get("weekends") else weekdays
        for d in span(history_start, today - timedelta(days=1)):
            if d in done:
                continue
            row = fetched.get(d)
            if row and row[0] == "failed" and now_dt - row[1] < timedelta(days=1):
                continue
            keys.append(d)
    keys.sort(reverse=bool(params.get("newest_first")))
    return keys[:max_items] if max_items else keys


def announcement_since(last_ok: datetime | None, today: date, days: int) -> date:
    if last_ok is None:
        return today - timedelta(days=days)
    return max(last_ok.date() - timedelta(days=1), today - timedelta(days=ANNOUNCEMENT_MAX_LOOKBACK_DAYS))


# ---- database helpers ----


def _fetched(conn: sqlite3.Connection, source: str, capability: str) -> Fetched:
    rows = conn.execute(
        "SELECT key, status, fetched_at FROM source_fetch WHERE source=? AND capability=?",
        (source, capability),
    )
    return {r["key"]: (r["status"], r["fetched_at"]) for r in rows}


def _scope_symbols(conn: sqlite3.Connection, scope: str) -> list[str]:
    if scope == "watch":
        q = (
            "SELECT symbol FROM watchlist UNION "
            "SELECT symbol FROM positions WHERE status='open' ORDER BY symbol"
        )
    else:
        q = "SELECT symbol FROM symbols WHERE in_universe=1 ORDER BY symbol"
    return [r["symbol"] for r in conn.execute(q)]


def _record_fetch(
    conn: sqlite3.Connection,
    source: str,
    capability: str,
    key: str,
    status: str,
    rows: int | None,
    error: str | None = None,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO source_fetch(source, capability, key, status, fetched_at, rows, error) "
        "VALUES (?,?,?,?,?,?,?)",
        (source, capability, key, status, timeutil.now_iso(), rows, error),
    )


def _select_keys(ctx: JobContext, source: str, capability: str, variant: JobVariant) -> list[str]:
    spec = registry.spec(source, capability)
    assert spec is not None
    override = ctx.params.get("keys")
    now = timeutil.now()
    with db.tx() as conn:
        fetched = _fetched(conn, source, capability)
        symbols = _scope_symbols(conn, variant.scope) if spec.mode == "by_symbol" else []
    if spec.mode == "by_symbol":
        return select_symbol_keys(symbols, fetched, now, variant.min_age_hours, variant.max_items, override)
    if spec.mode == "whole":
        return select_symbol_keys(["all"], fetched, now, variant.min_age_hours, 1, override)
    if override:
        return list(override)
    dated = {
        date.fromisoformat(k): (status, datetime.fromisoformat(at)) for k, (status, at) in fetched.items()
    }
    start = date.fromisoformat(spec.history_start) if spec.history_start else config.HISTORY_START
    keys = select_date_keys(
        start, timeutil.today(), now.timetz(), variant.params, dated, variant.max_items
    )
    return [d.isoformat() for d in keys]


# ---- fetching one key ----


RESPLIT_DAYS = 45  # a split/bonus this recent makes stored adjusted bars stale


def _fetch(source: str, capability: str, key: str, variant: JobVariant):
    """Call the adapter method for this capability; always returns a list of records."""
    src = registry.get(source)
    spec = registry.spec(source, capability)
    assert spec is not None
    today = timeutil.today()
    with db.tx() as conn:
        if capability == "bars" and spec.mode == "by_symbol":
            last = store.last_bar_date(source, key, conn)
        elif capability == "index":
            last = store.last_index_date(source, conn)
        else:
            last = None
        known: set[str] = set()
        last_ok: datetime | None = None
        resplit = False
        if capability == "bars" and spec.mode == "by_symbol" and spec.adjusted is True:
            cutoff = (today - timedelta(days=RESPLIT_DAYS)).isoformat()
            resplit = (
                conn.execute(
                    "SELECT 1 FROM corp_actions WHERE symbol=? AND kind IN ('split','bonus') "
                    "AND ex_date>=? LIMIT 1",
                    (key, cutoff),
                ).fetchone()
                is not None
            )
        if capability == "quarters":
            known = {
                r["period_end"]
                for r in conn.execute(
                    "SELECT period_end FROM quarters WHERE source=? AND symbol=? AND parse_error IS NULL",
                    (source, key),
                )
            }
        if capability == "announcements":
            row = conn.execute(
                "SELECT fetched_at FROM source_fetch WHERE source=? AND capability=? AND key=? "
                "AND status='ok'",
                (source, capability, key),
            ).fetchone()
            last_ok = datetime.fromisoformat(row["fetched_at"]) if row else None
    if last and not resplit:
        start = date.fromisoformat(last) - timedelta(days=5)
    else:
        start = config.HISTORY_START
    try:
        if capability == "universe":
            return src.universe()
        if capability == "bars" and spec.mode == "by_date":
            return src.bars_for_date(date.fromisoformat(key))
        if capability == "bars":
            return src.bars_for_symbol(key, start, today)
        if capability == "actions":
            return src.actions(key)
        if capability == "index":
            return src.index_bars(INDEX_NAME, start)
        if capability == "fundamentals":
            return [src.fundamentals(key)]
        if capability == "quarters":
            return src.quarters(key, known)
        if capability == "announcements":
            since = announcement_since(last_ok, today, int(variant.params.get("days", 7)))
            return src.announcements(key, since)
        if capability == "news":
            return src.news()
        if capability == "symbol_changes":
            return src.symbol_changes()
        if capability == "events":
            return src.events()
        if capability == "research":
            return src.research()
    except FetchError as e:
        raise from_fetch_error(e) from e
    raise ValueError(f"unknown capability: {capability}")


def _note_error(source: str, error: str) -> None:
    with db.tx() as conn:
        conn.execute(
            "UPDATE source_state SET last_error_at=?, last_error=? WHERE source=?",
            (timeutil.now_iso(), error[:500], source),
        )


def _pause_refused(source: str, label: str, detail: str) -> str:
    msg = f"{label} refused ({detail})"
    registry.set_enabled(source, False, msg)
    _note_error(source, msg)
    db.insert_alert(
        "job_refused",
        f"{msg}. The source is paused: re-enable it on the Sources page.",
        dedupe_key=f"refused:{source}:{timeutil.today().isoformat()}",
        severity="warn",
    )
    return msg


def run_source_job(ctx: JobContext, source: str, capability: str, variant: JobVariant) -> str:
    src = registry.get(source)
    if not registry.is_enabled(source):
        return "source disabled"
    for secret_key in src.secrets:
        if not src.secret(secret_key):
            raise RuntimeError(f"missing credentials: {secret_key}")

    keys = _select_keys(ctx, source, capability, variant)
    ctx.set_total(len(keys))
    stored = 0
    for key in keys:
        ctx.check_stop()
        try:
            records = _fetch(source, capability, key, variant)
        except NotFound as e:
            with db.tx() as conn:
                _record_fetch(conn, source, capability, key, "not_found", 0)
            ctx.item(key, "skipped", str(e) or "not found")
            continue
        except SourceRefused as e:
            ctx.item(key, "failed", f"refused: {e}")
            msg = _pause_refused(source, src.label, str(e))
            ctx.log(msg, "error")
            return msg
        except Exception as e:  # SourceError and anything unexpected: this key fails, the run goes on
            _fail_key(ctx, source, capability, key, e)
            continue
        try:
            with db.tx() as conn:
                n = store.save(capability, source, records, key=key, conn=conn)
                _record_fetch(conn, source, capability, key, "ok", n)
                conn.execute(
                    "UPDATE source_state SET last_ok_at=? WHERE source=?", (timeutil.now_iso(), source)
                )
        except Exception as e:
            _fail_key(ctx, source, capability, key, e)
            continue
        if n >= 1:
            stored += 1
            ctx.item(key, "ok", f"{n} rows")
        else:
            ctx.item(key, "skipped", "no new rows")
    return f"{src.label}: {stored} of {len(keys)} stored"


def _fail_key(ctx: JobContext, source: str, capability: str, key: str, e: Exception) -> None:
    detail = f"{type(e).__name__}: {e}"
    log.warning("%s %s %s failed: %s", source, capability, key, detail)
    with db.tx() as conn:
        _record_fetch(conn, source, capability, key, "failed", None, detail[:500])
    _note_error(source, detail)
    ctx.item(key, "failed", detail[:500])


# ---- registration ----


def register_source_jobs() -> None:
    """One JobDef per registered source x capability x variant. Safe to call twice."""
    for src in registry.all_sources():
        for cs in src.capabilities:
            for variant in cs.jobs:
                name = job_name(src.name, cs.capability, variant)
                try:
                    jobs_registry.get(name)
                    continue
                except KeyError:
                    pass
                stage, followups = STAGES[cs.capability]
                title = f"{src.label}: {CAP_LABEL[cs.capability]}"
                if variant.title:
                    title += f" ({variant.title})"
                jobs_registry.register(
                    JobDef(
                        name=name,
                        title=title,
                        description=f"{src.description} ({CAP_LABEL[cs.capability]}, {cs.mode})",
                        fn=_make_fn(src.name, cs.capability, variant),
                        default_schedule=dict(variant.schedule),
                        retryable=True,
                        group=f"source:{src.name}",
                        stage=BACKFILL_STAGE if variant.suffix == "backfill" else stage,
                        lane="background",
                        followups=followups,
                        refresh=variant.refresh,
                    )
                )


def _make_fn(source: str, capability: str, variant: JobVariant):
    def fn(ctx: JobContext) -> str | None:
        return run_source_job(ctx, source, capability, variant)

    return fn
