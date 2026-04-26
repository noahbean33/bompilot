from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

from app.core.database import Base


class PaddleEvent(Base):
    __tablename__ = "paddle_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, nullable=False, index=True, unique=True)
    event_type = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_paddle_events_event_id"),
    )
