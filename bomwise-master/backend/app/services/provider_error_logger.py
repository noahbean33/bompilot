"""
Provider error logging utility.

Captures structured error entries from provider API calls and writes them to
the provider_error_logs table.  All functions are fire-and-forget — errors
during logging are silently swallowed so they never propagate to callers.
"""

from __future__ import annotations

import json
import logging

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


def classify_error(exc: Exception) -> tuple[str, int | None]:
    """Return (error_type, http_status_code) for a provider exception."""
    try:
        import httpx  # type: ignore[import]
        if isinstance(exc, httpx.TimeoutException):
            return "timeout", None
        if isinstance(exc, httpx.HTTPStatusError):
            code: int = exc.response.status_code
            if code in (401, 403):
                return "auth_failure", code
            if code == 429:
                return "rate_limit", code
            return "http_error", code
    except ImportError:
        pass
    if isinstance(exc, (ValueError, KeyError, json.JSONDecodeError)):
        return "parse_error", None
    return "unknown", None


async def log_provider_error(
    provider_name: str,
    error_type: str,
    message: str,
    status_code: int | None = None,
) -> None:
    """Write a ProviderErrorLog row.  Never raises."""
    try:
        from app.models.provider_error_log import ProviderErrorLog

        db = SessionLocal()
        try:
            entry = ProviderErrorLog(
                provider_name=provider_name,
                error_type=error_type,
                message=str(message)[:2000],
                status_code=status_code,
            )
            db.add(entry)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.debug("log_provider_error: failed to write entry: %s", exc)
