"""
Celery tasks for background monitoring and email digests.

monitor_parts  — re-queries every stored PartResult against the active provider,
                 writes PartFlag rows on stock/price changes, updates stored data.
send_digest_emails — fires send_digest_email for every user with unacknowledged flags.
cleanup_provider_error_logs — deletes ProviderErrorLog entries older than 48 hours.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.part_flag import FLAG_OUT_OF_STOCK, FLAG_PRICE_CHANGE, PartFlag
from app.models.part_result import PartResult as PartResultRow
from app.models.project import BomLine
from app.providers.registry import ProviderRegistry
from app.providers.schema import PartResult as ProviderResult, PriceBreak
from app.schemas.preferences import MergedPreferences
from app.worker.celery_app import celery

logger = logging.getLogger(__name__)

_PRICE_CHANGE_THRESHOLD = 0.10  # 10 %


# ---------------------------------------------------------------------------
# Core monitoring logic (async, injectable for tests)
# ---------------------------------------------------------------------------


def _lowest_price(pricing: list[PriceBreak]) -> float | None:
    if not pricing:
        return None
    return min(p.unit_price for p in pricing)


def check_and_flag(
    db: Session,
    stored: PartResultRow,
    new_results: list[ProviderResult],
) -> list[PartFlag]:
    """
    Compare new provider results against a stored PartResult.
    Creates and adds PartFlag rows to the session (but does NOT commit).
    Also updates stored.stock and stored.unit_price in-place.
    Returns the list of newly created flags.
    """
    if not new_results:
        return []

    new = new_results[0]
    flags: list[PartFlag] = []

    # --- stock-drop-to-zero flag ---
    if stored.stock > 0 and new.stock_total == 0:
        flag = PartFlag(
            part_result_id=stored.id,
            flag_type=FLAG_OUT_OF_STOCK,
            old_value=str(stored.stock),
            new_value="0",
        )
        db.add(flag)
        flags.append(flag)
        logger.info("out_of_stock flag for part_result %d (MPN %s)", stored.id, stored.mpn)

    # --- price-change flag ---
    new_price = _lowest_price(new.pricing)
    old_price = stored.unit_price
    if old_price is not None and new_price is not None and old_price > 0:
        change = abs(new_price - old_price) / old_price
        if change > _PRICE_CHANGE_THRESHOLD:
            flag = PartFlag(
                part_result_id=stored.id,
                flag_type=FLAG_PRICE_CHANGE,
                old_value=f"{old_price:.6f}",
                new_value=f"{new_price:.6f}",
            )
            db.add(flag)
            flags.append(flag)
            logger.info(
                "price_change flag for part_result %d (MPN %s): %.4f → %.4f (%.1f%%)",
                stored.id, stored.mpn, old_price, new_price, change * 100,
            )

    # --- update stored values ---
    stored.stock = new.stock_total
    if new_price is not None:
        stored.unit_price = new_price
    stored.retrieved_at = datetime.now(UTC)

    return flags


async def run_monitor(db: Session, registry: ProviderRegistry) -> int:
    """
    Scan all PartResult rows, re-query the provider, create flags.
    Returns the total number of flags created.
    """
    prefs = MergedPreferences()
    # Skip part_results that belong to locked BOM lines
    stored_rows: list[PartResultRow] = (
        db.query(PartResultRow)
        .join(BomLine, BomLine.id == PartResultRow.bom_line_id)
        .filter(BomLine.locked == False)  # noqa: E712
        .all()
    )
    total_flags = 0

    for stored in stored_rows:
        try:
            new_results = await registry.get().search_by_mpn(stored.mpn, 1, prefs)
        except Exception as exc:
            logger.warning("monitor: provider error for MPN %s: %s", stored.mpn, exc)
            continue

        flags = check_and_flag(db, stored, new_results)
        total_flags += len(flags)

    db.commit()
    logger.info("monitor_parts: processed %d part_results, created %d flags", len(stored_rows), total_flags)
    return total_flags


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------


@celery.task(name="app.worker.tasks.monitor_parts")
def monitor_parts() -> int:
    from app.core.database import SessionLocal
    from app.providers.registry import registry as app_registry

    db = SessionLocal()
    try:
        return asyncio.run(run_monitor(db, app_registry))
    finally:
        db.close()


@celery.task(name="app.worker.tasks.downgrade_to_free")
def downgrade_to_free(user_id: int) -> None:
    """
    Downgrade a user from pro to free after their subscription period ends.
    Scheduled via apply_async(eta=subscription_current_period_end) by the
    subscription.cancelled webhook handler.
    """
    from app.core.database import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            logger.warning("downgrade_to_free: user %d not found", user_id)
            return
        # Only downgrade if still cancelled — if they reactivated, skip
        if user.subscription_status != "cancelled":
            logger.info(
                "downgrade_to_free: user %d is %s — skipping downgrade",
                user_id,
                user.subscription_status,
            )
            return
        user.subscription_tier = "free"
        user.plan = "free"
        user.subscription_status = None
        user.subscription_plan = None
        user.paddle_subscription_id = None
        user.subscription_current_period_end = None
        db.commit()
        logger.info("downgrade_to_free: user %d downgraded to free", user_id)
    finally:
        db.close()


@celery.task(name="app.worker.tasks.send_digest_emails")
def send_digest_emails() -> int:
    from app.core.database import SessionLocal
    from app.models.part_flag import PartFlag as PF
    from app.models.part_result import PartResult as PR
    from app.models.project import BomLine, Project
    from app.models.user import User
    from app.worker.email import send_digest_email

    db = SessionLocal()
    try:
        user_ids = (
            db.query(User.id)
            .join(Project, Project.user_id == User.id)
            .join(BomLine, BomLine.project_id == Project.id)
            .join(PR, PR.bom_line_id == BomLine.id)
            .join(PF, PF.part_result_id == PR.id)
            .filter(PF.acknowledged == False)  # noqa: E712
            .distinct()
            .all()
        )
        count = 0
        for (uid,) in user_ids:
            try:
                send_digest_email(uid, db=db)
                count += 1
            except Exception as exc:
                logger.error("send_digest_email failed for user %d: %s", uid, exc)
        return count
    finally:
        db.close()


@celery.task(name="app.worker.tasks.cleanup_provider_error_logs")
def cleanup_provider_error_logs() -> int:
    """Delete ProviderErrorLog entries older than 48 hours.  Runs every 6 hours."""
    from datetime import timedelta

    from app.core.database import SessionLocal
    from app.models.provider_error_log import ProviderErrorLog

    cutoff = datetime.now(UTC) - timedelta(hours=48)
    db = SessionLocal()
    try:
        deleted: int = (
            db.query(ProviderErrorLog)
            .filter(ProviderErrorLog.occurred_at < cutoff)
            .delete(synchronize_session="fetch")
        )
        db.commit()
        logger.info("cleanup_provider_error_logs: deleted %d old entries", deleted)
        return deleted
    finally:
        db.close()


# ---------------------------------------------------------------------------
# AI usage snapshot task
# ---------------------------------------------------------------------------

_HAIKU_INPUT_COST_PER_MTOK: float = 0.80
_HAIKU_OUTPUT_COST_PER_MTOK: float = 4.00

_AID_FEATURES = ("nl_query", "ai_assist", "ai_advisor")


async def _redis_get_int(key: str) -> int:
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings
        client = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=1.0
        )
        value = await client.get(key)
        await client.aclose()
        return int(value) if value is not None else 0
    except Exception:
        return 0


async def _snapshot_ai_usage(date_str: str) -> None:
    """Read Redis token counters for *date_str* and persist to DB."""
    from app.core.database import SessionLocal
    from app.models.ai_usage_snapshot import AiUsageSnapshot

    db = SessionLocal()
    try:
        for feature in _AID_FEATURES:
            input_tokens = await _redis_get_int(f"ai:{feature}:tokens:input:{date_str}")
            output_tokens = await _redis_get_int(f"ai:{feature}:tokens:output:{date_str}")
            input_cost = input_tokens / 1_000_000 * _HAIKU_INPUT_COST_PER_MTOK
            output_cost = output_tokens / 1_000_000 * _HAIKU_OUTPUT_COST_PER_MTOK

            row = (
                db.query(AiUsageSnapshot)
                .filter(AiUsageSnapshot.date == date_str, AiUsageSnapshot.feature == feature)
                .first()
            )
            if row is None:
                row = AiUsageSnapshot(date=date_str, feature=feature)
                db.add(row)
            row.input_tokens = input_tokens
            row.output_tokens = output_tokens
            row.input_cost_usd = round(input_cost, 6)
            row.output_cost_usd = round(output_cost, 6)

        db.commit()
        logger.info("snapshot_ai_usage: saved data for %s", date_str)
    finally:
        db.close()


@celery.task(name="app.worker.tasks.snapshot_daily_ai_usage")
def snapshot_daily_ai_usage(days_ago: int = 1) -> None:
    """Capture AI token usage for *days_ago* days ago into DB."""
    from datetime import timedelta

    target_date = datetime.now(UTC) - timedelta(days=days_ago)
    date_str = target_date.strftime("%Y-%m-%d")
    asyncio.run(_snapshot_ai_usage(date_str))


# ---------------------------------------------------------------------------
# Trial expiry emails
# ---------------------------------------------------------------------------


def _subscribe_link() -> str:
    from app.core.database import settings as _settings

    base_url = getattr(_settings, "app_base_url", "http://localhost:5173")
    return f"{base_url}/billing"


@celery.task(name="app.worker.tasks.check_trial_expiry_warnings")
def check_trial_expiry_warnings() -> int:
    """
    Send day-50 warning emails to trial users whose trial expires in ~10 days.
    Finds users with is_trial_provisioned=True and trial_ends_at between
    9 and 11 days from now.
    """
    from app.core.database import SessionLocal, settings as _settings
    from app.models.user import User
    from app.worker.email import _send_smtp
    from app.worker.email.template_renderer import render_template

    db = SessionLocal()
    try:
        now = datetime.now(UTC)
        window_start = now + timedelta(days=9)
        window_end = now + timedelta(days=11)

        users = (
            db.query(User)
            .filter(
                User.is_trial_provisioned == True,  # noqa: E712
                User.trial_ends_at >= window_start,
                User.trial_ends_at <= window_end,
            )
            .all()
        )

        count = 0
        for user in users:
            try:
                expiry_str = user.trial_ends_at.strftime("%Y-%m-%d")
                subject, body = render_template(
                    "trial_expiring_soon",
                    trial_end_date=expiry_str,
                    subscribe_link=_subscribe_link(),
                )
                _send_smtp(user.email, subject, body)
                count += 1
                logger.info(
                    "Trial expiry warning sent to %s (expires %s)",
                    user.email,
                    expiry_str,
                )
            except Exception as exc:
                logger.error(
                    "Failed to send trial expiry warning to %s: %s",
                    user.email,
                    exc,
                )
        return count
    finally:
        db.close()


@celery.task(name="app.worker.tasks.check_trial_expired")
def check_trial_expired() -> int:
    """
    Send day-60 expired emails to trial users whose trial has ended.
    Finds users with is_trial_provisioned=True, trial_ends_at < now(),
    and trial_expiry_email_sent_at IS NULL.
    Sets trial_expiry_email_sent_at after sending.
    """
    from app.core.database import SessionLocal
    from app.models.user import User
    from app.worker.email import _send_smtp
    from app.worker.email.template_renderer import render_template

    db = SessionLocal()
    try:
        now = datetime.now(UTC)

        users = (
            db.query(User)
            .filter(
                User.is_trial_provisioned == True,  # noqa: E712
                User.trial_ends_at < now,
                User.trial_expiry_email_sent_at.is_(None),
            )
            .all()
        )

        count = 0
        for user in users:
            try:
                expiry_str = user.trial_ends_at.strftime("%Y-%m-%d")
                subject, body = render_template(
                    "trial_expired",
                    trial_end_date=expiry_str,
                    subscribe_link=_subscribe_link(),
                )
                _send_smtp(user.email, subject, body)
                user.trial_expiry_email_sent_at = now
                count += 1
                logger.info(
                    "Trial expired email sent to %s (expired %s)",
                    user.email,
                    expiry_str,
                )
            except Exception as exc:
                logger.error(
                    "Failed to send trial expired email to %s: %s",
                    user.email,
                    exc,
                )

        if count:
            db.commit()
        return count
    finally:
        db.close()

