"""/api/mail: the read-only mail provider and the mail agent (operator token required).

The only public route is the OAuth callback: Google's redirect cannot carry the operator header,
so it is protected by the single-use, 10-minute `state` value that only an operator-started
connect request creates (plus PKCE and a rate limit).
"""
import base64
import binascii
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.verify import RateLimiter
from config import settings
from services import gmail_account, llm_status, mail_agent, runtime_settings, shield_runtime
from services.operator_auth import require_operator
from shield.email_parser import MAX_BYTES
from shield.providers.base import ProviderAuthError, ProviderTemporaryError, RawMessageRef
from shield.providers.gmail import GMAIL_READONLY_SCOPE, ScopeError

router = APIRouter(prefix="/api/mail", tags=["mail"])
callback_limiter = RateLimiter(20, noun="Gmail connection attempts")


class ProviderRequest(BaseModel):
    provider: Literal["auto", "gmail", "eml"]


class SyncRequest(BaseModel):
    mode: Literal["full", "rules"] = "full"


class UploadRequest(BaseModel):
    raw: str | None = Field(default=None, max_length=MAX_BYTES + 1)
    eml_base64: str | None = Field(default=None, max_length=(MAX_BYTES // 3 + 1) * 4 + 4)
    mode: Literal["full", "rules"] = "full"


class StepRequest(BaseModel):
    task: Literal["extract_action_items", "draft_reply", "propose_calendar_event", "propose_forward",
                  "propose_share_data", "propose_open_link", "report_phishing", "quarantine_email"]
    target: str | None = Field(default=None, max_length=500, description="recipient address or URL, typed by the user")


def _use_llm(mode: str) -> bool:
    return mode == "full" and settings.INBOX_USE_LLM


@router.get("/status")
async def mail_status(_actor: str = Depends(require_operator)):
    """Which inbox the agent reads, the Gmail connection, and whether the AI part is available."""
    name, _ = await mail_agent.active_provider()
    remaining = llm_status.breaker.remaining()
    return {
        "active_provider": name, "provider_setting": mail_agent._active["provider"],
        "gmail": await gmail_account.status(),
        "demo_inbox": {"messages": len(await mail_agent.eml_provider().list_new(None))},
        "poll_seconds": settings.MAIL_POLL_SECONDS, "poll_enabled": settings.MAIL_POLL_ENABLED,
        "llm": {"state": "quota_exhausted" if remaining else ("ok" if settings.INBOX_USE_LLM else "disabled"),
                "retry_after_seconds": remaining or None},
    }


@router.put("/provider")
async def set_provider(body: ProviderRequest, actor: str = Depends(require_operator)):
    """Choose the inbox: 'gmail' (live), 'eml' (demo inbox) or 'auto' (Gmail when connected). The choice is saved
    so it survives a restart."""
    try:
        await runtime_settings.save(runtime_settings.MAIL_PROVIDER, body.provider, f"human:{actor}")
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "The provider choice could not be saved, so it was not changed. Try again.") from None
    mail_agent.set_active(body.provider)
    await shield_runtime.audit().append(f"human:{actor}", "mail_provider_changed", {"provider": body.provider})
    return await mail_status(actor)


@router.post("/gmail/connect")
async def gmail_connect(_actor: str = Depends(require_operator)):
    """Start the Google consent flow (gmail.readonly only). Send the browser to `auth_url`."""
    try:
        url = gmail_account.start_connect()
    except gmail_account.GmailSetupError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    return {"auth_url": url, "scope": GMAIL_READONLY_SCOPE, "expires_in": gmail_account.STATE_TTL_SECONDS,
            "warning": "Connect only a throwaway test Gmail account, never a personal or work inbox."}


def _back(result: str, reason: str | None = None) -> RedirectResponse:
    url = f"{settings.FRONTEND_URL.rstrip('/')}/inbox?gmail={result}" + (f"&reason={reason}" if reason else "")
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/gmail/callback")
async def gmail_callback(request: Request, code: str | None = Query(default=None, max_length=2048),
                         state: str | None = Query(default=None, max_length=256),
                         error: str | None = Query(default=None, max_length=100)):
    """Google redirects here after consent; we redirect back to the frontend's inbox page."""
    callback_limiter.check(request.client.host if request.client else "unknown")
    if error or not code or not state:
        return _back("error", "denied" if error else "missing_code")
    try:
        await gmail_account.finish_connect(state, code)
    except ScopeError:
        return _back("error", "scope_not_allowed")
    except gmail_account.GmailSetupError:
        return _back("error", "not_configured")
    except ProviderTemporaryError:
        return _back("error", "google_unreachable")
    except ProviderAuthError:
        return _back("error", "auth_failed")
    return _back("connected")


@router.post("/gmail/disconnect")
async def gmail_disconnect(_actor: str = Depends(require_operator)):
    """Revoke the token at Google and delete it here."""
    return await gmail_account.disconnect()


@router.post("/sync")
async def sync_now(body: SyncRequest | None = None, _actor: str = Depends(require_operator)):
    """Fetch and process new mail from the active inbox now (the poller also does this for Gmail)."""
    name, provider = await mail_agent.active_provider()
    if provider is None:
        status_ = await gmail_account.status()
        raise HTTPException(status.HTTP_409_CONFLICT, "Gmail is not connected" + (
            " (reconnect required)" if status_["reconnect_required"] else ""))
    report = await mail_agent.sync(provider, use_llm=_use_llm((body or SyncRequest()).mode))
    return report.model_dump()


@router.post("/upload")
async def upload(body: UploadRequest, _actor: str = Depends(require_operator)):
    """Give the mail agent an .eml file or pasted message (demo inbox); returns its task."""
    if body.eml_base64:
        try:
            data = base64.b64decode(body.eml_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "eml_base64 is not valid base64") from None
    elif body.raw and body.raw.strip():
        data = body.raw.encode("utf-8")
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Provide raw or eml_base64")
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Email is larger than 5 MB")
    eml = mail_agent.eml_provider()
    message_id = eml.add(data)
    task_id = await mail_agent.process(eml, RawMessageRef("eml", message_id), source="upload", use_llm=_use_llm(body.mode))
    if task_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This message was already given to the agent")
    return await mail_agent.task_view(task_id)


@router.get("/tasks")
async def tasks(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
                state: str | None = Query(default=None, max_length=24), _actor: str = Depends(require_operator)):
    return await mail_agent.list_tasks(limit, offset, state)


@router.get("/tasks/{task_id}")
async def task(task_id: str, _actor: str = Depends(require_operator)):
    view = await mail_agent.task_view(task_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown task")
    return view


@router.post("/tasks/{task_id}/steps")
async def add_step(task_id: str, body: StepRequest, actor: str = Depends(require_operator)):
    """Ask the agent to do something with an analysed message (for example forward it). The step is
    policy-checked like any other; outgoing steps only ever reach the simulated outbox."""
    try:
        return await mail_agent.request_step(task_id, body.task, body.target, actor)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown task") from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.get("/outbox")
async def simulated_outbox(limit: int = Query(50, ge=1, le=200), _actor: str = Depends(require_operator)):
    """Everything the agent 'sent': simulated only. Nothing here left FactFlow."""
    return {"simulated": True, "items": await mail_agent.outbox(limit)}


@router.delete("/outbox")
@router.post("/outbox/clear")
async def clear_outbox(_actor: str = Depends(require_operator)):
    """Clear the simulated outbox."""
    from shield.sandbox_agent import clear_simulated_outbox
    cleared = await clear_simulated_outbox()
    return {"simulated": True, "cleared": cleared}
