from fastapi import APIRouter

from app import config, db, timeutil

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "time": timeutil.now_iso(),
        "version": "0.1.0",
        "runtime": config.RUNTIME,
        "schema": db.schema_status(),
    }
