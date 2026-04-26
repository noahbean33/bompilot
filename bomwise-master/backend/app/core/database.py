from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://user:password@localhost/bomexplorer"
    secret_key: str = "your-secret-key-here"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    environment: str = "development"

    # Provider layer
    component_provider: str = "oemsecrets"
    # Comma-separated fallback chain, e.g. "oemsecrets,mouser,digikey".
    # Takes precedence over component_provider when set.
    provider_fallback_order: str = ""
    nexar_client_id: str = ""
    nexar_client_secret: str = ""
    oemsecrets_api_key: str = ""
    mouser_api_key: str = ""
    digikey_client_id: str = ""
    digikey_client_secret: str = ""
    nextpcb_app_id: str | None = None
    nextpcb_app_secret: str | None = None

    # Freemium plan limits (overridable per-user via DB columns)
    free_plan_max_projects: int = 3
    free_plan_max_parts_per_project: int = 50

    # AI Assist monthly line budget (0 = unlimited)
    ai_assist_free_monthly_lines: int = 50
    ai_assist_paid_monthly_lines: int = 500

    # AI Advisor monthly query budget (0 = unlimited)
    ai_advisor_free_monthly_queries: int = 5
    ai_advisor_paid_monthly_queries: int = 50

    # AI features
    anthropic_api_key: str = ""

    # Celery / Redis
    redis_url: str = "redis://localhost:6379/0"

    # SMTP (for digest emails)
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "noreply@bomexplorer.app"

    # Application base URL (used in email links)
    app_base_url: str = "http://localhost:5173"

    # Paddle Billing
    paddle_api_key: str = ""
    paddle_webhook_secret: str = ""
    paddle_price_id_pro_monthly: str = ""
    paddle_environment: str = "production"  # "sandbox" | "production" — set to sandbox in .env for local dev

    # Internal provisioning
    internal_provisioning_token: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
