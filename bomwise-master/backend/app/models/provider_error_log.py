from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class ProviderErrorLog(Base):
    """Structured error log entries captured from provider API calls."""

    __tablename__ = "provider_error_logs"

    id = Column(Integer, primary_key=True, index=True)
    provider_name = Column(String, nullable=False, index=True)
    error_type = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    status_code = Column(Integer, nullable=True)
    occurred_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        Index("ix_provider_error_logs_name_occurred", "provider_name", "occurred_at"),
    )
