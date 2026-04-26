from typing import Any

from sqlalchemy.orm import Session

from app.models.preferences import UserPreferences
from app.models.project import ProjectPreferences

_SYSTEM_DEFAULTS: dict[str, Any] = {
    "preferred_currency": "USD",
    "preferred_distributors": [],
    "preferred_nl_presets": [],
    "auto_lock_parts": True,
}


class PreferencesService:
    # ------------------------------------------------------------------
    # User preferences
    # ------------------------------------------------------------------

    @staticmethod
    def get_user_preferences(db: Session, user_id: int) -> UserPreferences:
        """Return user's global preferences, creating defaults if none exist."""
        prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
        if prefs is None:
            prefs = UserPreferences(
                user_id=user_id,
                preferred_currency=_SYSTEM_DEFAULTS["preferred_currency"],
                preferred_distributors=list(_SYSTEM_DEFAULTS["preferred_distributors"]),
                preferred_nl_presets=list(_SYSTEM_DEFAULTS["preferred_nl_presets"]),
                auto_lock_parts=_SYSTEM_DEFAULTS["auto_lock_parts"],
            )
            db.add(prefs)
            db.commit()
            db.refresh(prefs)
        return prefs

    @staticmethod
    def update_user_preferences(
        db: Session,
        user_id: int,
        preferred_currency: str | None,
        preferred_distributors: list[str] | None,
        preferred_nl_presets: list[dict] | None = None,
        auto_lock_parts: bool | None = None,
    ) -> UserPreferences:
        prefs = PreferencesService.get_user_preferences(db, user_id)
        if preferred_currency is not None:
            prefs.preferred_currency = preferred_currency
        if preferred_distributors is not None:
            prefs.preferred_distributors = preferred_distributors
        if preferred_nl_presets is not None:
            prefs.preferred_nl_presets = preferred_nl_presets
        if auto_lock_parts is not None:
            prefs.auto_lock_parts = auto_lock_parts
        db.commit()
        db.refresh(prefs)
        return prefs

    # ------------------------------------------------------------------
    # Project preferences
    # ------------------------------------------------------------------

    @staticmethod
    def get_project_preferences(db: Session, project_id: int) -> ProjectPreferences | None:
        return (
            db.query(ProjectPreferences)
            .filter(ProjectPreferences.project_id == project_id)
            .first()
        )

    @staticmethod
    def get_or_create_project_preferences(db: Session, project_id: int) -> ProjectPreferences:
        prefs = PreferencesService.get_project_preferences(db, project_id)
        if prefs is None:
            prefs = ProjectPreferences(project_id=project_id)
            db.add(prefs)
            db.commit()
            db.refresh(prefs)
        return prefs

    @staticmethod
    def update_project_preferences(
        db: Session,
        project_id: int,
        preferred_currency: str | None,
        preferred_distributors: list[str] | None,
    ) -> ProjectPreferences:
        prefs = PreferencesService.get_or_create_project_preferences(db, project_id)
        if preferred_currency is not None:
            prefs.preferred_currency = preferred_currency
        if preferred_distributors is not None:
            prefs.preferred_distributors = preferred_distributors
        db.commit()
        db.refresh(prefs)
        return prefs

    # ------------------------------------------------------------------
    # Merged / effective preferences
    # ------------------------------------------------------------------

    @staticmethod
    def get_effective_preferences(
        db: Session, user_id: int, project_id: int
    ) -> dict[str, Any]:
        """
        Merge preferences in priority order (highest wins):
          project overrides  >  user preferences  >  system defaults
        """
        user_prefs = PreferencesService.get_user_preferences(db, user_id)
        project_prefs = PreferencesService.get_project_preferences(db, project_id)

        # Start with user prefs (which already fall back to system defaults on creation)
        result: dict[str, Any] = {
            "preferred_currency": user_prefs.preferred_currency,
            "preferred_distributors": list(user_prefs.preferred_distributors or []),
        }

        # Project overrides win where set
        if project_prefs is not None:
            if project_prefs.preferred_currency is not None:
                result["preferred_currency"] = project_prefs.preferred_currency
            if project_prefs.preferred_distributors is not None:
                result["preferred_distributors"] = list(project_prefs.preferred_distributors)

        return result
