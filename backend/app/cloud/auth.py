"""Password gate for the public deployment (SPEC §17.5).

When env `APP_PASSWORD` is set, every `/api/*` path except the exempt ones needs the
`nr_session` cookie = `<expiry>.<hmac_sha256(APP_SECRET, expiry)>`. Unset: the gate is off.
"""

import hashlib
import hmac
import logging
import os
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import timeutil

log = logging.getLogger(__name__)

COOKIE = "nr_session"
MAX_AGE_S = 90 * 24 * 3600
EXEMPT = frozenset({"/api/health", "/api/login", "/api/me"})


def password() -> str:
    return os.environ.get("APP_PASSWORD", "")


def required() -> bool:
    return bool(password())


def _secret() -> bytes:
    # APP_SECRET should always be set alongside APP_PASSWORD; fall back to the password so the
    # cookie is never signed with an empty key.
    return (os.environ.get("APP_SECRET") or password()).encode()


def _sign(expiry: str) -> str:
    return hmac.new(_secret(), expiry.encode(), hashlib.sha256).hexdigest()


def make_cookie(now: datetime) -> str:
    expiry = str(int(now.timestamp()) + MAX_AGE_S)
    return f"{expiry}.{_sign(expiry)}"


def cookie_ok(value: str | None, now: datetime) -> bool:
    if not value or "." not in value:
        return False
    expiry, sig = value.split(".", 1)
    if not expiry.isdigit():
        return False
    if not hmac.compare_digest(sig.encode(), _sign(expiry).encode()):
        return False
    return int(expiry) > now.timestamp()


def password_ok(given: str) -> bool:
    return required() and hmac.compare_digest(given.encode(), password().encode())


def _gated(path: str) -> bool:
    return (path == "/api" or path.startswith("/api/")) and path not in EXEMPT


def install(app: FastAPI) -> None:
    """Add the gate middleware. A no-op per request while `APP_PASSWORD` is unset."""

    @app.middleware("http")
    async def password_gate(request: Request, call_next):
        if required() and _gated(request.url.path):
            if not cookie_ok(request.cookies.get(COOKIE), timeutil.now()):
                return JSONResponse({"detail": "login required"}, status_code=401)
        return await call_next(request)
