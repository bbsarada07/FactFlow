"""/api/auth: Sign in with Google, sign out, and who is signed in."""
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from loguru import logger

from api.verify import RateLimiter
from config import settings
from services import auth, google_login, shield_runtime
from services.auth import CurrentUser

router = APIRouter(prefix="/api/auth", tags=["auth"])
login_limiter = RateLimiter(30, noun="sign-in attempts")


def _to_login(error: str) -> RedirectResponse:
    resp = RedirectResponse(f"/login?error={error}", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(google_login.STATE_COOKIE, path="/api/auth")
    return resp


@router.get("/google/login")
async def google_start(request: Request, next: str = Query("/", max_length=500)):  # noqa: A002 - query name
    """Send the browser to Google's account chooser."""
    login_limiter.check(request.client.host if request.client else "unknown")
    try:
        url, cookie = google_login.start(next)
    except google_login.LoginError as exc:
        return _to_login(exc.code)
    resp = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(google_login.STATE_COOKIE, cookie, max_age=google_login.STATE_TTL_SECONDS, httponly=True,
                    secure=auth.cookie_secure(), samesite="lax", path="/api/auth")
    return resp


@router.get("/google/callback")
async def google_callback(request: Request, code: str | None = Query(None, max_length=2048),
                          state: str | None = Query(None, max_length=256), error: str | None = Query(None, max_length=100)):
    """Google redirects here. On success: a new session and a redirect to where the user was going."""
    login_limiter.check(request.client.host if request.client else "unknown")
    if error or not code or not state:
        return _to_login("cancelled" if error else "missing_code")
    try:
        identity, next_path = await google_login.finish(code, state, request.cookies.get(google_login.STATE_COOKIE))
    except google_login.LoginError as exc:
        logger.info(f"sign-in refused: {exc.code}")
        return _to_login(exc.code)
    allowed = auth.email_list(settings.ALLOWED_EMAILS)
    if allowed and identity.email not in allowed:
        return _to_login("not_allowed")
    try:
        user = await auth.upsert_google_user(identity.sub, identity.email, identity.name, identity.picture)
    except PermissionError:
        return _to_login("account_conflict")
    token, csrf = await auth.create_session(user.id, request.headers.get("user-agent"))
    await shield_runtime.audit().append(f"user:{user.email}", "signed_in", {"via": "google"}, user_id=user.id)
    resp = RedirectResponse(next_path, status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(google_login.STATE_COOKIE, path="/api/auth")
    auth.set_session_cookies(resp, token, csrf)
    return resp


@router.get("/me")
async def me(request: Request):
    """The signed-in user and the CSRF token to send with changes; 401 when signed out."""
    user = await auth.optional_user(request)
    if user is None:
        return JSONResponse({"detail": "Not signed in", "google_configured": google_login.configured()},
                            status_code=status.HTTP_401_UNAUTHORIZED)
    from database import connection
    from database.models import User

    async with connection.session_factory()() as s:
        row = await s.get(User, user.id)
    return {"user": row.to_dict(), "csrf_token": user.csrf_token, "via": user.via}


@router.post("/logout")
async def logout(user: CurrentUser = Depends(auth.session_user)):
    """End this browser's session."""
    await auth.end_session(user.session_id)
    await shield_runtime.audit().append(user.actor, "signed_out", {}, user_id=user.id)
    resp = JSONResponse({"signed_out": True})
    auth.clear_session_cookies(resp)
    return resp


@router.post("/logout-everywhere")
async def logout_everywhere(user: CurrentUser = Depends(auth.session_user)):
    """End every session of this user (all browsers)."""
    await auth.end_all_sessions(user.id)
    await shield_runtime.audit().append(user.actor, "signed_out_everywhere", {}, user_id=user.id)
    resp = JSONResponse({"signed_out": True})
    auth.clear_session_cookies(resp)
    return resp
