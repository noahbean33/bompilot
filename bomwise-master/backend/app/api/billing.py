"""
Billing API endpoints — Paddle Billing integration + internal trial provisioning.

All routes except /webhooks and /internal/* require authentication.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import secrets
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db, settings
from app.core.security import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


# ---------------------------------------------------------------------------
# Internal provisioning endpoint (secured by shared secret header)
# ---------------------------------------------------------------------------

INTERNAL_TOKEN = getattr(settings, "internal_provisioning_token", "")


def _verify_internal_token(x_internal_token: str | None) -> None:
    """Raise 401 if the internal provisioning token is missing or wrong."""
    if not INTERNAL_TOKEN or not x_internal_token or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing internal token")


class ProvisionTrialRequest(BaseModel):
    email: str
    full_name: str | None = None
    trial_days: int = 60
    source: str | None = None


class ProvisionTrialResponse(BaseModel):
    status: str  # "created" | "upgraded" | "already_pro"
    email: str
    trial_ends_at: datetime | None


@router.post("/internal/provision-trial", response_model=ProvisionTrialResponse)
async def provision_trial(
    body: ProvisionTrialRequest,
    x_internal_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ProvisionTrialResponse:
    """
    Internal endpoint — provisions a 60-day Pro trial for the given email.
    Secured by X-Internal-Token header.

    Upsert logic:
    - New user → create account with Pro trial, send password-set email
    - Existing free → upgrade to Pro trial, send trial-activated email
    - Existing pro → return already_pro, no changes
    """
    _verify_internal_token(x_internal_token)

    existing = db.query(User).filter(User.email == body.email).first()
    trial_ends_at = datetime.now(UTC) + timedelta(days=body.trial_days)

    # --- Already trial provisioned (even if later downgraded to free): no-op ---
    if existing and existing.is_trial_provisioned:
        return ProvisionTrialResponse(
            status="already_trial",
            email=body.email,
            trial_ends_at=existing.trial_ends_at,
        )

    # --- Existing pro: no-op ---
    if existing and existing.subscription_tier == "pro" and existing.plan == "paid":
        return ProvisionTrialResponse(
            status="already_pro",
            email=body.email,
            trial_ends_at=existing.trial_ends_at,
        )

    # --- New user: create ---
    if existing is None:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(hours=24)

        from app.models.password_reset_token import PasswordResetToken

        db_user = User(
            email=body.email,
            hashed_password="",  # no password yet — user will set via reset link
            plan="paid",
            subscription_tier="pro",
            subscription_status="active",
            trial_ends_at=trial_ends_at,
            is_trial_provisioned=True,
            trial_source=body.source,
            email_verified_at=datetime.now(UTC),  # trust email from n8n workflow
        )
        if body.full_name:
            db_user.name = body.full_name
        db.add(db_user)
        db.flush()

        # Create a password-reset token so user can set their password
        db.add(PasswordResetToken(
            user_id=db_user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        ))
        db.commit()
        db.refresh(db_user)

        # Send password-set email
        _send_password_set_email(body.email, raw_token, trial_ends_at)

        return ProvisionTrialResponse(
            status="created",
            email=body.email,
            trial_ends_at=db_user.trial_ends_at,
        )

    # --- Existing free user: upgrade ---
    existing.plan = "paid"
    existing.subscription_tier = "pro"
    existing.subscription_status = "active"
    existing.trial_ends_at = trial_ends_at
    existing.is_trial_provisioned = True
    existing.trial_source = body.source
    if body.full_name and not existing.name:
        existing.name = body.full_name
    db.commit()
    db.refresh(existing)

    _send_trial_activated_email(body.email, trial_ends_at)

    return ProvisionTrialResponse(
        status="upgraded",
        email=body.email,
        trial_ends_at=existing.trial_ends_at,
    )


def _send_password_set_email(email: str, raw_token: str, trial_ends_at: datetime) -> None:
    """Send password-set email for new trial user."""
    from app.worker.email import _send_smtp
    from app.worker.email.template_renderer import render_template

    base_url = getattr(settings, "app_base_url", "http://localhost:5173")
    reset_link = f"{base_url}/reset-password?token={raw_token}"
    expiry_str = trial_ends_at.strftime("%Y-%m-%d")

    subject, body = render_template(
        "password_set",
        trial_end_date=expiry_str,
        reset_link=reset_link,
    )
    try:
        _send_smtp(email, subject, body)
        logger.info("Password-set email sent to %s", email)
    except Exception as exc:
        logger.error("Failed to send password-set email to %s: %s", email, exc)


def _send_trial_activated_email(email: str, trial_ends_at: datetime) -> None:
    """Send trial-activated email for existing user upgraded to trial."""
    from app.worker.email import _send_smtp
    from app.worker.email.template_renderer import render_template

    expiry_str = trial_ends_at.strftime("%Y-%m-%d")

    subject, body = render_template(
        "trial_activated",
        trial_end_date=expiry_str,
    )
    try:
        _send_smtp(email, subject, body)
        logger.info("Trial-activated email sent to %s", email)
    except Exception as exc:
        logger.error("Failed to send trial-activated email to %s: %s", email, exc)


# ---------------------------------------------------------------------------
# Paddle API helper
# ---------------------------------------------------------------------------

def _paddle_base_url() -> str:
    if settings.paddle_environment == "production":
        return "https://api.paddle.com"
    return "https://sandbox-api.paddle.com"


def _paddle_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.paddle_api_key}",
        "Content-Type": "application/json",
    }


class PaddleAPIError(Exception):
    """Raised when Paddle returns a non-2xx response. Preserves the error code."""

    def __init__(self, http_status: int, paddle_code: str, paddle_detail: str) -> None:
        self.http_status = http_status
        self.paddle_code = paddle_code
        self.paddle_detail = paddle_detail
        super().__init__(f"{paddle_code}: {paddle_detail}")


async def _paddle_request(
    method: str,
    path: str,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make a Paddle API request and return the parsed response data."""
    url = f"{_paddle_base_url()}{path}"
    logger.debug("Paddle %s %s (environment=%s)", method, url, settings.paddle_environment)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(method, url, headers=_paddle_headers(), json=json)
    except httpx.RequestError as exc:
        logger.error("Paddle request failed — %s %s: %s", method, url, exc)
        raise HTTPException(status_code=502, detail="Paddle API unreachable") from exc
    if resp.status_code not in (200, 201):
        logger.error(
            "Paddle API error — %s %s → %s: %s",
            method, url, resp.status_code, resp.text,
        )
        try:
            err = resp.json().get("error", {})
            paddle_code = err.get("code", "unknown")
            paddle_detail = err.get("detail", resp.text)
        except Exception:
            paddle_code = "unknown"
            paddle_detail = resp.text
        raise PaddleAPIError(resp.status_code, paddle_code, paddle_detail)
    return resp.json()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class SubscriptionInfo(BaseModel):
    subscription_tier: str
    subscription_status: str | None
    subscription_plan: str | None
    subscription_current_period_end: datetime | None
    paddle_customer_id: str | None
    paddle_subscription_id: str | None
    is_trial_provisioned: bool
    trial_ends_at: datetime | None

    model_config = {"from_attributes": True}


