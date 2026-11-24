"""Signal log and track-record summary endpoints (SPEC §16.5)."""

import json

from fastapi import APIRouter

from app import db
from app.analytics import frames
from app.signals import ideas

router = APIRouter()

MIN_CLOSED = 30
OUTCOME_COLS = (
    "status", "entry_date", "entry_fill", "gap_pct", "exit_date", "exit_fill", "exit_reason",
    "days_held", "return_pct", "r_multiple", "mfe_r", "mae_r", "excess_pct",
)  # fmt: skip


def _reasons(raw: str | None) -> list:
    try:
        v = json.loads(raw or "[]")
    except ValueError:
        return []
    return v if isinstance(v, list) else []


def _row(r: dict) -> dict:
    outcome = None
    if r["o_status"] is not None:
        outcome = {k: r["o_" + k] for k in OUTCOME_COLS}
    return {
        "id": r["id"], "source": r["source"], "screen_id": r["screen_id"],
        "screen_name": r["screen_name"], "symbol": r["symbol"], "name": r["name"],
        "as_of": r["as_of"], "rank": r["rank"], "score": r["score"],
        "reasons": _reasons(r["reasons"]), "planned_entry": r["planned_entry"],
        "planned_stop": r["planned_stop"], "planned_target": r["planned_target"],
        "app_version": r["app_version"], "outcome": outcome,
    }  # fmt: skip


