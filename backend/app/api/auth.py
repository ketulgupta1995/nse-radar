import time

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app import timeutil
from app.cloud import auth

router = APIRouter()

FAIL_DELAY_S = 1.0


class Login(BaseModel):
    password: str


def _set_cookie(resp: Response, value: str, max_age: int) -> None:
    resp.set_cookie(
        auth.COOKIE, value, max_age=max_age, path="/", httponly=True, secure=True, samesite="lax"
    )


@router.post("/login", status_code=204)
def login(body: Login) -> Response:
    if not auth.password_ok(body.password):
        time.sleep(FAIL_DELAY_S)  # slows guessing
        return Response(
            content='{"detail":"wrong password"}', status_code=401, media_type="application/json"
        )
    resp = Response(status_code=204)
    _set_cookie(resp, auth.make_cookie(timeutil.now()), auth.MAX_AGE_S)
    return resp


@router.post("/logout", status_code=204)
def logout() -> Response:
    resp = Response(status_code=204)
    _set_cookie(resp, "", 0)
    return resp


@router.get("/me")
def me(request: Request) -> dict:
    if not auth.required():
        return {"auth_required": False, "logged_in": True}
    return {
        "auth_required": True,
        "logged_in": auth.cookie_ok(request.cookies.get(auth.COOKIE), timeutil.now()),
    }
