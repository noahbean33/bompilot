from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class PartAlternative(Base):
    __tablename__ = "part_alternatives"

    id = Column(Integer, primary_key=True, index=True)
    bom_line_id = Column(Integer, ForeignKey("bom_lines.id"), nullable=False, index=True)
    mpn = Column(String, nullable=False)
    manufacturer = Column(String, nullable=True)
    description = Column(String, nullable=True)
    package = Column(String, nullable=True)
    distributor = Column(String, nullable=True)
    stock = Column(Integer, nullable=True)
    datasheet_url = Column(String, nullable=True)
    source = Column(String, nullable=False)
    match_score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
