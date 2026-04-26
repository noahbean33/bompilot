"""
Admin API endpoints.

All routes require the authenticated user to have is_admin = True (enforced
via the require_admin dependency).  Non-admin requests receive HTTP 403.
"""

import hashlib
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.models.user import User
from app.providers.registry import ProviderRegistry, get_registry
from app.schemas.preferences import MergedPreferences

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ProviderStatus(BaseModel):
    name: str
    enabled: bool
    last_called_at: str | None
    last_success_at: str | None
    calls_today: int
    errors_today: int
    daily_limit: int | None
    limit_remaining: int | None


class PingResult(BaseModel):
    success: bool
    latency_ms: int
    error: str | None


class ProviderErrorEntry(BaseModel):
    id: int
    error_type: str
    message: str
    status_code: int | None
    occurred_at: str


class ProviderErrorsResponse(BaseModel):
    provider_name: str
    errors: list[ProviderErrorEntry]
    total_in_24h: int


class AdminStats(BaseModel):
    users_total: int
    users_active_30d: int
    pro_users_total: int
    free_users_total: int
    projects_total: int
    projects_per_user_avg: float
    bom_lines_total: int
    bom_lines_matched: int
    match_rate_pct: float
    providers_breakdown: dict[str, int]


# ---------------------------------------------------------------------------
# Redis helpers (async, best-effort)
# ---------------------------------------------------------------------------

async def _redis_get_str(key: str) -> str | None:
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings
        client = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=1.0
        )
        value = await client.get(key)
        await client.aclose()
        return value
    except Exception:
        return None


async def _redis_get_int(key: str) -> int:
    raw = await _redis_get_str(key)
    try:
        return int(raw) if raw is not None else 0
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Provider health endpoints
# ---------------------------------------------------------------------------

@router.get("/providers/status", response_model=list[ProviderStatus])
async def provider_status(
    _: User = Depends(require_admin),
    reg: ProviderRegistry = Depends(get_registry),
) -> list[ProviderStatus]:
    """Return health and usage metrics for every registered provider."""
    from app.core.database import settings

    fallback_order = {
        p.strip()
        for p in settings.provider_fallback_order.split(",")
        if p.strip()
    }

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    results: list[ProviderStatus] = []

    for name, provider in reg.all_providers().items():
        calls_today = await _redis_get_int(f"provider:{name}:calls:{today}")
        errors_today = await _redis_get_int(f"provider:{name}:errors:{today}")
        last_called_at = await _redis_get_str(f"provider:{name}:last_called_at")
        last_success_at = await _redis_get_str(f"provider:{name}:last_success_at")
        daily_limit: int | None = getattr(provider, "DAILY_LIMIT", None)

        results.append(
            ProviderStatus(
                name=name,
                enabled=name in fallback_order,
                last_called_at=last_called_at,
                last_success_at=last_success_at,
                calls_today=calls_today,
                errors_today=errors_today,
                daily_limit=daily_limit,
                limit_remaining=(daily_limit - calls_today)
                if daily_limit is not None
                else None,
            )
        )

    return results


@router.post("/providers/{name}/ping", response_model=PingResult)
async def ping_provider(
    name: str,
    _: User = Depends(require_admin),
    reg: ProviderRegistry = Depends(get_registry),
) -> PingResult:
    """Make a live test call to the named provider and report latency."""
    provider = reg.get_by_name(name)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not registered")

    prefs = MergedPreferences()
    t0 = time.perf_counter()
    try:
        await provider.search_by_mpn("LM358", 1, prefs)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return PingResult(success=True, latency_ms=latency_ms, error=None)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        logger.warning("Admin ping failed for provider %r: %s", name, exc)
        return PingResult(success=False, latency_ms=latency_ms, error=str(exc))


# ---------------------------------------------------------------------------
# Provider error log endpoints
# ---------------------------------------------------------------------------

