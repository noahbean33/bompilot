"""
Paddle webhook handler.

Incoming webhooks are verified via HMAC-SHA256 (Paddle-Signature header),
written to paddle_events for idempotency, then dispatched to per-event handlers.

Signature format: Paddle-Signature: ts=<timestamp>;h1=<hex-hash>
Signed payload:   f"{timestamp}:{raw_request_body}"
"""

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db, settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_paddle_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """
    Verify the Paddle-Signature HMAC.

    Returns True if valid, False otherwise.
    An empty PADDLE_WEBHOOK_SECRET disables verification (dev/test only).
    """
    if not settings.paddle_webhook_secret:
        return True  # Skip in dev when secret is not configured

    if not signature_header:
        return False

    # Parse ts= and h1= from the header
    ts: str | None = None
    h1: str | None = None
    for part in signature_header.split(";"):
        if part.startswith("ts="):
            ts = part[3:]
        elif part.startswith("h1="):
            h1 = part[3:]

    if ts is None or h1 is None:
        logger.error("Paddle-Signature header missing ts= or h1=: %s", signature_header)
        return False

    signed_payload = f"{ts}:{raw_body.decode('utf-8', errors='replace')}"
    expected = hmac.new(
        settings.paddle_webhook_secret.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    match = hmac.compare_digest(expected, h1)
    if not match:
        logger.error(
            "Paddle signature mismatch — ts=%s expected(first16)=%s got(first16)=%s "
            "body_length=%d secret_prefix=%s",
            ts, expected[:16], h1[:16], len(raw_body),
            settings.paddle_webhook_secret[:8],
        )
    return match


# ---------------------------------------------------------------------------
# Paddle API helper (used to enrich sparse webhook payloads)
# ---------------------------------------------------------------------------

def _paddle_base_url() -> str:
    if settings.paddle_environment == "production":
        return "https://api.paddle.com"
    return "https://sandbox-api.paddle.com"


def _paddle_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.paddle_api_key}"}


async def _fetch_customer_email(customer_id: str) -> str | None:
    """
    Webhook payloads only carry customer_id, not email.
    Call the Paddle Customers API to retrieve the email so we can match
    the event to a local user.
    """
    try:
        url = f"{_paddle_base_url()}/customers/{customer_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_paddle_headers())
        if resp.status_code == 200:
            email: str | None = resp.json().get("data", {}).get("email")
            logger.debug("Fetched email for Paddle customer %s: %s", customer_id, email)
            return email
        logger.warning("Paddle customer lookup %s returned %s", customer_id, resp.status_code)
    except Exception as exc:
        logger.error("Failed to fetch Paddle customer %s: %s", customer_id, exc)
    return None


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _find_user_by_paddle(db: Session, data: dict[str, Any]) -> Any:
    """
    Resolve the local user from Paddle event data.

    Resolution order (most → least reliable):
    1. custom_data.user_id — our own ID embedded at transaction creation time;
       immune to the customer typing a different email in the Paddle overlay.
    2. paddle_customer_id — set after the first successful payment.
    3. customer email — fallback, enriched from the Paddle Customers API upstream.
    """
    from app.models.user import User

    # 1. custom_data.user_id (most reliable)
    user_id: int | None = None
    custom_data = data.get("custom_data") or {}
    if isinstance(custom_data, dict):
        raw_id = custom_data.get("user_id")
        if raw_id is not None:
            try:
                user_id = int(raw_id)
            except (TypeError, ValueError):
                pass
    if user_id is not None:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            return user
        logger.warning("custom_data.user_id=%d not found in DB", user_id)

    # 2. paddle_customer_id
    customer_id: str | None = (
        data.get("customer_id")
        or data.get("customer", {}).get("id")
    )
    if customer_id:
        user = db.query(User).filter(User.paddle_customer_id == customer_id).first()
        if user:
            return user

    # 3. email (enriched from Paddle API upstream)
    customer_email: str | None = (
        data.get("customer", {}).get("email")
        or data.get("customer_email")
    )
    if customer_email:
        user = db.query(User).filter(User.email == customer_email).first()
        if user:
            return user

    logger.warning(
        "Could not resolve user — user_id=%s customer_id=%s email=%s",
        user_id, customer_id, customer_email,
    )
    return None


