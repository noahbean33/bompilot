from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# use_alter defers the bom_lines → part_results FK to an ALTER TABLE statement
# so SQLAlchemy's create_all() can handle the circular dependency cleanly.
_SELECTED_RESULT_FK = ForeignKey(
    "part_results.id",
    use_alter=True,
    name="fk_bom_lines_selected_result_id",
)

from app.core.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    variant_tag = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    bom_lines = relationship(
        "BomLine", back_populates="project", cascade="all, delete-orphan"
    )
    preferences = relationship(
        "ProjectPreferences",
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ProjectPreferences(Base):
    __tablename__ = "project_preferences"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True, index=True)
    preferred_currency = Column(String, nullable=True)
    preferred_distributors = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    project = relationship("Project", back_populates="preferences")


class BomLine(Base):
    __tablename__ = "bom_lines"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    reference = Column(String, nullable=True)
    value = Column(String, nullable=True)
    footprint = Column(String, nullable=True)
    description = Column(String, nullable=True)
    quantity = Column(Integer, nullable=True)
    mpn_raw = Column(String, nullable=True)
    raw_fields = Column(JSON, nullable=False)
    match_type = Column(String, nullable=True)
    selected_result_id = Column(Integer, _SELECTED_RESULT_FK, nullable=True)
    pinned = Column(Boolean, nullable=False, default=False)
    locked = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)
    datasheet_url = Column(String, nullable=True)
    matched_provider = Column(String, nullable=True)
    dnp = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", back_populates="bom_lines")
    selected_result = relationship(
        "PartResult",
        primaryjoin="BomLine.selected_result_id == PartResult.id",
        foreign_keys="[BomLine.selected_result_id]",
        post_update=True,
        lazy="select",
    )
