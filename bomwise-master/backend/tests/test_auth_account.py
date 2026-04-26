"""
Tests for account management endpoints:
  - POST /auth/forgot-password
  - POST /auth/reset-password
  - POST /auth/change-password
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register(client: TestClient, email: str, name: str = "Test User") -> None:
    """Register a user (suppresses SMTP so tests don't need a mail server)."""
    with patch("app.worker.email._send_smtp"):
        client.post(REGISTER_URL, json={"email": email, "name": name})


def _register_and_login(client: TestClient, db_session, email: str, password: str = "password123") -> str:
    """Register user, set password via reset token, then login."""
    from app.models.password_reset_token import PasswordResetToken
    from app.models.user import User

    _register(client, email)
    user = db_session.query(User).filter(User.email == email).first()

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    db_session.add(PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    ))
    db_session.commit()

    client.post("/auth/reset-password", json={"token": raw_token, "new_password": password})
    resp = client.post(LOGIN_URL, json={"email": email, "password": password})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# forgot-password
# ---------------------------------------------------------------------------

class TestForgotPassword:
    def test_always_returns_200_for_unknown_email(self, client: TestClient):
        resp = client.post(
            "/auth/forgot-password", json={"email": "nobody@example.com"}
        )
        assert resp.status_code == 200
        assert "reset link" in resp.json()["detail"].lower()

    def test_returns_200_for_registered_email(self, client: TestClient):
        _register(client, "alice@example.com")
        with patch("app.worker.email._send_smtp"):
            resp = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
        assert resp.status_code == 200

    def test_does_not_leak_existence_of_email(self, client: TestClient):
        """Both registered and unknown emails get the same response body."""
        _register(client, "exists@example.com")
        with patch("app.worker.email._send_smtp"):
            r1 = client.post("/auth/forgot-password", json={"email": "exists@example.com"})
        r2 = client.post("/auth/forgot-password", json={"email": "doesntexist@example.com"})
        assert r1.status_code == r2.status_code == 200
        assert r1.json()["detail"] == r2.json()["detail"]


# ---------------------------------------------------------------------------
# reset-password
# ---------------------------------------------------------------------------

class TestResetPassword:
    def test_reset_with_valid_token(self, client: TestClient, db_session):
        from app.models.password_reset_token import PasswordResetToken
        from app.models.user import User

        _register(client, "bob@example.com", "oldpass123")
        user = db_session.query(User).filter(User.email == "bob@example.com").first()

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        db_session.add(PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ))
        db_session.commit()

        resp = client.post(
            "/auth/reset-password",
            json={"token": raw_token, "new_password": "newpassword123"},
        )
        assert resp.status_code == 200

        # Old password no longer works
        assert client.post(LOGIN_URL, json={"email": "bob@example.com", "password": "oldpass123"}).status_code == 401
        # New password works
        assert client.post(LOGIN_URL, json={"email": "bob@example.com", "password": "newpassword123"}).status_code == 200

    def test_reset_fails_on_expired_token(self, client: TestClient, db_session):
        from app.models.password_reset_token import PasswordResetToken
        from app.models.user import User

        _register(client, "carol@example.com", "oldpass123")
        user = db_session.query(User).filter(User.email == "carol@example.com").first()

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        db_session.add(PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) - timedelta(hours=2),  # already expired
        ))
        db_session.commit()

        resp = client.post(
            "/auth/reset-password",
            json={"token": raw_token, "new_password": "newpassword123"},
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_reset_fails_on_invalid_token(self, client: TestClient):
        resp = client.post(
            "/auth/reset-password",
            json={"token": "completely-wrong-token", "new_password": "newpassword123"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# change-password
# ---------------------------------------------------------------------------

class TestChangePassword:
    def test_change_password_success(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "dave@example.com", "oldpass123")
        resp = client.post(
            "/auth/change-password",
            json={"current_password": "oldpass123", "new_password": "newpass456"},
            headers=_auth(token),
        )
        assert resp.status_code == 200

        # Old password no longer works
        assert client.post(LOGIN_URL, json={"email": "dave@example.com", "password": "oldpass123"}).status_code == 401
        # New password works
        assert client.post(LOGIN_URL, json={"email": "dave@example.com", "password": "newpass456"}).status_code == 200

    def test_change_password_fails_if_current_wrong(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "eve@example.com", "correct123")
        resp = client.post(
            "/auth/change-password",
            json={"current_password": "wrongpassword", "new_password": "doesntmatter"},
            headers=_auth(token),
        )
        assert resp.status_code == 400
        assert "incorrect" in resp.json()["detail"].lower()

    def test_change_password_requires_auth(self, client: TestClient):
        resp = client.post(
            "/auth/change-password",
            json={"current_password": "old", "new_password": "new"},
        )
        assert resp.status_code == 401


# Email verification endpoints removed — password-set email now auto-verifies on reset