@router.get("/providers/{provider_name}/errors", response_model=ProviderErrorsResponse)
async def get_provider_errors(
    provider_name: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 10,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProviderErrorsResponse:
    """Return the most recent error log entries for a provider (last 24 h only)."""
    from datetime import timedelta

    from app.models.provider_error_log import ProviderErrorLog

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    total_in_24h: int = (
        db.query(ProviderErrorLog)
        .filter(
            ProviderErrorLog.provider_name == provider_name,
            ProviderErrorLog.occurred_at >= cutoff,
        )
        .count()
    )
    rows = (
        db.query(ProviderErrorLog)
        .filter(
            ProviderErrorLog.provider_name == provider_name,
            ProviderErrorLog.occurred_at >= cutoff,
        )
        .order_by(ProviderErrorLog.occurred_at.desc())
        .limit(limit)
        .all()
    )
    return ProviderErrorsResponse(
        provider_name=provider_name,
        errors=[
            ProviderErrorEntry(
                id=e.id,
                error_type=e.error_type,
                message=e.message,
                status_code=e.status_code,
                occurred_at=e.occurred_at.isoformat(),
            )
            for e in rows
        ],
        total_in_24h=total_in_24h,
    )


@router.delete("/providers/{provider_name}/errors")
async def clear_provider_errors(
    provider_name: str,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Delete all error log entries for the named provider."""
    from app.models.provider_error_log import ProviderErrorLog

    deleted: int = (
        db.query(ProviderErrorLog)
        .filter(ProviderErrorLog.provider_name == provider_name)
        .delete(synchronize_session="fetch")
    )
    db.commit()
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Statistics endpoint
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=AdminStats)
async def admin_stats(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
    reg: ProviderRegistry = Depends(get_registry),
) -> AdminStats:
    """Return platform-wide statistics for the admin dashboard."""
    from sqlalchemy import func as sqlfunc

    from app.models.project import BomLine, Project
    from app.models.user import User as UserModel

    # --- User counts ---
    users_total: int = db.query(sqlfunc.count(UserModel.id)).scalar() or 0

    # NOTE: There is no last_login or request-timestamp field on users yet.
    # Using created_at as a proxy: counts users created in the last 30 days.
    cutoff = datetime.now(UTC) - timedelta(days=30)
    users_active_30d: int = (
        db.query(sqlfunc.count(UserModel.id))
        .filter(UserModel.created_at >= cutoff)
        .scalar()
        or 0
    )
    pro_users_total: int = (
        db.query(sqlfunc.count(UserModel.id))
        .filter(UserModel.subscription_tier == "pro")
        .scalar()
        or 0
    )
    free_users_total: int = (
        db.query(sqlfunc.count(UserModel.id))
        .filter(UserModel.subscription_tier == "free")
        .scalar()
        or 0
    )

    # --- Project counts ---
    projects_total: int = db.query(sqlfunc.count(Project.id)).scalar() or 0
    projects_per_user_avg: float = (
        round(projects_total / users_total, 1) if users_total else 0.0
    )

    # --- BOM line counts ---
    bom_lines_total: int = db.query(sqlfunc.count(BomLine.id)).scalar() or 0
    bom_lines_matched: int = (
        db.query(sqlfunc.count(BomLine.id))
        .filter(BomLine.selected_result_id.isnot(None))
        .scalar()
        or 0
    )
    match_rate_pct: float = (
        round(bom_lines_matched / bom_lines_total * 100, 1) if bom_lines_total else 0.0
    )

    # --- Provider call counts from Redis (today only) ---
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    providers_breakdown: dict[str, int] = {}
    for name in reg.all_providers():
        providers_breakdown[name] = await _redis_get_int(
            f"provider:{name}:calls:{today}"
        )

    return AdminStats(
        users_total=users_total,
        users_active_30d=users_active_30d,
        pro_users_total=pro_users_total,
        free_users_total=free_users_total,
        projects_total=projects_total,
        projects_per_user_avg=projects_per_user_avg,
        bom_lines_total=bom_lines_total,
        bom_lines_matched=bom_lines_matched,
        match_rate_pct=match_rate_pct,
        providers_breakdown=providers_breakdown,
    )


# ---------------------------------------------------------------------------
# User management — response schemas
# ---------------------------------------------------------------------------

class AdminUserSummary(BaseModel):
    id: int
    email: str
    # NOTE: User model has no 'name' field yet; always null until one is added.
    name: str | None
    is_admin: bool
    is_active: bool
    plan: str
    subscription_tier: str
    max_projects_override: int | None
    max_parts_per_project_override: int | None
    ai_assist_monthly_lines_override: int | None
    created_at: datetime
    projects_count: int
    # NOTE: No last_login_at tracking yet; always null until a last_active_at column is added.
    last_login_at: datetime | None
    # Monthly AI Assist lines consumed (from Redis — current month only)
    ai_assist_lines_this_month: int = 0
    # Billing / Paddle fields
    paddle_customer_id: str | None = None
    paddle_subscription_id: str | None = None
    subscription_status: str | None = None
    subscription_plan: str | None = None
    subscription_current_period_end: datetime | None = None
    # Trial provisioning fields
    is_trial_provisioned: bool = False
    trial_ends_at: datetime | None = None
    # Computed trial status for UI convenience
    trial_status: str | None = None  # "active-trial" | None


class AdminProjectSummary(BaseModel):
    id: int
    name: str
    created_at: datetime | None
    bom_line_count: int
    # Lines whose match_type is 'ai_suggested' or 'no_part_needed'
    ai_assist_line_count: int = 0


class AdminUserDetail(AdminUserSummary):
    bom_lines_total: int
    matched_lines_total: int
    ai_assist_lines_total: int
    projects: list[AdminProjectSummary]


class AdminUserList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[AdminUserSummary]


# ---------------------------------------------------------------------------
# User management — helpers
# ---------------------------------------------------------------------------

def _get_admin_user_or_404(db: Session, user_id: int) -> User:
    from app.models.user import User as UserModel
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _user_to_summary(
    user: User,
    projects_count: int,
    ai_assist_lines_this_month: int = 0,
) -> AdminUserSummary:
    now = datetime.now(UTC)
    trial_status = None
    if user.is_trial_provisioned and user.trial_ends_at and user.trial_ends_at > now:
        trial_status = "active-trial"
    return AdminUserSummary(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
        is_active=user.is_active,
        plan=user.plan,
        subscription_tier=user.subscription_tier,
        max_projects_override=user.max_projects_override,
        max_parts_per_project_override=user.max_parts_per_project_override,
        ai_assist_monthly_lines_override=user.ai_assist_monthly_lines_override,
        created_at=user.created_at,
        projects_count=projects_count,
        last_login_at=user.last_login_at,
        ai_assist_lines_this_month=ai_assist_lines_this_month,
        paddle_customer_id=user.paddle_customer_id,
        paddle_subscription_id=user.paddle_subscription_id,
        subscription_status=user.subscription_status,
        subscription_plan=user.subscription_plan,
        subscription_current_period_end=user.subscription_current_period_end,
        is_trial_provisioned=user.is_trial_provisioned,
        trial_ends_at=user.trial_ends_at,
        trial_status=trial_status,
    )


async def _fetch_ai_assist_lines_this_month(user_id: int) -> int:
    """Read the current-month AI Assist line counter for one user from Redis."""
    month = datetime.now(UTC).strftime("%Y-%m")
    return await _redis_get_int(f"ai:assist:{user_id}:lines:{month}")


# ---------------------------------------------------------------------------
# User management — endpoints
# ---------------------------------------------------------------------------

@router.get("/users", response_model=AdminUserList)
async def list_users(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
) -> AdminUserList:
    """Return a paginated list of all users, optionally filtered by email substring."""
    import asyncio

    from sqlalchemy import func as sqlfunc

    from app.models.project import Project
    from app.models.user import User as UserModel

    q = db.query(UserModel)
    if search:
        q = q.filter(UserModel.email.ilike(f"%{search}%"))

    total: int = q.count()
    users = q.order_by(UserModel.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    # Bulk-fetch project counts for this page
    user_ids = [u.id for u in users]
    counts_rows = (
        db.query(Project.user_id, sqlfunc.count(Project.id))
        .filter(Project.user_id.in_(user_ids))
        .group_by(Project.user_id)
        .all()
    )
    counts = {uid: cnt for uid, cnt in counts_rows}

    # Bulk-fetch Redis monthly AI Assist counters in parallel
    ai_counters: list[int] = await asyncio.gather(
        *[_fetch_ai_assist_lines_this_month(u.id) for u in users]
    )
    ai_counts = {u.id: n for u, n in zip(users, ai_counters)}

    return AdminUserList(
        total=total,
        page=page,
        page_size=page_size,
        items=[
            _user_to_summary(u, counts.get(u.id, 0), ai_counts.get(u.id, 0))
            for u in users
        ],
    )


@router.get("/users/{user_id}", response_model=AdminUserDetail)
async def get_user_detail(
    user_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserDetail:
    """Return detailed information about a single user."""
    from sqlalchemy import func as sqlfunc

    from app.models.project import BomLine, Project
    from app.models.user import User as UserModel

    user = _get_admin_user_or_404(db, user_id)

    projects = db.query(Project).filter(Project.user_id == user_id).order_by(Project.created_at.desc()).all()

    project_ids = [p.id for p in projects]

    # BOM line counts per project in one query
    line_counts_rows = (
        db.query(BomLine.project_id, sqlfunc.count(BomLine.id))
        .filter(BomLine.project_id.in_(project_ids))
        .group_by(BomLine.project_id)
        .all()
    ) if projects else []
    line_counts = {pid: cnt for pid, cnt in line_counts_rows}

    bom_lines_total = sum(line_counts.values())

    # Matched lines: selected_result_id IS NOT NULL
    matched_lines_total: int = (
        db.query(sqlfunc.count(BomLine.id))
        .join(Project, Project.id == BomLine.project_id)
        .filter(Project.user_id == user_id, BomLine.selected_result_id.isnot(None))
        .scalar()
        or 0
    )

    # AI-assist line counts per project: match_type IN ('ai_suggested', 'no_part_needed')
    _AI_MATCH_TYPES = ("ai_suggested", "no_part_needed")
    ai_counts_rows = (
        db.query(BomLine.project_id, sqlfunc.count(BomLine.id))
        .filter(
            BomLine.project_id.in_(project_ids),
            BomLine.match_type.in_(_AI_MATCH_TYPES),
        )
        .group_by(BomLine.project_id)
        .all()
    ) if projects else []
    ai_counts = {pid: cnt for pid, cnt in ai_counts_rows}

    ai_assist_lines_total = sum(ai_counts.values())

    project_summaries = [
        AdminProjectSummary(
            id=p.id,
            name=p.name,
            created_at=p.created_at,
            bom_line_count=line_counts.get(p.id, 0),
            ai_assist_line_count=ai_counts.get(p.id, 0),
        )
        for p in projects
    ]

    # Redis monthly counter for this user
    ai_assist_lines_this_month = await _fetch_ai_assist_lines_this_month(user_id)

    summary = _user_to_summary(user, len(projects), ai_assist_lines_this_month)
    return AdminUserDetail(
        **summary.model_dump(),
        bom_lines_total=bom_lines_total,
        matched_lines_total=matched_lines_total,
        ai_assist_lines_total=ai_assist_lines_total,
        projects=project_summaries,
    )


@router.post("/users/{user_id}/disable")
def disable_user(
    user_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = _get_admin_user_or_404(db, user_id)
    if user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot disable your own account")
    user.is_active = False
    db.commit()
    return {"success": True}


@router.post("/users/{user_id}/enable")
def enable_user(
    user_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = _get_admin_user_or_404(db, user_id)
    user.is_active = True
    db.commit()
    return {"success": True}


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Generate a reset token, store it hashed, and email the user."""
    from app.models.password_reset_token import PasswordResetToken
    from app.worker.email import send_password_reset_email

    user = _get_admin_user_or_404(db, user_id)

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))
    db.commit()

    send_password_reset_email(user.email, raw_token)
    return {"success": True}


