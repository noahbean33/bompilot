"""
Pydantic schemas for user and project preferences.
"""

from datetime import datetime

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------


class NlPresetFilter(BaseModel):
    field: str
    op: str
    value: str | int | float | bool | None = None


class NlPresetSchema(BaseModel):
    label: str
    filters: list[NlPresetFilter]
    highlightOnly: bool = False


class UserPreferencesRead(BaseModel):
    id: int
    user_id: int
    preferred_currency: str
    preferred_distributors: list[str]
    preferred_nl_presets: list[NlPresetSchema] = []
    auto_lock_parts: bool
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserPreferencesUpdate(BaseModel):
    preferred_currency: str | None = None
    preferred_distributors: list[str] | None = None
    preferred_nl_presets: list[NlPresetSchema] | None = None
    auto_lock_parts: bool | None = None


# ---------------------------------------------------------------------------
# Project preferences
# ---------------------------------------------------------------------------


class ProjectPreferencesRead(BaseModel):
    id: int
    project_id: int
    preferred_currency: str | None = None
    preferred_distributors: list[str] | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProjectPreferencesUpdate(BaseModel):
    preferred_currency: str | None = None
    preferred_distributors: list[str] | None = None


# ---------------------------------------------------------------------------
# Merged / effective preferences (returned by PreferencesService)
# ---------------------------------------------------------------------------


class MergedPreferences(BaseModel):
    preferred_currency: str = "USD"
    preferred_distributors: list[str] = []