def _parse_period_end(data: dict[str, Any]) -> datetime | None:
    """Extract subscription current_billing_period.ends_at as a UTC datetime."""
    raw: str | None = (
        (data.get("current_billing_period") or {}).get("ends_at")
        or data.get("next_billed_at")
    )
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(UTC).replace(tzinfo=UTC)
    except Exception:
        return None


def _handle_subscription_activated(db: Session, data: dict[str, Any]) -> None:
    from app.models.user import User

    user = _find_user_by_paddle(db, data)
    if not user:
        logger.warning("subscription.activated: no user found for event data")
        return

    user.subscription_tier = "pro"
    user.plan = "paid"
    user.subscription_status = "active"
    user.subscription_plan = "pro"
    user.paddle_customer_id = data.get("customer_id") or user.paddle_customer_id
    user.paddle_subscription_id = data.get("id") or user.paddle_subscription_id
    user.subscription_current_period_end = _parse_period_end(data)
    db.commit()
    logger.info("subscription.activated: user %d upgraded to pro", user.id)


def _handle_subscription_updated(db: Session, data: dict[str, Any]) -> None:
    user = _find_user_by_paddle(db, data)
    if not user:
        logger.warning("subscription.updated: no user found")
        return

    status: str | None = data.get("status")
    if status:
        user.subscription_status = status
    period_end = _parse_period_end(data)
    if period_end:
        user.subscription_current_period_end = period_end

    items = data.get("items", [])
    if items:
        price_id: str | None = items[0].get("price", {}).get("id")
        if price_id:
            user.subscription_plan = "pro"

    db.commit()
    logger.info("subscription.updated: user %d status=%s", user.id, status)


def _handle_subscription_canceled(db: Session, data: dict[str, Any]) -> None:
    """
    Handle subscription.canceled (Paddle uses US spelling).

    If the billing period has already ended or there is no future period end,
    downgrade the user to free immediately.  Otherwise preserve Pro access until
    period_end and schedule a Celery task to downgrade at that time.
    """
    user = _find_user_by_paddle(db, data)
    if not user:
        logger.warning("subscription.canceled: no user found")
        return

    user.subscription_status = "cancelled"
    period_end = _parse_period_end(data)
    if period_end:
        user.subscription_current_period_end = period_end

    now = datetime.now(UTC)
    if not period_end or period_end <= now:
        # Immediate cancellation (e.g. cancelled from Paddle dashboard with no
        # remaining paid period) — downgrade right away.
        user.subscription_tier = "free"
        user.subscription_plan = None
        user.paddle_subscription_id = None
        db.commit()
        logger.info("subscription.canceled: user %d downgraded to free immediately", user.id)
        return

    db.commit()

    # Period still running — schedule downgrade at period end.
    try:
        from app.worker.tasks import downgrade_to_free
        downgrade_to_free.apply_async(
            args=[user.id],
            eta=period_end,
        )
        logger.info(
            "subscription.canceled: user %d stays pro until %s, downgrade scheduled",
            user.id, period_end,
        )
    except Exception as exc:
        logger.error("Failed to schedule downgrade task for user %d: %s", user.id, exc)


def _handle_subscription_past_due(db: Session, data: dict[str, Any]) -> None:
    user = _find_user_by_paddle(db, data)
    if not user:
        logger.warning("subscription.past_due: no user found")
        return

    user.subscription_status = "past_due"
    db.commit()
    logger.info("subscription.past_due: user %d (tier preserved, Paddle will retry)", user.id)