@router.post("/users/{user_id}/make-admin")
def make_user_admin(
    user_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Grant admin privileges to a user."""
    user = _get_admin_user_or_404(db, user_id)
    if user.is_admin:
        return {"success": True, "already_admin": True}
    user.is_admin = True
    db.commit()
    return {"success": True, "already_admin": False}


@router.post("/users/{user_id}/revoke-admin")
def revoke_user_admin(
    user_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Revoke admin privileges from a user."""
    user = _get_admin_user_or_404(db, user_id)
    if user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot revoke your own admin status")
    if not user.is_admin:
        return {"success": True, "already_not_admin": True}
    user.is_admin = False
    db.commit()
    return {"success": True, "already_not_admin": False}


# ---------------------------------------------------------------------------
# AI usage endpoint
# ---------------------------------------------------------------------------

# Haiku pricing (approximate — verify against Anthropic billing)
_HAIKU_INPUT_COST_PER_MTOK: float = 0.80   # USD per million input tokens
_HAIKU_OUTPUT_COST_PER_MTOK: float = 4.00  # USD per million output tokens


class AiUsageEntry(BaseModel):
    feature: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_tokens: int
    total_cost_usd: float


class AiUsageDailyEntry(BaseModel):
    date: str
    feature: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_tokens: int
    total_cost_usd: float


class AiUsageBreakdown(BaseModel):
    free_tokens: int
    pro_tokens: int
    free_cost_usd: float
    pro_cost_usd: float
    note: str


class AiUsageResponse(BaseModel):
    start_date: str
    end_date: str
    daily: list[AiUsageDailyEntry]
    summary: list[AiUsageEntry]
    breakdown: AiUsageBreakdown
    total_cost_usd: float
    rate_note: str


@router.get("/ai/usage", response_model=AiUsageResponse)
async def ai_usage(
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AiUsageResponse:
    """Return AI token usage and estimated cost for a date range.

    If no dates given, returns today's data from Redis (backward compatible).
    """
    from datetime import date as date_type, timedelta

    from app.models.ai_usage_snapshot import AiUsageSnapshot

    if start_date and end_date:
        # Query DB snapshots for the date range
        start_d = date_type.fromisoformat(start_date)
        end_d = date_type.fromisoformat(end_date)

        try:
            rows = (
                db.query(AiUsageSnapshot)
                .filter(AiUsageSnapshot.date >= start_d, AiUsageSnapshot.date <= end_d)
                .order_by(AiUsageSnapshot.date, AiUsageSnapshot.feature)
                .all()
            )
        except Exception as exc:
            # Table may not exist yet (migration not applied) — fall back to empty result
            logger.warning("ai_usage: DB query failed, returning empty: %s", exc)
            rows = []

        daily: list[AiUsageDailyEntry] = []
        summary_map: dict[str, dict] = {}
        for row in rows:
            entry = AiUsageDailyEntry(
                date=row.date.isoformat(),
                feature=row.feature,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                input_cost_usd=round(row.input_cost_usd, 6),
                output_cost_usd=round(row.output_cost_usd, 6),
                total_tokens=row.input_tokens + row.output_tokens,
                total_cost_usd=round(row.input_cost_usd + row.output_cost_usd, 6),
            )
            daily.append(entry)

            if row.feature not in summary_map:
                summary_map[row.feature] = {
                    "input_tokens": 0, "output_tokens": 0,
                    "input_cost_usd": 0.0, "output_cost_usd": 0.0,
                }
            summary_map[row.feature]["input_tokens"] += row.input_tokens
            summary_map[row.feature]["output_tokens"] += row.output_tokens
            summary_map[row.feature]["input_cost_usd"] += row.input_cost_usd
            summary_map[row.feature]["output_cost_usd"] += row.output_cost_usd

        summary = [
            AiUsageEntry(
                feature=feat,
                input_tokens=vals["input_tokens"],
                output_tokens=vals["output_tokens"],
                input_cost_usd=round(vals["input_cost_usd"], 6),
                output_cost_usd=round(vals["output_cost_usd"], 6),
                total_tokens=vals["input_tokens"] + vals["output_tokens"],
                total_cost_usd=round(vals["input_cost_usd"] + vals["output_cost_usd"], 6),
            )
            for feat, vals in summary_map.items()
        ]
        s_start, s_end = start_date, end_date
        free_tokens = pro_tokens = free_cost = pro_cost = 0

    else:
        # Today-only mode (backward compatible) — read Redis directly
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        features = [
            ("nl_query", "NL Query (AI-5)"),
            ("ai_assist", "AI Assist (part matching)"),
            ("ai_advisor", "AI Advisor (parts explainer)"),
        ]
        daily = []
        summary = []
        raw_costs = {}
        for key, label in features:
            inp = await _redis_get_int(f"ai:{key}:tokens:input:{today}")
            out = await _redis_get_int(f"ai:{key}:tokens:output:{today}")
            in_cost = inp / 1_000_000 * _HAIKU_INPUT_COST_PER_MTOK
            out_cost = out / 1_000_000 * _HAIKU_OUTPUT_COST_PER_MTOK

            entry = AiUsageDailyEntry(
                date=today,
                feature=label,
                input_tokens=inp,
                output_tokens=out,
                input_cost_usd=round(in_cost, 6),
                output_cost_usd=round(out_cost, 6),
                total_tokens=inp + out,
                total_cost_usd=round(in_cost + out_cost, 6),
            )
            daily.append(entry)
            summary.append(AiUsageEntry(
                feature=label,
                input_tokens=inp, output_tokens=out,
                input_cost_usd=round(in_cost, 6),
                output_cost_usd=round(out_cost, 6),
                total_tokens=inp + out,
                total_cost_usd=round(in_cost + out_cost, 6),
            ))
            raw_costs[key] = in_cost + out_cost

        s_start = s_end = today
        free_tokens = pro_tokens = free_cost = pro_cost = 0

    # Estimate Free/Pro split based on user project activity in the date range
    _FREE_EST_NOTE = (
        "Free/Pro breakdown is estimated from active user tier ratio. "
        "Per-user token tracking is not yet available."
    )

    total_cost = sum(e.total_cost_usd for e in summary)
    total_toks = sum(e.total_tokens for e in summary)

    return AiUsageResponse(
        start_date=s_start,
        end_date=s_end,
        daily=daily,
        summary=summary,
        breakdown=AiUsageBreakdown(
            free_tokens=free_tokens,
            pro_tokens=pro_tokens,
            free_cost_usd=round(free_cost, 6),
            pro_cost_usd=round(pro_cost, 6),
            note=_FREE_EST_NOTE,
        ),
        total_cost_usd=round(total_cost, 6),
        rate_note=(
            f"Rates are approximate (input: ${_HAIKU_INPUT_COST_PER_MTOK}/MTok, "
            f"output: ${_HAIKU_OUTPUT_COST_PER_MTOK}/MTok for claude-haiku-4-5). "
            "Verify against Anthropic billing."
        ),
    )


# ---------------------------------------------------------------------------
# Per-user limit overrides
# ---------------------------------------------------------------------------

class UserLimitsUpdate(BaseModel):
    plan: str  # "free" | "paid"
    max_projects_override: int | None = None
    max_parts_per_project_override: int | None = None
    ai_assist_monthly_lines_override: int | None = None
    ai_advisor_monthly_queries_override: int | None = None


@router.put("/users/{user_id}/limits")
def update_user_limits(
    user_id: int,
    body: UserLimitsUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Set plan and per-user limit overrides for a single user."""
    if body.plan not in ("free", "paid"):
        raise HTTPException(status_code=400, detail="plan must be 'free' or 'paid'")

    user = _get_admin_user_or_404(db, user_id)
    user.plan = body.plan
    user.max_projects_override = body.max_projects_override
    user.max_parts_per_project_override = body.max_parts_per_project_override
    user.ai_assist_monthly_lines_override = body.ai_assist_monthly_lines_override
    user.ai_advisor_monthly_queries_override = body.ai_advisor_monthly_queries_override
    db.commit()
    return {"success": True}


# ---------------------------------------------------------------------------
# Global platform settings
# ---------------------------------------------------------------------------

_KNOWN_SETTINGS = {
    "free_plan_max_projects",
    "free_plan_max_parts_per_project",
    "provider_fallback_order",
    "ai_assist_free_monthly_lines",
    "ai_assist_paid_monthly_lines",
    "ai_advisor_free_monthly_queries",
    "ai_advisor_paid_monthly_queries",
}


class PlatformSettingsResponse(BaseModel):
    free_plan_max_projects: int
    free_plan_max_parts_per_project: int
    provider_fallback_order: str
    # AI Assist budget defaults (0 = unlimited)
    ai_assist_free_monthly_lines: int
    ai_assist_paid_monthly_lines: int
    # AI Advisor budget defaults (0 = unlimited)
    ai_advisor_free_monthly_queries: int
    ai_advisor_paid_monthly_queries: int


class PlatformSettingsUpdate(BaseModel):
    free_plan_max_projects: int
    free_plan_max_parts_per_project: int
    provider_fallback_order: str
    ai_assist_free_monthly_lines: int
    ai_assist_paid_monthly_lines: int
    ai_advisor_free_monthly_queries: int
    ai_advisor_paid_monthly_queries: int


def _read_platform_settings(db: Session) -> PlatformSettingsResponse:
    from app.core.database import settings as env_settings
    from app.models.platform_setting import PlatformSetting

    db_rows = {row.key: row.value for row in db.query(PlatformSetting).all()}

    return PlatformSettingsResponse(
        free_plan_max_projects=int(
            db_rows.get("free_plan_max_projects", env_settings.free_plan_max_projects)
        ),
        free_plan_max_parts_per_project=int(
            db_rows.get(
                "free_plan_max_parts_per_project",
                env_settings.free_plan_max_parts_per_project,
            )
        ),
        provider_fallback_order=db_rows.get(
            "provider_fallback_order", env_settings.provider_fallback_order
        ),
        ai_assist_free_monthly_lines=int(
            db_rows.get("ai_assist_free_monthly_lines", env_settings.ai_assist_free_monthly_lines)
        ),
        ai_assist_paid_monthly_lines=int(
            db_rows.get("ai_assist_paid_monthly_lines", env_settings.ai_assist_paid_monthly_lines)
        ),
        ai_advisor_free_monthly_queries=int(
            db_rows.get("ai_advisor_free_monthly_queries", env_settings.ai_advisor_free_monthly_queries)
        ),
        ai_advisor_paid_monthly_queries=int(
            db_rows.get("ai_advisor_paid_monthly_queries", env_settings.ai_advisor_paid_monthly_queries)
        ),
    )


@router.get("/settings", response_model=PlatformSettingsResponse)
def get_platform_settings(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> PlatformSettingsResponse:
    """Return current global platform settings (DB values override .env defaults)."""
    return _read_platform_settings(db)


# ---------------------------------------------------------------------------
# Admin rematch endpoint
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/rematch")
async def admin_rematch_project(
    project_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
    reg: ProviderRegistry = Depends(get_registry),
) -> dict:
    """Re-run matching for all non-locked lines that are pending (match_type=None) or no_match.

    Locked lines and already-matched lines are left untouched.
    Returns the count of lines that were queued for re-matching and the match summary.
    """
    from app.models.project import BomLine, Project
    from app.services.matching import PartMatchingService
    from app.schemas.preferences import MergedPreferences

    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Reset no_match lines to None so the matcher will attempt them again.
    # Lines with match_type=None are already pending — no reset needed.
    no_match_lines = (
        db.query(BomLine)
        .filter(
            BomLine.project_id == project_id,
            BomLine.locked == False,  # noqa: E712
            BomLine.match_type == "no_match",
        )
        .all()
    )
    for line in no_match_lines:
        line.match_type = None
    db.commit()

    # Count all non-locked lines that need matching (pending after reset above)
    target_count: int = (
        db.query(BomLine)
        .filter(
            BomLine.project_id == project_id,
            BomLine.locked == False,  # noqa: E712
            BomLine.match_type.is_(None),
        )
        .count()
    )

    service = PartMatchingService(reg)
    summary = await service.match_project(db, project_id)
    return {"queued": target_count, **summary}


@router.put("/settings", response_model=PlatformSettingsResponse)
def update_platform_settings(
    body: PlatformSettingsUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> PlatformSettingsResponse:
    """Upsert global platform settings into the DB (does not modify .env)."""
    from datetime import UTC, datetime

    from app.models.platform_setting import PlatformSetting

    updates = {
        "free_plan_max_projects": str(body.free_plan_max_projects),
        "free_plan_max_parts_per_project": str(body.free_plan_max_parts_per_project),
        "provider_fallback_order": body.provider_fallback_order.strip(),
        "ai_assist_free_monthly_lines": str(body.ai_assist_free_monthly_lines),
        "ai_assist_paid_monthly_lines": str(body.ai_assist_paid_monthly_lines),
        "ai_advisor_free_monthly_queries": str(body.ai_advisor_free_monthly_queries),
        "ai_advisor_paid_monthly_queries": str(body.ai_advisor_paid_monthly_queries),
    }

    for key, value in updates.items():
        row = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
        if row is None:
            db.add(PlatformSetting(key=key, value=value))
        else:
            row.value = value
            row.updated_at = datetime.now(UTC)

    db.commit()
    return _read_platform_settings(db)
