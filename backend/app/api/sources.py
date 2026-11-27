"""Sources API (SPEC §6.5): list, switch on/off, secrets, priority, coverage."""

from datetime import timedelta

from fastapi import APIRouter, HTTPException

from app import bardb, config, db, timeutil
from app.analytics import frames
from app.sources import registry, secrets
from app.sources.base import BaseSource
from app.sources.jobs import job_name

router = APIRouter()

CAPABILITIES = ("universe", "bars", "actions", "index", "fundamentals", "quarters", "announcements", "news")


def _stats(c, name: str) -> dict:
    since = (timeutil.now() - timedelta(days=7)).isoformat(timespec="seconds")
    counts = {
        r["status"]: r["n"]
        for r in c.execute(
            "SELECT status, COUNT(*) n FROM source_fetch WHERE source=? AND fetched_at >= ? GROUP BY status",
            (name, since),
        )
    }
    return {
        "ok_7d": counts.get("ok", 0),
        "failed_7d": counts.get("failed", 0),
        "not_found_7d": counts.get("not_found", 0),
    }


def _source(c, src: BaseSource) -> dict:
    enabled = registry.is_enabled(src.name, c)
    row = c.execute("SELECT * FROM source_state WHERE source=?", (src.name,)).fetchone()
    return {
        "name": src.name,
        "label": src.label,
        "description": src.description,
        "homepage": src.homepage,
        "enabled": enabled,
        "paused_reason": row["paused_reason"],
        "last_ok_at": row["last_ok_at"],
        "last_error_at": row["last_error_at"],
        "last_error": row["last_error"],
        "capabilities": [
            {
                "capability": cs.capability,
                "mode": cs.mode,
                "adjusted": cs.adjusted,
                "jobs": [job_name(src.name, cs.capability, v) for v in cs.jobs],
            }
            for cs in src.capabilities
        ],
        # only sources that declare secrets can have stored ones; the lookup costs a connection each
        "secrets": secrets.status(src.name) if src.secrets else {},
        "stats": _stats(c, src.name),
    }


def _priority(c) -> dict:
    caps: dict[str, list[str]] = {}
    for src in registry.all_sources():
        for cs in src.capabilities:
            caps.setdefault(cs.capability, []).append(src.name)
    return {**db.get_setting("source_priority", c), "capabilities": caps}


@router.get("/sources")
def list_sources() -> list[dict]:
    with db.tx() as c:
        return [_source(c, s) for s in registry.all_sources()]


@router.get("/sources/priority")
def get_priority() -> dict:
    with db.tx() as c:
        return _priority(c)


@router.put("/sources/priority")
def put_priority(body: dict[str, list[str]]) -> dict:
    for cap, names in body.items():
        if cap not in CAPABILITIES:
            raise HTTPException(400, f"unknown capability: {cap}")
        if len(set(names)) != len(names):
            raise HTTPException(400, f"{cap}: a source is listed twice")
        for n in names:
            if registry.spec(n, cap) is None:
                raise HTTPException(400, f"{n} is not a source of {cap}")
    with db.tx() as c:
        current = db.get_setting("source_priority", c)
        db.set_setting("source_priority", {**current, **body}, c)
        out = _priority(c)
    frames.invalidate()
    return out


@router.get("/sources/coverage")
def coverage(capability: str = "bars") -> list[dict]:
    # capability -> (table, what counts as a "symbol", date column)
    tables = {
        "bars": ("bars", "symbol", "date"),
        "index": ("index_bars", "index_name", "date"),
        "fundamentals": ("fund_snapshots", "symbol", "substr(fetched_at,1,10)"),
        "quarters": ("quarters", "symbol", "period_end"),
    }
    if capability not in tables:
        raise HTTPException(400, f"coverage is available for: {', '.join(tables)}")
    if capability == "bars":
        return frames.memo("sources.coverage.bars", _bars_coverage)
    table, sym, day = tables[capability]
    sql = (
        f"SELECT source, COUNT(DISTINCT {sym}) symbols, MIN({day}) first_date, "
        f"MAX({day}) last_date, COUNT(*) rows FROM {table} GROUP BY source"
    )
    with db.tx() as c:
        return [dict(r) for r in c.execute(sql)]


def _bars_coverage() -> list[dict]:
    """Compact layout (app/bardb.py): source ids and integer days.

    On Vercel counting every bar is too heavy (SPEC §17.5): symbols and dates come from key seeks and
    `rows` from the housekeeping job's count (0 until it has run once)."""
    with db.read() as c:
        if config.RUNTIME != "vercel":
            out = [dict(r) for r in c.execute(bardb.COVERAGE_SQL)]
        else:
            out = [dict(r) for r in c.execute(bardb.COVERAGE_LIGHT_SQL)]
            try:
                counts = db.get_setting(bardb.COVERAGE_KEY, c).get("rows", {})
            except KeyError:
                counts = {}
            for r in out:
                r["rows"] = int(counts.get(r["source"], 0))
    for r in out:
        r["first_date"], r["last_date"] = bardb.iso(r["first_date"]), bardb.iso(r["last_date"])
    return out


def _get(name: str) -> BaseSource:
    try:
        return registry.get(name)
    except KeyError:
        raise HTTPException(404, "source not found") from None


@router.put("/sources/{name}")
def set_enabled(name: str, body: dict[str, bool]) -> dict:
    src = _get(name)
    if "enabled" not in body:
        raise HTTPException(400, "send {enabled: true|false}")
    with db.tx() as c:
        registry.set_enabled(name, body["enabled"], None, c)
        out = _source(c, src)
    frames.invalidate()
    return out


@router.put("/sources/{name}/secrets")
def put_secrets(name: str, body: dict[str, str | None]) -> dict[str, bool]:
    src = _get(name)
    unknown = sorted(set(body) - set(src.secrets))
    if unknown:
        raise HTTPException(400, f"{name} has no secret named: {', '.join(unknown)}")
    for key, value in body.items():
        secrets.set(name, key, value.strip() if value and value.strip() else None)
    return secrets.status(name)
