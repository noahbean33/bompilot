from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.project import BomLine, Project
from app.models.user import User
from app.schemas.preferences import UserPreferencesRead, UserPreferencesUpdate
from app.services.preferences import PreferencesService
from pydantic import BaseModel

router = APIRouter()


# ---------------------------------------------------------------------------
# Usage endpoint
# ---------------------------------------------------------------------------

class UserUsageSummary(BaseModel):
    period: str
    start_date: str
    end_date: str
    projects_count: int
    bom_lines_total: int
    matched_lines: int
    ai_assist_lines_db: int
    ai_assist_lines_monthly: int
    ai_advisor_queries_monthly: int
    time_saved_minutes: int
    time_saved_note: str


@router.get("/me/usage", response_model=UserUsageSummary)
async def get_user_usage(
    period: str = Query("week", pattern="^(day|week|month|year)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserUsageSummary:
    """Return the current user's usage summary for the given time period."""
    # Compute date range
    now = datetime.now(UTC)
    if period == "day":
        start = now - timedelta(days=1)
    elif period == "week":
        start = now - timedelta(weeks=1)
    elif period == "month":
        start = now - timedelta(days=30)
    else:  # year
        start = now - timedelta(days=365)
    end = now

    # Projects count (all-time, not date-filtered, since projects don't have meaningful date range queries)
    projects_count: int = (
        db.query(sqlfunc.count(Project.id))
        .filter(Project.user_id == current_user.id)
        .scalar() or 0
    )

    # BOM lines count (all-time)
    bom_lines_total: int = (
        db.query(sqlfunc.count(BomLine.id))
        .join(Project, Project.id == BomLine.project_id)
        .filter(Project.user_id == current_user.id)
        .scalar() or 0
    )

    # Matched lines (all-time)
    matched_lines: int = (
        db.query(sqlfunc.count(BomLine.id))
        .join(Project, Project.id == BomLine.project_id)
        .filter(
            Project.user_id == current_user.id,
            BomLine.selected_result_id.isnot(None),
        )
        .scalar() or 0
    )

    # AI assist lines from DB (all-time)
    _AI_MATCH_TYPES = ("ai_suggested", "no_part_needed")
    ai_assist_lines_db: int = (
        db.query(sqlfunc.count(BomLine.id))
        .join(Project, Project.id == BomLine.project_id)
        .filter(
            Project.user_id == current_user.id,
            BomLine.match_type.in_(_AI_MATCH_TYPES),
        )
        .scalar() or 0
    )

    # Redis monthly counters (current month only)
    ai_assist_lines_monthly = await _redis_get_ai_assist_lines(current_user.id)
    ai_advisor_queries_monthly = await _redis_get_ai_advisor_queries(current_user.id)

    # Time-saved heuristic
    # assumes ~2min per matched part (manual search) + ~5min per AI assist
    time_saved = (matched_lines * 2) + (ai_assist_lines_db * 5)
    time_saved_note = (
        "Estimate: matched parts × 2 min + AI assist lines × 5 min. "
        "Actual time saved depends on part complexity."
    )

    return UserUsageSummary(
        period=period,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        projects_count=projects_count,
        bom_lines_total=bom_lines_total,
        matched_lines=matched_lines,
        ai_assist_lines_db=ai_assist_lines_db,
        ai_assist_lines_monthly=ai_assist_lines_monthly,
        ai_advisor_queries_monthly=ai_advisor_queries_monthly,
        time_saved_minutes=time_saved,
        time_saved_note=time_saved_note,
    )


# ---------------------------------------------------------------------------
# Redis helpers for usage
# ---------------------------------------------------------------------------

async def _redis_get_ai_assist_lines(user_id: int) -> int:
    """Read current-month AI Assist line counter from Redis."""
    month = datetime.now(UTC).strftime("%Y-%m")
    return await _redis_get_int_key(f"ai:assist:{user_id}:lines:{month}")


async def _redis_get_ai_advisor_queries(user_id: int) -> int:
    """Read current-month AI Advisor query counter from Redis."""
    month = datetime.now(UTC).strftime("%Y-%m")
    return await _redis_get_int_key(f"ai:advisor:queries:{user_id}:{month}")


async def _redis_get_int_key(key: str) -> int:
    """Generic async Redis read → int, best-effort."""
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings
        client = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=1.0
        )
        value = await client.get(key)
        await client.aclose()
        try:
            return int(value) if value is not None else 0
        except (ValueError, TypeError):
            return 0
    except Exception:
        return 0


@router.get("/me/preferences", response_model=UserPreferencesRead)
def get_my_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return PreferencesService.get_user_preferences(db, user_id=current_user.id)


@router.put("/me/preferences", response_model=UserPreferencesRead)
def update_my_preferences(
    body: UserPreferencesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return PreferencesService.update_user_preferences(
        db,
        user_id=current_user.id,
        preferred_currency=body.preferred_currency,
        preferred_distributors=body.preferred_distributors,
        preferred_nl_presets=(
            [p.model_dump() for p in body.preferred_nl_presets]
            if body.preferred_nl_presets is not None
            else None
        ),
        auto_lock_parts=body.auto_lock_parts,
    )
