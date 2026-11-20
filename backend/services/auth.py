"""Accounts: sessions, CSRF protection, extension tokens and the `current_user` dependency.

* A session is a random 256-bit value in an HttpOnly, SameSite=Lax cookie (`ff_session`); only its SHA-256 is
  stored, so a database leak does not hand out sessions. Sessions last SESSION_DAYS.
* Requests that change something (POST/PUT/PATCH/DELETE) with a session cookie must also send the session's
  CSRF token in `X-CSRF-Token`. The token is readable by the page (from /api/auth/me and the `ff_csrf` cookie),
  never by another site.
* The browser extension sends `Authorization: Bearer ffx_...` instead: a personal token whose SHA-256 is stored
  and which the user can revoke. Bearer requests need no CSRF token (nothing is sent automatically).
* Every route that touches user data depends on `current_user` and filters by `user.id`.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import delete, select, update

from config import settings
from database import connection
from database.models import ApiToken, User, UserSession, utcnow

SESSION_COOKIE = "ff_session"
CSRF_COOKIE = "ff_csrf"
CSRF_HEADER = "x-csrf-token"
EXTENSION_PREFIX = "ffx_"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
TOUCH_EVERY = timedelta(minutes=5)


@dataclass(frozen=True)
class CurrentUser:
    """The signed-in person for this request."""

    id: str
    email: str
    name: str | None
    role: str
    via: str  # session | extension
    session_id: str | None = None
    csrf_token: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def actor(self) -> str:
        """How this person appears in the audit log."""
        return f"user:{self.email}"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def email_list(raw: str) -> set[str]:
    return {e.strip().lower() for e in (raw or "").split(",") if e.strip()}


def cookie_secure() -> bool:
    """Secure cookies everywhere except plain-http local development."""
    return settings.ENVIRONMENT.lower() == "production" or settings.FRONTEND_URL.lower().startswith("https://")


# ------------------------------------------------------------------------------------------- sessions


async def create_session(user_id: str, user_agent: str | None) -> tuple[str, str]:
    """Start a session. Returns (cookie value, csrf token); only hashes and the csrf token are stored."""
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = utcnow()
    async with connection.session_factory()() as s:
        s.add(UserSession(id=_sha(token), user_id=user_id, csrf_token=csrf, created_at=now, last_seen_at=now,
                          expires_at=now + timedelta(days=settings.SESSION_DAYS),
                          user_agent=(user_agent or "")[:200] or None))
        # housekeeping: drop this user's expired sessions
        await s.execute(delete(UserSession).where(UserSession.user_id == user_id, UserSession.expires_at < now))
        await s.commit()
    return token, csrf


def set_session_cookies(response: Response, token: str, csrf: str) -> None:
    max_age = settings.SESSION_DAYS * 86400
    secure = cookie_secure()
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=secure, samesite="lax", path="/")
    # Readable by the page on purpose: the page echoes it in X-CSRF-Token. Useless to other sites.
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=secure, samesite="lax", path="/")


def clear_session_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=cookie_secure(), samesite="lax")


async def end_session(session_id: str) -> None:
    async with connection.session_factory()() as s:
        await s.execute(delete(UserSession).where(UserSession.id == session_id))
        await s.commit()


async def end_all_sessions(user_id: str) -> None:
    async with connection.session_factory()() as s:
        await s.execute(delete(UserSession).where(UserSession.user_id == user_id))
        await s.commit()


# ------------------------------------------------------------------------------------ extension tokens


async def create_extension_token(user_id: str, label: str = "Browser extension") -> tuple[ApiToken, str]:
    """A new personal extension token. The plain value is returned once and never stored."""
    token = EXTENSION_PREFIX + secrets.token_urlsafe(32)
    async with connection.session_factory()() as s:
        row = ApiToken(token_hash=_sha(token), user_id=user_id, kind="extension", label=label[:100],
                       prefix=token[:10])
        s.add(row)
        await s.commit()
        await s.refresh(row)
    return row, token


async def list_extension_tokens(user_id: str) -> list[dict]:
    async with connection.session_factory()() as s:
        rows = (await s.scalars(select(ApiToken).where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
                                .order_by(ApiToken.created_at.desc()))).all()
        return [r.to_dict() for r in rows]


async def revoke_extension_token(user_id: str, token_id: str) -> bool:
    async with connection.session_factory()() as s:
        res = await s.execute(update(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user_id,
                                                     ApiToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
        await s.commit()
        return res.rowcount == 1


# --------------------------------------------------------------------------------------- dependencies


def _unauthorized(detail: str = "Sign in to continue.") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail)


async def _from_session(request: Request, cookie: str) -> CurrentUser | None:
    now = utcnow()
    async with connection.session_factory()() as s:
        row = await s.get(UserSession, _sha(cookie))
        if row is None or _aware(row.expires_at) <= now:
            return None
        user = await s.get(User, row.user_id)
        if user is None:
            return None
        if row.last_seen_at is None or now - _aware(row.last_seen_at) > TOUCH_EVERY:
            row.last_seen_at = now
            await s.commit()
        if request.method in UNSAFE_METHODS:
            sent = request.headers.get(CSRF_HEADER, "")
            if not sent or not hmac.compare_digest(sent.encode(), row.csrf_token.encode()):
                raise HTTPException(status.HTTP_403_FORBIDDEN,
                                    "Missing or wrong CSRF token. Reload the page and try again.")
        return CurrentUser(user.id, user.email, user.name, user.role, "session", row.id, row.csrf_token)


async def _from_bearer(token: str) -> CurrentUser | None:
    if not token.startswith(EXTENSION_PREFIX):
        return None
    async with connection.session_factory()() as s:
        row = await s.scalar(select(ApiToken).where(ApiToken.token_hash == _sha(token), ApiToken.revoked_at.is_(None)))
        if row is None:
            return None
        user = await s.get(User, row.user_id)
        if user is None:
            return None
        now = utcnow()
        if row.last_used_at is None or now - _aware(row.last_used_at) > TOUCH_EVERY:
            row.last_used_at = now
            await s.commit()
        return CurrentUser(user.id, user.email, user.name, user.role, "extension")


async def optional_user(request: Request) -> CurrentUser | None:
    """The signed-in user, or None. Raises 403 for a session request without its CSRF token."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return await _from_bearer(auth[7:].strip())
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return await _from_session(request, cookie)
    return None


