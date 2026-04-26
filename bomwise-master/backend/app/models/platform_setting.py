from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class PlatformSetting(Base):
    """Global admin-editable settings stored as key/value pairs.

    Values in this table override the corresponding .env / Settings defaults.
    Known keys:
      free_plan_max_projects          int
      free_plan_max_parts_per_project int
      provider_fallback_order         str  (comma-separated provider names)
    """

    __tablename__ = "platform_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
