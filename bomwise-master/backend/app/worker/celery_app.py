from datetime import timedelta

from celery import Celery

from app.core.database import settings

celery = Celery(
    "bomexplorer",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "monitor-parts-daily": {
            "task": "app.worker.tasks.monitor_parts",
            "schedule": timedelta(hours=24),
        },
        "send-digest-emails-daily": {
            "task": "app.worker.tasks.send_digest_emails",
            "schedule": timedelta(hours=24),
        },
        "cleanup-provider-error-logs": {
            "task": "app.worker.tasks.cleanup_provider_error_logs",
            "schedule": timedelta(hours=6),
        },
        "snapshot-daily-ai-usage": {
            "task": "app.worker.tasks.snapshot_daily_ai_usage",
            "schedule": timedelta(hours=24),
            "kwargs": {"days_ago": 1},
        },
        "check-trial-expiry-warnings": {
            "task": "app.worker.tasks.check_trial_expiry_warnings",
            "schedule": timedelta(hours=24),
        },
        "check-trial-expired": {
            "task": "app.worker.tasks.check_trial_expired",
            "schedule": timedelta(hours=24),
        },
    },
)
