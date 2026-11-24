"""Settings API and database backup (SPEC §5)."""

import sqlite3
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from app import config, db, timeutil
from app.analytics import frames
from app.sources import registry

router = APIRouter()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Feed(_Strict):
    name: Annotated[str, Field(min_length=1)]
    url: str

    @field_validator("url")
    @classmethod
    def _http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


class CostModel(_Strict):
    brokerage_pct: Annotated[float, Field(ge=0, le=5)]
    brokerage_cap_inr: Annotated[float, Field(ge=0)]
    stt_pct: Annotated[float, Field(ge=0, le=5)]
    exchange_pct: Annotated[float, Field(ge=0, le=5)]
    sebi_pct: Annotated[float, Field(ge=0, le=5)]
    stamp_buy_pct: Annotated[float, Field(ge=0, le=5)]
    gst_pct: Annotated[float, Field(ge=0, le=100)]
    dp_charge_inr: Annotated[float, Field(ge=0)]
    slippage_pct: Annotated[float, Field(ge=0, le=10)]


Weights = dict[str, Annotated[float, Field(ge=0, le=100)]]
Simple: dict[str, Any] = {
    "capital_inr": Annotated[float, Field(gt=0)],
    "risk_per_trade_pct": Annotated[float, Field(ge=0.1, le=5)],
    "default_time_stop_weeks": Annotated[int, Field(ge=1, le=52)],
    "atr_stop_multiple": Annotated[float, Field(ge=0.5, le=10)],
    "signal_target_atr_multiple": Annotated[float, Field(ge=0.5, le=20)],
    "position_exit_sma": Annotated[int, Field(ge=20, le=300)] | Literal[0],
    "trail_atr_multiple": Annotated[float, Field(ge=1, le=15)] | Literal[0],
    "backtest_workers": Annotated[int, Field(ge=1, le=6)],
    "ai_model": Annotated[str, Field(min_length=1)],
    "ai_timeout_s": Annotated[int, Field(ge=10, le=3600)],
    "score_weights": Weights,
    "rss_feeds": list[Feed],
    "jobs_paused": bool,
    "last_visit_at": str | None,
    "cost_model": CostModel,
}


def _provider(v: Any) -> str:
    if not isinstance(v, str) or not v:
        raise ValueError("must be a non-empty string")
    try:
        from app.ai import base  # type: ignore[attr-defined]
    except ImportError:
        return v
    names = [p.name for p in base.providers()] if hasattr(base, "providers") else None
    if names is not None and v not in names:
        raise ValueError(f"unknown provider (choose from {', '.join(names)})")
    return v


def _source_priority(v: Any) -> dict:
    TypeAdapter(dict[str, list[str]]).validate_python(v)
    for cap, names in v.items():
        if len(set(names)) != len(names):
            raise ValueError(f"{cap}: a source is listed twice")
        for n in names:
            if registry.spec(n, cap) is None:
                raise ValueError(f"{n} is not a source of {cap}")
    return v


def _field_priority(v: Any) -> dict:
    TypeAdapter(dict[str, list[str]]).validate_python(v)
    for field, names in v.items():
        for n in names:
            if n != "quarters" and registry.spec(n, "fundamentals") is None:
                raise ValueError(f"{field}: {n} is not a fundamentals source")
    return v


def _date(v: Any) -> str:
    try:
        if not isinstance(v, str) or date.fromisoformat(v).isoformat() != v:
            raise ValueError
    except ValueError:
        raise ValueError("must be a date like 2022-01-01") from None
    return v


Custom = {
    "holdout_start": _date,
    "ai_provider": _provider,
    "source_priority": _source_priority,
    "fundamentals_field_priority": _field_priority,
}


def _validate(key: str, value: Any) -> Any:
    if key in Custom:
        return Custom[key](value)
    out = TypeAdapter(Simple[key]).validate_python(value)
    if isinstance(out, BaseModel):
        return out.model_dump()
    if isinstance(out, list):
        return [o.model_dump() if isinstance(o, BaseModel) else o for o in out]
    return out


def _all(c: sqlite3.Connection) -> dict:
    return {key: db.get_setting(key, c) for key in db.DEFAULT_SETTINGS}


@router.get("/settings")
def get_settings() -> dict:
    with db.tx() as c:
        return _all(c)


@router.put("/settings")
def put_settings(body: dict[str, Any]) -> dict:
    clean: dict[str, Any] = {}
    for key, value in body.items():
        if key not in db.DEFAULT_SETTINGS:
            raise HTTPException(400, f"{key}: unknown setting")
        try:
            clean[key] = _validate(key, value)
        except (ValueError, ValidationError) as e:
            msg = e.errors()[0]["msg"] if isinstance(e, ValidationError) else str(e)
            raise HTTPException(400, f"{key}: {msg}") from e
    with db.tx() as c:
        for key, value in clean.items():
            db.set_setting(key, value, c)
        out = _all(c)
    if {"source_priority", "fundamentals_field_priority"} & clean.keys():
        frames.invalidate()
    return out


@router.post("/backup")
def backup() -> dict:
    if config.RUNTIME == "vercel":  # no database file here; the cloud worker backs up (SPEC §17.8)
        raise HTTPException(409, "Backups run weekly in the cloud worker")
    dest_dir = config.DATA_DIR / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"stock-{timeutil.now().strftime('%Y%m%d-%H%M')}.db"
    src = sqlite3.connect(config.DB_PATH)
    try:
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    return {"path": str(dest), "size_bytes": dest.stat().st_size}