class CheckoutResponse(BaseModel):
    transaction_id: str


class SubscriptionActionResponse(BaseModel):
    subscription_status: str | None
    subscription_plan: str | None
    subscription_current_period_end: datetime | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/subscription", response_model=SubscriptionInfo)
def get_subscription(current_user: User = Depends(get_current_user)) -> SubscriptionInfo:
    """Return the current user's subscription state."""
    return SubscriptionInfo(
        subscription_tier=current_user.subscription_tier,
        subscription_status=current_user.subscription_status,
        subscription_plan=current_user.subscription_plan,
        subscription_current_period_end=current_user.subscription_current_period_end,
        paddle_customer_id=current_user.paddle_customer_id,
        paddle_subscription_id=current_user.paddle_subscription_id,
        is_trial_provisioned=current_user.is_trial_provisioned,
        trial_ends_at=current_user.trial_ends_at,
    )


@router.post("/subscribe", response_model=CheckoutResponse)
async def subscribe(
    current_user: User = Depends(get_current_user),
) -> CheckoutResponse:
    """
    Create a Paddle checkout session for the Pro Monthly plan.
    Returns a checkout URL to open via Paddle.js overlay.
    """
    if not settings.paddle_price_id_pro_monthly:
        logger.error("subscribe called but PADDLE_PRICE_ID_PRO_MONTHLY is not configured")
        raise HTTPException(status_code=503, detail="Billing not configured")

    logger.info(
        "Creating Paddle checkout for user %s via %s (environment=%s)",
        current_user.id, _paddle_base_url(), settings.paddle_environment,
    )
    payload: dict[str, Any] = {
        "items": [{"price_id": settings.paddle_price_id_pro_monthly, "quantity": 1}],
        "customer": {"email": current_user.email},
        # Embed our local user ID so webhook handlers can match by ID,
        # regardless of which email the customer types in the Paddle overlay.
        "custom_data": {"user_id": current_user.id},
    }
    if current_user.paddle_customer_id:
        payload["customer"] = {"id": current_user.paddle_customer_id}

    try:
        data = await _paddle_request("POST", "/transactions", json=payload)
    except PaddleAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Paddle error: {exc.paddle_detail}") from exc
    transaction_id: str | None = data.get("data", {}).get("id")
    if not transaction_id:
        raise HTTPException(status_code=502, detail="Paddle did not return a transaction ID")

    return CheckoutResponse(transaction_id=transaction_id)


