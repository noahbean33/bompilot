import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"
REFRESH_URL = "/auth/refresh"
LOGOUT_URL = "/auth/logout"
ME_URL = "/auth/me"

EMAIL = "test@example.com"
PASSWORD = "securepassword123"


def _register(client: TestClient):
    return client.post(REGISTER_URL, json={"email": EMAIL, "name": "Test User"})


def _set_password(client: TestClient, db_session, email: str, password: str) -> None:
    from app.models.password_reset_token import PasswordResetToken
    from app.models.user import User
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


def _login(client: TestClient):
    return client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_success(client: TestClient):
    response = _register(client)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == EMAIL
    assert data["subscription_tier"] == "free"
    assert data["is_active"] is True
    assert "id" in data
    assert "hashed_password" not in data


def test_register_duplicate_email(client: TestClient):
    _register(client)
    response = _register(client)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


def test_register_invalid_email(client: TestClient):
    response = client.post(REGISTER_URL, json={"email": "not-an-email", "name": "Test User"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_success(client: TestClient, db_session):
    _register(client)
    _set_password(client, db_session, EMAIL, PASSWORD)
    response = _login(client)
    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert "access_token" in data
    assert "refresh_token" in client.cookies


def test_login_wrong_password(client: TestClient, db_session):
    _register(client)
    _set_password(client, db_session, EMAIL, PASSWORD)
    response = client.post(LOGIN_URL, json={"email": EMAIL, "password": "wrongpassword"})
    assert response.status_code == 401


def test_login_nonexistent_user(client: TestClient):
    response = client.post(LOGIN_URL, json={"email": "nobody@example.com", "password": "pass"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------


def test_me_authenticated(client: TestClient, db_session):
    _register(client)
    _set_password(client, db_session, EMAIL, PASSWORD)
    token = _login(client).json()["access_token"]
    response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


def test_me_unauthenticated(client: TestClient):
    assert client.get(ME_URL).status_code == 401


def test_me_invalid_token(client: TestClient):
    response = client.get(ME_URL, headers={"Authorization": "Bearer invalidtoken"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


def test_refresh_token(client: TestClient, db_session):
    _register(client)
    _set_password(client, db_session, EMAIL, PASSWORD)
    _login(client)  # sets refresh_token cookie on client

    response = client.post(REFRESH_URL)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "refresh_token" in client.cookies


def test_refresh_token_missing_cookie(client: TestClient):
    response = client.post(REFRESH_URL)
    assert response.status_code == 401
    assert "missing" in response.json()["detail"].lower()


def test_refresh_then_use_new_access_token(client: TestClient, db_session):
    _register(client)
    _set_password(client, db_session, EMAIL, PASSWORD)
    _login(client)

    new_access_token = client.post(REFRESH_URL).json()["access_token"]
    response = client.get(ME_URL, headers={"Authorization": f"Bearer {new_access_token}"})
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout(client: TestClient, db_session):
    _register(client)
    _set_password(client, db_session, EMAIL, PASSWORD)
    _login(client)
    assert "refresh_token" in client.cookies

    response = client.post(LOGOUT_URL)
    assert response.status_code == 200

    # After logout the refresh cookie should be cleared
    response = client.post(REFRESH_URL)
    assert response.status_code == 401