@router.get("/signals")
def list_signals(
    source: str | None = None,
    screen_id: int | None = None,
    status: str | None = None,
    symbol: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    where, args = [], []
    for col, val in (("g.source", source), ("g.screen_id", screen_id), ("o.status", status)):
        if val is not None:
            where.append(f"{col} = ?")
            args.append(val)
    if symbol:
        where.append("g.symbol = ?")
        args.append(symbol.strip().upper())
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    base = (
        "FROM signals g LEFT JOIN signal_outcomes o ON o.signal_id = g.id "
        "LEFT JOIN symbols s ON s.symbol = g.symbol" + clause
    )
    cols = ", ".join(f"o.{k} AS o_{k}" for k in OUTCOME_COLS)
    with db.read() as c:
        total = c.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
        rows = c.execute(
            f"SELECT g.*, s.name AS name, {cols} {base} "
            "ORDER BY g.as_of DESC, g.id DESC LIMIT ? OFFSET ?",
            [*args, max(limit, 0), max(offset, 0)],
        ).fetchall()
    out = [_row(dict(r)) for r in rows]
    _add_prices(out)
    return {"total": total, "rows": out}


def _add_prices(rows: list[dict]) -> None:
    """`current_price` = latest close, from batched key seeks rather than one frame per stock (§17.5)."""
    last = frames.latest_closes({r["symbol"] for r in rows})
    for r in rows:
        r["current_price"] = last.get(r["symbol"])


def _mean(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None


def _group(key: str, label: str, kind: str, sigs: list[dict]) -> dict:
    closed = [s for s in sigs if s["status"] == "closed"]

    def avg(col: str) -> float | None:
        return _mean([s[col] for s in closed if s[col] is not None])

    wins = sum(1 for s in closed if (s["return_pct"] or 0) > 0)
    return {
        "key": key, "label": label, "kind": kind,
        "n_closed": len(closed),
        "n_open": sum(1 for s in sigs if s["status"] == "open"),
        "n_pending": sum(1 for s in sigs if s["status"] == "pending"),
        "hit_rate_pct": round(wins / len(closed) * 100, 2) if closed else None,
        "avg_return_pct": avg("return_pct"), "avg_r": avg("r_multiple"),
        "avg_excess_pct": avg("excess_pct"), "avg_days": avg("days_held"),
        "enough": len(closed) >= MIN_CLOSED,
    }  # fmt: skip


def _coverage(c) -> dict:
    d = c.execute("SELECT MIN(as_of) lo, MAX(as_of) hi, COUNT(*) n FROM signal_days").fetchone()
    first, last = d["lo"], d["hi"]
    trading = 0
    if first and last:
        bench = frames.load_benchmark()
        trading = int(sum(1 for t in bench.index if first <= t.date().isoformat() <= last))
    return {"first_day": first, "last_day": last, "days_logged": d["n"], "trading_days": trading}


def _all_loggings(c) -> list[dict]:
    """Every logging with its outcome columns (prefixed `o_`) and the company name, oldest first."""
    cols = ", ".join(f"o.{k} AS o_{k}" for k in OUTCOME_COLS)
    rows = c.execute(
        f"SELECT g.id, g.source, g.screen_id, g.screen_name, g.symbol, g.as_of, g.rank, g.score, "
        f"g.reasons, g.planned_entry, g.planned_stop, g.planned_target, s.name AS name, {cols} "
        "FROM signals g LEFT JOIN signal_outcomes o ON o.signal_id = g.id "
        "LEFT JOIN symbols s ON s.symbol = g.symbol ORDER BY g.as_of, g.id"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["status"] = d["o_status"] or "pending"
        d["exit_date"] = d["o_exit_date"]
        out.append(d)
    return out


def _idea_stats(idea: dict) -> dict:
    """The anchor's outcome, which is what the idea is graded on."""
    a = idea["anchor"]
    return {"status": a["status"], "return_pct": a["o_return_pct"], "r_multiple": a["o_r_multiple"],
            "excess_pct": a["o_excess_pct"], "days_held": a["o_days_held"]}  # fmt: skip


@router.get("/signals/summary")
def summary() -> dict:
    with db.read() as c:
        sigs = _all_loggings(c)
        coverage = _coverage(c)
    grouped = ideas.group_ideas(sigs)

    groups: list[dict] = []
    screens: dict[int, list[dict]] = {}
    labels: dict[int, str | None] = {}
    for s in sigs:  # oldest first, so the last name seen is the newest
        if s["source"] == "screen":
            labels[s["screen_id"]] = s["screen_name"]
    for idea in grouped:
        stats = _idea_stats(idea)
        for sid in {m["screen_id"] for m in idea["members"] if m["source"] == "screen"}:
            screens.setdefault(sid, []).append(stats)
    for sid in sorted(screens):
        groups.append(_group(f"screen:{sid}", labels.get(sid) or f"Screen {sid}", "screen", screens[sid]))

    ranked = [(ideas.best_rank(i["members"]), _idea_stats(i)) for i in grouped]
    groups.append(_group("shortlist:rank1-3", "Shortlist #1–3", "rank",
                         [s for rk, s in ranked if rk is not None and rk <= 3]))  # fmt: skip
    groups.append(_group("shortlist:rank4-10", "Shortlist #4–10", "rank",
                         [s for rk, s in ranked if rk is not None and 4 <= rk <= 10]))  # fmt: skip

    scored = [(ideas.best_score(i["members"]), _idea_stats(i)) for i in grouped]
    scored = [(sc, s) for sc, s in scored if sc is not None]
    groups.append(_group("band:75+", "Score 75+", "band", [s for sc, s in scored if sc >= 75]))
    groups.append(_group("band:60-75", "Score 60–75", "band",
                         [s for sc, s in scored if 60 <= sc < 75]))  # fmt: skip
    groups.append(_group("band:<60", "Score under 60", "band", [s for sc, s in scored if sc < 60]))
    return {"groups": groups, "coverage": coverage, "min_closed": MIN_CLOSED,
            "n_signals": len(sigs), "n_ideas": len(grouped)}  # fmt: skip


def _idea_row(idea: dict) -> dict:
    a, members = idea["anchor"], idea["members"]
    outcome = {k: a["o_" + k] for k in OUTCOME_COLS} if a["o_status"] is not None else None
    return {
        "id": a["id"], "symbol": a["symbol"], "name": a["name"],
        "first_as_of": a["as_of"], "last_as_of": members[-1]["as_of"],
        "score": ideas.best_score(members), "reasons": ideas.merged_reasons(members),
        "planned_entry": a["planned_entry"], "planned_stop": a["planned_stop"],
        "planned_target": a["planned_target"],
        "seen": [{"signal_id": m["id"], "as_of": m["as_of"], "source": m["source"],
                  "screen_id": m["screen_id"], "screen_name": m["screen_name"], "rank": m["rank"],
                  "score": m["score"]} for m in members],
        "outcome": outcome,
    }  # fmt: skip


def _status(row: dict) -> str:
    return row["outcome"]["status"] if row["outcome"] else "pending"


@router.get("/signals/ideas")
def list_ideas(
    status: str | None = None,
    source: str | None = None,
    screen_id: int | None = None,
    q: str | None = None,
    since: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    with db.read() as c:
        rows = [_idea_row(i) for i in ideas.group_ideas(_all_loggings(c))]

    needle = (q or "").strip().lower()

    def keep(r: dict) -> bool:
        if source and not any(s["source"] == source for s in r["seen"]):
            return False
        if screen_id is not None and not any(
            s["source"] == "screen" and s["screen_id"] == screen_id for s in r["seen"]
        ):
            return False
        if needle and needle not in r["symbol"].lower() and needle not in (r["name"] or "").lower():
            return False
        return not since or r["last_as_of"] >= since

    rows = [r for r in rows if keep(r)]
    counts = {k: 0 for k in ("open", "pending", "closed", "no_data")}
    for r in rows:
        counts[_status(r)] = counts.get(_status(r), 0) + 1
    if status:
        rows = [r for r in rows if _status(r) == status]

    if status == "closed":
        rows.sort(key=lambda r: (r["outcome"]["exit_date"] or "", r["id"]), reverse=True)
    else:
        rows.sort(key=lambda r: (r["first_as_of"], r["id"]), reverse=True)
    page = rows[max(offset, 0) : max(offset, 0) + max(limit, 0)]
    _add_prices(page)
    return {"total": len(rows), "counts": counts, "rows": page}