def _paddle_error_to_http(exc: PaddleAPIError) -> HTTPException:
    """Map known Paddle error codes to appropriate HTTP responses."""
    if exc.paddle_code == "subscription_locked_pending_changes":
        return HTTPException(
            status_code=409,
            detail="Paddle is still processing a previous change on this subscription. "
                   "Please wait a few seconds and try again.",
        )
    return HTTPException(status_code=502, detail=f"Paddle error: {exc.paddle_detail}")


@router.post("/cancel", response_model=SubscriptionActionResponse)
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubscriptionActionResponse:
    """Cancel the subscription at the end of the current billing period."""
    if not current_user.paddle_subscription_id:
        raise HTTPException(status_code=403, detail="No active subscription to cancel")
    if current_user.subscription_status not in ("active", "past_due"):
        raise HTTPException(
            status_code=400,
            detail=f"Subscription is not active (status: {current_user.subscription_status})",
        )

    try:
        await _paddle_request(
            "POST",
            f"/subscriptions/{current_user.paddle_subscription_id}/cancel",
            json={"effective_from": "next_billing_period"},
        )
    except PaddleAPIError as exc:
        raise _paddle_error_to_http(exc) from exc
    current_user.subscription_status = "cancelled"
    db.commit()

    return SubscriptionActionResponse(
        subscription_status=current_user.subscription_status,
        subscription_plan=current_user.subscription_plan,
        subscription_current_period_end=current_user.subscription_current_period_end,
    )


@router.post("/reactivate", response_model=SubscriptionActionResponse)
async def reactivate_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubscriptionActionResponse:
    """Reactivate a cancelled subscription that is still within its current period."""
    if not current_user.paddle_subscription_id:
        raise HTTPException(status_code=403, detail="No subscription to reactivate")
    if current_user.subscription_status != "cancelled":
        raise HTTPException(
            status_code=400,
            detail="Subscription is not in cancelled state",
        )

    try:
        await _paddle_request(
            "POST",
            f"/subscriptions/{current_user.paddle_subscription_id}/resume",
            json={"effective_from": "immediately"},
        )
    except PaddleAPIError as exc:
        raise _paddle_error_to_http(exc) from exc
    current_user.subscription_status = "active"
    db.commit()

    return SubscriptionActionResponse(
        subscription_status=current_user.subscription_status,
        subscription_plan=current_user.subscription_plan,
        subscription_current_period_end=current_user.subscription_current_period_end,
    )
