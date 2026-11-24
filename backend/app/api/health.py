from fastapi import APIRouter

from app import timeutil

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"ok": True, "time": timeutil.now_iso(), "version": "0.1.0"}
