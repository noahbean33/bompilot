from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base

# Valid flag_type values
FLAG_OUT_OF_STOCK = "out_of_stock"
FLAG_PRICE_CHANGE = "price_change"


class PartFlag(Base):
    __tablename__ = "part_flags"

    id = Column(Integer, primary_key=True, index=True)
    part_result_id = Column(Integer, ForeignKey("part_results.id"), nullable=False, index=True)
    flag_type = Column(String, nullable=False)  # "out_of_stock" | "price_change"
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    acknowledged = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
