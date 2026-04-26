from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text
from sqlalchemy import JSON
from sqlalchemy.sql import func

from app.core.database import Base


class AiAdvisorCache(Base):
    __tablename__ = "ai_advisor_cache"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mpn_hash = Column(String(32), unique=True, nullable=False, index=True)
    mpns = Column(JSON, nullable=False)
    bom_context = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=True)
    recommendation = Column(String(255), nullable=True)
    reasoning = Column(Text, nullable=True)
    input_tokens = Column(Integer, nullable=False, server_default="0")
    output_tokens = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_accessed = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    access_count = Column(Integer, nullable=False, server_default="0")