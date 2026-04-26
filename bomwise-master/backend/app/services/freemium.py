"""
Freemium plan enforcement helpers.

get_effective_limits(user, db) is the single source of truth for what a user
is allowed to do.  Enforcement code should call it rather than reading
settings or user fields directly.

Limit resolution order (highest priority first):
  1. Per-user override columns  (max_projects_override, max_parts_per_project_override,
                                  ai_assist_monthly_lines_override)
  2. Platform settings DB table (admin-editable via /admin/settings)
  3. .env / Settings defaults

Limits use None to mean "unlimited" internally.  The .env setting 0 also maps to
None (unlimited) for ai_assist limits, since 0 is the conventional "no cap" value
in the admin UI.

Paid-plan ai_assist_monthly_lines defaults to ai_assist_paid_monthly_lines from
settings (500 unless overridden), not None — paid users still have a ceiling the
admin can adjust.

Trial users (trial_ends_at in the future) are treated as paid users for all
enforcement purposes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.user import User


def _is_trial_active(user: User) -> bool:
    """Return True if user has an active trial period."""
    if user.trial_ends_at is None:
        return False
    trial_end = user.trial_ends_at
    if trial_end.tzinfo is None:
        trial_end = trial_end.replace(tzinfo=UTC)
    return trial_end > datetime.now(UTC)


def _is_trial_expired(user: User) -> bool:
    """Return True if course-provisioned trial has expired."""
    if user.trial_ends_at is None:
        return False
    trial_end = user.trial_ends_at
    if trial_end.tzinfo is None:
        trial_end = trial_end.replace(tzinfo=UTC)
    return trial_end < datetime.now(UTC)


def _zero_to_none(val: int) -> int | None:
    """Convert 0 (admin UI convention for 'unlimited') to None."""
    return None if val == 0 else val


def get_effective_limits(user: User, db: Session | None = None) -> dict[str, int | None]:
    """Return the effective plan limits for *user*.

    Pass *db* to allow admin-set global defaults to take effect.  When *db*
    is None the function falls back to .env / Settings defaults only.

    Returned keys:
      max_projects                – int | None (None = unlimited)
      max_parts_per_project       – int | None
      ai_assist_monthly_lines     – int | None (None = unlimited)
      ai_advisor_monthly_queries  – int | None (None = unlimited)
    """
    from app.core.database import settings  # avoid circular import at module level

    is_paid = user.plan == "paid" or _is_trial_active(user)

    # Course-provisioned trial expired → free-tier, regardless of plan/tier
    # This check runs before per-user override resolution.
    # Does NOT modify plan/subscription_tier — only degrades limit resolution.
    if user.is_trial_provisioned and _is_trial_expired(user):
        is_paid = False

    # -----------------------------------------------------------------------
    # Step 1: start from .env defaults
    # -----------------------------------------------------------------------
    global_max_projects: int = settings.free_plan_max_projects
    global_max_parts: int = settings.free_plan_max_parts_per_project
    global_ai_free: int | None = _zero_to_none(settings.ai_assist_free_monthly_lines)
    global_ai_paid: int | None = _zero_to_none(settings.ai_assist_paid_monthly_lines)
    global_advisor_free: int | None = _zero_to_none(settings.ai_advisor_free_monthly_queries)
    global_advisor_paid: int | None = _zero_to_none(settings.ai_advisor_paid_monthly_queries)

    # -----------------------------------------------------------------------
    # Step 2: DB platform_settings override env defaults
    # -----------------------------------------------------------------------
    if db is not None:
        from app.models.platform_setting import PlatformSetting
        rows = (
            db.query(PlatformSetting)
            .filter(
                PlatformSetting.key.in_([
                    "free_plan_max_projects",
                    "free_plan_max_parts_per_project",
                    "ai_assist_free_monthly_lines",
                    "ai_assist_paid_monthly_lines",
                    "ai_advisor_free_monthly_queries",
                    "ai_advisor_paid_monthly_queries",
                ])
            )
            .all()
        )
        for row in rows:
            try:
                val = int(row.value)
            except (ValueError, TypeError):
                continue
            if row.key == "free_plan_max_projects":
                global_max_projects = val
            elif row.key == "free_plan_max_parts_per_project":
                global_max_parts = val
            elif row.key == "ai_assist_free_monthly_lines":
                global_ai_free = _zero_to_none(val)
            elif row.key == "ai_assist_paid_monthly_lines":
                global_ai_paid = _zero_to_none(val)
            elif row.key == "ai_advisor_free_monthly_queries":
                global_advisor_free = _zero_to_none(val)
            elif row.key == "ai_advisor_paid_monthly_queries":
                global_advisor_paid = _zero_to_none(val)

    # -----------------------------------------------------------------------
    # Step 3: per-user overrides win over globals
    # -----------------------------------------------------------------------
    if is_paid:
        max_projects: int | None = None
        max_parts: int | None = None
        global_ai = global_ai_paid
    else:
        max_projects = (
            user.max_projects_override
            if user.max_projects_override is not None
            else global_max_projects
        )
        max_parts = (
            user.max_parts_per_project_override
            if user.max_parts_per_project_override is not None
            else global_max_parts
        )
        global_ai = global_ai_free

    ai_monthly = (
        _zero_to_none(user.ai_assist_monthly_lines_override)
        if user.ai_assist_monthly_lines_override is not None
        else global_ai
    )

    advisor_global = global_advisor_paid if is_paid else global_advisor_free
    advisor_monthly = (
        _zero_to_none(user.ai_advisor_monthly_queries_override)
        if user.ai_advisor_monthly_queries_override is not None
        else advisor_global
    )

    return {
        "max_projects": max_projects,
        "max_parts_per_project": max_parts,
        "ai_assist_monthly_lines": ai_monthly,
        "ai_advisor_monthly_queries": advisor_monthly,
    }
