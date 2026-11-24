from datetime import date, datetime

from app.config import TZ


def now() -> datetime:
    return datetime.now(TZ)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def today() -> date:
    return now().date()
