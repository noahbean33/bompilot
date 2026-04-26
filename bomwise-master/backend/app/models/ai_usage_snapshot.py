from sqlalchemy import Column, Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class AiUsageSnapshot(Base):
    __tablename__ = "ai_usage_snapshot"
    __table_args__ = (
        UniqueConstraint("date", "feature", name="uq_ai_usage_snapshot_date_feature"),
    )

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    feature = Column(String(50), nullable=False)  # nl_query | ai_assist | ai_advisor
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    input_cost_usd = Column(Float, nullable=False, default=0)
    output_cost_usd = Column(Float, nullable=False, default=0)
    snapshot_at = Column(DateTime(timezone=True), server_default=func.now())