"""
Tests for the provider error log feature.

Covers:
  - log_provider_error writes a ProviderErrorLog row
  - GET /admin/providers/{name}/errors returns only entries within 24 h
  - limit cap: requesting 600 returns at most 500
  - DELETE /admin/providers/{name}/errors clears only the named provider's entries
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.models.password_reset_token import PasswordResetToken
from app.models.provider_error_log import ProviderErrorLog
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_admin.py)
# ---------------------------------------------------------------------------

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"


def _register_and_login(client: TestClient, db_session, email: str, password: str = "pass1234") -> str:
    # 1. Register with email and name (no password)
    client.post(REGISTER_URL, json={"email": email, "name": "Test User"})

    # 2. Get the newly created user
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None

    # 3. Create a PasswordResetToken
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    db_session.add(PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))
    db_session.commit()

    # 4. Reset password using the token
    client.post("/auth/reset-password", json={"token": raw_token, "new_password": password})

    # 5. Login
    resp = client.post(LOGIN_URL, json={"email": email, "password": password})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_admin(db_session, email: str) -> None:
    from app.models.user import User
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    user.is_admin = True
    db_session.commit()


def _insert_error(
    db_session,
    provider_name: str = "oemsecrets",
    error_type: str = "http_error",
    message: str = "Test error",
    status_code: int | None = 500,
    occurred_at: datetime | None = None,
) -> ProviderErrorLog:
    entry = ProviderErrorLog(
        provider_name=provider_name,
        error_type=error_type,
        message=message,
        status_code=status_code,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# 1. log_provider_error writes a row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_provider_error_writes_row(db_session):
    """log_provider_error should insert a ProviderErrorLog row."""
    from app.core.database import SessionLocal
    from app.services.provider_error_logger import log_provider_error

    with patch("app.services.provider_error_logger.SessionLocal", return_value=db_session):
        # Prevent the finally-block double-close from crashing the test session
        original_close = db_session.close
        db_session.close = lambda: None
        try:
            await log_provider_error(
                provider_name="mouser",
                error_type="timeout",
                message="Connection timed out",
                status_code=None,
            )
        finally:
            db_session.close = original_close

    rows = db_session.query(ProviderErrorLog).filter(
        ProviderErrorLog.provider_name == "mouser"
    ).all()
    assert len(rows) == 1
    assert rows[0].error_type == "timeout"
    assert rows[0].message == "Connection timed out"
    assert rows[0].status_code is None


# ---------------------------------------------------------------------------
# 2. GET endpoint returns only entries within 24 h
# ---------------------------------------------------------------------------


class TestGetProviderErrors:
    def test_returns_only_24h_entries(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "admin1@example.com")
        _make_admin(db_session, "admin1@example.com")

        # Recent entry (within 24 h)
        _insert_error(db_session, provider_name="nexar", occurred_at=datetime.now(UTC))
        # Old entry (outside 24 h)
        _insert_error(
            db_session,
            provider_name="nexar",
            occurred_at=datetime.now(UTC) - timedelta(hours=25),
        )

        resp = client.get("/admin/providers/nexar/errors", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["provider_name"] == "nexar"
        assert body["total_in_24h"] == 1
        assert len(body["errors"]) == 1

    def test_requires_admin(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "regular@example.com")
        resp = client.get("/admin/providers/nexar/errors", headers=_auth(token))
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self, client: TestClient):
        resp = client.get("/admin/providers/nexar/errors")
        assert resp.status_code == 401

    def test_empty_provider_returns_zero(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "admin2@example.com")
        _make_admin(db_session, "admin2@example.com")

        resp = client.get("/admin/providers/digikey/errors", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_in_24h"] == 0
        assert body["errors"] == []


# ---------------------------------------------------------------------------
# 3. limit cap: requesting >500 is capped at 500
# ---------------------------------------------------------------------------


class TestLimitCap:
    def test_limit_600_capped_to_500(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "admin3@example.com")
        _make_admin(db_session, "admin3@example.com")

        # Insert 510 entries for "mouser" within 24 h
        for i in range(510):
            db_session.add(ProviderErrorLog(
                provider_name="mouser",
                error_type="http_error",
                message=f"error {i}",
                status_code=500,
                occurred_at=datetime.now(UTC),
            ))
        db_session.commit()

        # limit=600 should be rejected with 422 (Query validator caps at 500)
        resp = client.get(
            "/admin/providers/mouser/errors?limit=600", headers=_auth(token)
        )
        assert resp.status_code == 422  # FastAPI validation error — above max

    def test_limit_500_returns_500_rows(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "admin4@example.com")
        _make_admin(db_session, "admin4@example.com")

        for i in range(510):
            db_session.add(ProviderErrorLog(
                provider_name="mouser2",
                error_type="http_error",
                message=f"error {i}",
                status_code=500,
                occurred_at=datetime.now(UTC),
            ))
        db_session.commit()

        resp = client.get(
            "/admin/providers/mouser2/errors?limit=500", headers=_auth(token)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["errors"]) == 500
        assert body["total_in_24h"] == 510  # total count ignores limit


# ---------------------------------------------------------------------------
# 4. DELETE clears only the named provider's entries
# ---------------------------------------------------------------------------


class TestDeleteProviderErrors:
    def test_delete_clears_only_named_provider(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "admin5@example.com")
        _make_admin(db_session, "admin5@example.com")

        _insert_error(db_session, provider_name="oemsecrets")
        _insert_error(db_session, provider_name="oemsecrets")
        _insert_error(db_session, provider_name="nexar")  # different provider

        resp = client.delete("/admin/providers/oemsecrets/errors", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2

        # nexar entry must be untouched
        remaining = db_session.query(ProviderErrorLog).all()
        assert len(remaining) == 1
        assert remaining[0].provider_name == "nexar"

    def test_delete_requires_admin(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "regular2@example.com")
        resp = client.delete("/admin/providers/oemsecrets/errors", headers=_auth(token))
        assert resp.status_code == 403

    def test_delete_empty_returns_zero(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "admin6@example.com")
        _make_admin(db_session, "admin6@example.com")

        resp = client.delete("/admin/providers/nonexistent/errors", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0
