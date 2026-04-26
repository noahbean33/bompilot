from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class SubstitutionHistory(Base):
    __tablename__ = "substitution_history"

    id = Column(Integer, primary_key=True, index=True)
    bom_line_id = Column(Integer, ForeignKey("bom_lines.id"), nullable=False, index=True)
    from_mpn = Column(String, nullable=True)
    to_mpn = Column(String, nullable=False)
    swapped_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    swapped_by = Column(Integer, ForeignKey("users.id"), nullable=True)
