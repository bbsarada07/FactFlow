"""OPERATOR_TOKEN check for routes that change state or expose other people's data (DECISIONS D6).

The token is sent in the `X-Operator-Token` header. The frontend keeps it in sessionStorage after
the operator types it; it is never built into the frontend bundle. Comparison is constant-time,
and an address with too many wrong tokens in a minute is refused (429) even with the right one,
until the minute passes. With no OPERATOR_TOKEN configured, these routes are closed (503).
"""
import hmac

from fastapi import Header, HTTPException, Request, status

from api.verify import RateLimiter
from config import settings

failures = RateLimiter(settings.OPERATOR_FAILURES_PER_MINUTE, noun="failed operator-token attempts")


def require_operator(request: Request, x_operator_token: str | None = Header(default=None)) -> str:
    """FastAPI dependency. Returns the actor name used in the audit log."""
    configured = settings.OPERATOR_TOKEN
    if not configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "This action needs OPERATOR_TOKEN to be set on the server.")
    key = request.client.host if request.client else "unknown"
    blocked = failures.blocked(key)
    if blocked:
        raise blocked
    if not x_operator_token or not hmac.compare_digest(x_operator_token.encode(), configured.encode()):
        failures.check(key)  # records the failure; raises 429 once the limit is reached
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or wrong operator token.",
                            headers={"WWW-Authenticate": "X-Operator-Token"})
    return "operator"
