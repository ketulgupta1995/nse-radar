# N008: Password gate (backend + login page)
Cloud · Depends on: N007 · Model: sonnet

## Goal
The public URL shows nothing without the owner's password (SPEC §17.5 "Password gate").

## Read first
SPEC §17.5, `backend/app/main.py`, `frontend/src/api/client.ts`, `frontend/src/routes.tsx`, `frontend/src/App.tsx`

## Files
- `backend/app/cloud/auth.py` (new): `make_cookie(now) -> str`, `cookie_ok(value, now) -> bool` (HMAC-SHA256 with `APP_SECRET`, `hmac.compare_digest`, expiry check) and a FastAPI middleware `install(app)`, called from `main.py` (core wiring, allowed here). The middleware is a no-op when `APP_PASSWORD` is unset.
- `backend/app/api/auth.py` (new): `POST /api/login`, `POST /api/logout`, `GET /api/me` → `{"auth_required": bool, "logged_in": bool}` (exempt from the gate). After a failed login, wait 1 s before answering.
- `frontend/src/pages/Login.tsx` (new): one password field + button, plain error text, then redirect to where the user was going. The route is outside the shell layout and not in the nav.
- `frontend/src/api/client.ts`: on 401 with `login required`, go to `/login?next=<path>`.
- Settings page: a "Log out" button, shown only when `auth_required`.
- Tests: backend (`test_auth.py`): gate off without the env; 401 without the cookie; a bad password gets 401; a good one sets the cookie with the right flags; an expired or tampered cookie fails; health/login/me are exempt. Frontend: the login page submits and redirects; the client redirects on 401.

## Notes for the planner
