from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String

from app.core.database import Base


class PartResult(Base):
    __tablename__ = "part_results"

    id = Column(Integer, primary_key=True, index=True)
    bom_line_id = Column(Integer, ForeignKey("bom_lines.id"), nullable=False, index=True)
    rank = Column(Integer, nullable=False)
    mpn = Column(String, nullable=False)
    manufacturer = Column(String, nullable=False)
    description = Column(String, nullable=True)
    package = Column(String, nullable=True)
    distributor = Column(String, nullable=True)
    unit_price = Column(Float, nullable=True)
    stock = Column(Integer, nullable=False, default=0)
    lifecycle_status = Column(String, nullable=True)
    tech_specs = Column(JSON, nullable=True)
    datasheet_url = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    source_provider = Column(String, nullable=False)
    match_type = Column(String, nullable=False)
    retrieved_at = Column(DateTime(timezone=True), nullable=False)