async def current_user(request: Request) -> CurrentUser:
    """FastAPI dependency: the signed-in user (401 otherwise)."""
    user = await optional_user(request)
    if user is None:
        raise _unauthorized()
    return user


async def require_admin(request: Request) -> CurrentUser:
    user = await current_user(request)
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can do this.")
    return user


async def session_user(request: Request) -> CurrentUser:
    """Like current_user, but only a browser session (not an extension token) is accepted."""
    user = await current_user(request)
    if user.via != "session":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Do this from the FactFlow website.")
    return user


# -------------------------------------------------------------------------------------------- users


async def upsert_google_user(sub: str, email: str, name: str | None, picture: str | None) -> User:
    """Find or create the user for a verified Google identity; admins come from ADMIN_EMAILS."""
    email = email.strip().lower()
    role = "admin" if email in email_list(settings.ADMIN_EMAILS) else "user"
    now = utcnow()
    async with connection.session_factory()() as s:
        user = await s.scalar(select(User).where(User.google_sub == sub))
        if user is None:
            user = await s.scalar(select(User).where(User.email == email))
            if user is not None and user.google_sub != sub:
                # Same address, different Google account (e.g. deleted and recreated): refuse rather than merge.
                raise PermissionError("This email is already linked to a different Google account.")
        if user is None:
            user = User(google_sub=sub, email=email, created_at=now)
            s.add(user)
        user.email, user.name, user.picture_url = email, (name or "")[:200] or None, (picture or "")[:2000] or None
        user.role, user.last_login_at = role, now
        await s.commit()
        await s.refresh(user)
        return user