def _handle_subscription_paused(db: Session, data: dict[str, Any]) -> None:
    user = _find_user_by_paddle(db, data)
    if not user:
        logger.warning("subscription.paused: no user found")
        return

    user.subscription_status = "paused"
    user.subscription_tier = "free"
    user.plan = "free"
    db.commit()
    logger.info("subscription.paused: user %d downgraded to free", user.id)


def _handle_transaction_completed(db: Session, data: dict[str, Any]) -> None:
    """
    Fires immediately when payment succeeds (before subscription.activated).
    Upgrades the user to pro so the UI updates without waiting for the subscription event.
    """
    user = _find_user_by_paddle(db, data)
    if not user:
        logger.warning("transaction.completed: no user found for event data")
        return

    if user.subscription_tier == "pro":
        logger.info("transaction.completed: user %d already pro — skipping", user.id)
        return

    user.subscription_tier = "pro"
    user.paddle_customer_id = data.get("customer_id") or user.paddle_customer_id
    db.commit()
    logger.info("transaction.completed: user %d set to pro (subscription event will follow)", user.id)


_EVENT_HANDLERS = {
    "transaction.completed": _handle_transaction_completed,
    "subscription.activated": _handle_subscription_activated,
    "subscription.updated": _handle_subscription_updated,
    "subscription.canceled": _handle_subscription_canceled,   # Paddle uses US spelling
    "subscription.past_due": _handle_subscription_past_due,
    "subscription.paused": _handle_subscription_paused,
}


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@router.post("/paddle")
async def paddle_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """
    Receive and process Paddle webhook events.

    - Verifies HMAC signature
    - Writes to paddle_events (idempotency check)
    - Dispatches to per-event handler
    """
    from app.models.paddle_event import PaddleEvent

    raw_body = await request.body()
    sig_header = request.headers.get("Paddle-Signature")

    logger.debug(
        "Paddle webhook received — body_length=%d sig_header=%s",
        len(raw_body), sig_header,
    )

    if not _verify_paddle_signature(raw_body, sig_header):
        logger.error(
            "Paddle webhook 400 — signature invalid. "
            "Check PADDLE_WEBHOOK_SECRET is the notification secret key, not the notification ID. "
            "sig_header=%s body_preview=%s",
            sig_header, raw_body[:200],
        )
        raise HTTPException(status_code=400, detail="Invalid Paddle signature")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_id: str | None = payload.get("event_id") or payload.get("id")
    event_type: str | None = payload.get("event_type") or payload.get("notification_type")
    data: dict[str, Any] = payload.get("data", payload)

    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Missing event_id or event_type")

    # Webhook payloads carry customer_id but not the customer's email.
    # Fetch the email from the Paddle Customers API so _find_user_by_paddle
    # can match the event to a local user when paddle_customer_id is not yet set.
    customer_id: str | None = data.get("customer_id")
    if customer_id and not data.get("customer", {}).get("email"):
        email = await _fetch_customer_email(customer_id)
        if email:
            data.setdefault("customer", {})["email"] = email
            logger.debug("Enriched event %s with customer email %s", event_type, email)

    # Idempotency: skip if already processed
    existing = db.query(PaddleEvent).filter(PaddleEvent.event_id == event_id).first()
    if existing:
        logger.info("Duplicate webhook event_id=%s — skipping", event_id)
        return {"status": "already_processed"}

    # Write to paddle_events before processing
    event_row = PaddleEvent(
        event_id=event_id,
        event_type=event_type,
        payload=payload,
    )
    db.add(event_row)
    db.flush()  # Persist before processing

    try:
        # Dispatch to handler
        handler = _EVENT_HANDLERS.get(event_type)
        if handler:
            handler(db, data)
        else:
            logger.debug("Unhandled Paddle event type: %s", event_type)

        # Mark as processed
        event_row.processed_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Webhook processing error for event %s: %s", event_id, exc)
        raise HTTPException(status_code=500, detail="Webhook processing failed") from exc

    return {"status": "ok"}
