from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    subscription_tier = Column(String, nullable=False, default="free")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    email_verified_at = Column(DateTime(timezone=True), nullable=True)

    # Freemium plan enforcement
    plan = Column(String, nullable=False, default="free")  # "free" | "paid"
    max_projects_override = Column(Integer, nullable=True)
    max_parts_per_project_override = Column(Integer, nullable=True)
    # AI Assist budget: lines/month override (null = use global default)
    ai_assist_monthly_lines_override = Column(Integer, nullable=True)
    # AI Advisor budget: queries/month override (null = use global default)
    ai_advisor_monthly_queries_override = Column(Integer, nullable=True)

    # Admin
    is_admin = Column(Boolean, nullable=False, default=False)

    # Paddle subscription fields
    paddle_customer_id = Column(String, nullable=True)
    paddle_subscription_id = Column(String, nullable=True)
    subscription_status = Column(String, nullable=True)  # active|past_due|cancelled|paused
    subscription_plan = Column(String, nullable=True)    # pro
    subscription_current_period_end = Column(DateTime(timezone=True), nullable=True)
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)

    # Trial provisioning (course bonus via webhook)
    is_trial_provisioned = Column(Boolean, nullable=False, default=False)
    trial_source = Column(String(255), nullable=True)  # e.g., "course-n8n-webhook"
    trial_expiry_email_sent_at = Column(DateTime(timezone=True), nullable=True)

    name = Column(String(255), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
