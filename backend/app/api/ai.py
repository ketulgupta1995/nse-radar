"""AI API (SPEC §11)."""

import json
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app import db, timeutil
from app.ai import base
from app.jobs import runner

router = APIRouter()
AWAITING = "awaiting_answer"


class RequestIn(BaseModel):
    kind: str
    symbol: str | None = None
    payload: dict | None = None


class AnswerIn(BaseModel):
    text: str


class PromptIn(BaseModel):
    kind: str
    payload: dict | None = None


def _task(kind: str) -> base.AITask:
    try:
        return base.task(kind)
    except KeyError:
        raise HTTPException(404, f"unknown AI task: {kind}") from None


def _build(kind: str, payload: dict) -> str:
    t = _task(kind)
    if t.needs_symbol and not payload.get("symbol"):
        raise HTTPException(400, "this task needs a symbol")
    try:
        return t.build_prompt(payload)
    except base.AIError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/ai/status")
def status() -> dict:
    name = db.get_setting("ai_provider")
    try:
        ok, detail = base.provider(name).available()
    except base.AIError as e:
        ok, detail = False, str(e)
    return {
        "provider": name,
        "available": ok,
        "detail": detail,
        "model": db.get_setting("ai_model"),
        "providers": [{"name": p.name, "label": p.label} for p in base.providers()],
    }


@router.get("/ai/tasks")
def tasks() -> list[dict]:
    return [{"kind": t.kind, "label": t.label, "needs_symbol": t.needs_symbol} for t in base.all_tasks()]


@router.get("/ai/prompt")
def prompt_get(kind: str, symbol: str | None = None) -> dict:
    return {"prompt": _build(kind, {"symbol": symbol} if symbol else {})}


@router.post("/ai/prompt")
def prompt_post(body: PromptIn) -> dict:
    return {"prompt": _build(body.kind, dict(body.payload or {}))}


@router.post("/ai/requests")
def create_request(body: RequestIn) -> dict:
    payload = dict(body.payload or {})
    if body.symbol:
        payload["symbol"] = body.symbol
    prompt = _build(body.kind, payload)
    try:
        prov = base.provider()
    except base.AIError as e:
        raise HTTPException(400, str(e)) from None
    model = db.get_setting("ai_model")  # read before the write transaction opens
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO ai_requests(kind, symbol, payload, prompt, status, provider, model, created_at) "
            "VALUES (?,?,?,?,'queued',?,?,?)",
            (body.kind, body.symbol, json.dumps(payload), prompt, prov.name, model,
             timeutil.now_iso()),
        )  # fmt: skip
        rid = int(cur.lastrowid)
    if _manual(prov.name):
        # SPEC §17.7: no job; the owner pastes Claude's answer into /answer.
        return {"id": rid, "run_id": None, "status": AWAITING, "prompt": prompt}
    run_id = runner.enqueue("ai_request", params={"request_id": rid})
    with db.tx() as c:
        c.execute("UPDATE ai_requests SET run_id=? WHERE id=?", (run_id, rid))
    return {"id": rid, "run_id": run_id}


def _manual(provider_name: str | None) -> bool:
    """True for a provider whose answer the owner pastes in (it never runs as a job)."""
    if not provider_name:
        return False
    try:
        return bool(getattr(base.provider(provider_name), "manual_answer", False))
    except base.AIError:
        return False


def _awaiting(r: sqlite3.Row) -> bool:
    # schema.sql has no 'awaiting_answer' status: it is stored as 'queued' with no run.
    return r["status"] == "queued" and r["run_id"] is None and _manual(r["provider"])


def _row(r: sqlite3.Row, run_status: str | None) -> dict:
    status = AWAITING if _awaiting(r) else r["status"]
    # A run stopped while still queued (or lost in a restart) never reaches the job body.
    if status in ("queued", "running") and run_status in ("cancelled", "interrupted", "failed"):
        status = "cancelled" if run_status == "cancelled" else "failed"
    synthetic = status != r["status"] and status == "failed"
    return {
        "id": r["id"], "kind": r["kind"], "symbol": r["symbol"], "status": status,
        "response": r["response"], "result": json.loads(r["result"]) if r["result"] else None,
        "error": r["error"] or (f"run {run_status}" if synthetic else None),
        "duration_s": r["duration_s"], "provider": r["provider"], "model": r["model"],
        "run_id": r["run_id"], "created_at": r["created_at"],
    }  # fmt: skip


_SELECT = (
    "SELECT a.*, j.status AS run_status FROM ai_requests a LEFT JOIN job_runs j ON j.id = a.run_id"
)


@router.get("/ai/requests/{request_id}")
def get_request(request_id: int) -> dict:
    with db.tx() as c:
        r = c.execute(_SELECT + " WHERE a.id=?", (request_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such AI request")
    return _row(r, r["run_status"])


def _parse_answer(kind: str, text: str, payload: dict) -> tuple[str, dict | None, str | None]:
    """Run the task's postprocess on a pasted answer, like the ai_request job does."""
    try:
        post = base.task(kind).postprocess
        result = post(text, payload) if post else None
    except (base.AIError, KeyError) as e:
        return "failed", None, str(e)
    return "done", result, None


@router.post("/ai/requests/{request_id}/answer")
def answer_request(request_id: int, body: AnswerIn) -> dict:
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "paste Claude's answer first")
    with db.tx() as c:
        r = c.execute("SELECT * FROM ai_requests WHERE id=?", (request_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such AI request")
    # A pasted answer may replace an earlier one, but never a job-run request.
    if r["run_id"] is not None or not _manual(r["provider"]):
        raise HTTPException(409, "this request was sent to Claude by a job, not pasted")
    status, result, error = _parse_answer(r["kind"], text, json.loads(r["payload"] or "{}"))
    with db.tx() as c:
        c.execute(
            "UPDATE ai_requests SET status=?, response=?, result=?, error=? WHERE id=?",
            (status, text, json.dumps(result) if result is not None else None, error, request_id),
        )
    return get_request(request_id)


@router.get("/ai/requests")
def list_requests(
    symbol: str | None = None, kind: str | None = None, limit: int = Query(20, ge=1, le=200)
) -> list[dict]:
    where, args = [], []
    if symbol:
        where.append("a.symbol=?")
        args.append(symbol)
    if kind:
        where.append("a.kind=?")
        args.append(kind)
    sql = _SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY a.id DESC LIMIT ?"
    with db.tx() as c:
        rows = c.execute(sql, (*args, limit)).fetchall()
    return [_row(r, r["run_status"]) for r in rows]
