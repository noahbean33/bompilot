from sqlalchemy import Boolean, JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    preferred_currency = Column(String, nullable=False, default="USD", server_default="USD")
    preferred_distributors = Column(JSON, nullable=False, default=list, server_default="[]")
    preferred_nl_presets = Column(JSON, nullable=False, default=list, server_default="[]")
    auto_lock_parts = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
