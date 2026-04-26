"""
Tests for Paddle billing endpoints and webhook handler.

All Paddle API calls and SMTP are mocked — no live network calls.
"""

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"
WEBHOOK_URL = "/webhooks/paddle"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register(client: TestClient, email: str, name: str = "Test User") -> None:
    with patch("app.worker.email._send_smtp"):
        client.post(REGISTER_URL, json={"email": email, "name": name})


def _register_and_login(client: TestClient, db_session, email: str, password: str = "pass123456") -> str:
    _register(client, email)
    from app.models.user import User
    from app.models.password_reset_token import PasswordResetToken

    user = db_session.query(User).filter(User.email == email).first()
    raw_token = f"test-reset-token-{email}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
    db_session.commit()

    client.post("/auth/reset-password", json={"token": raw_token, "new_password": password})
    resp = client.post(LOGIN_URL, json={"email": email, "password": password})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_paddle_sig(body: bytes, secret: str, ts: str = "1234567890") -> str:
    signed = f"{ts}:{body.decode()}"
    h1 = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"ts={ts};h1={h1}"


def _webhook(client: TestClient, payload: dict, secret: str = "") -> object:
    """Send a Paddle webhook. Empty secret bypasses HMAC check."""
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Paddle-Signature"] = _make_paddle_sig(body, secret)
    else:
        # With empty webhook secret, any signature (or none) is accepted
        headers["Paddle-Signature"] = "ts=123;h1=skipped"
    return client.post(WEBHOOK_URL, content=body, headers=headers)


# ---------------------------------------------------------------------------
# GET /billing/subscription
# ---------------------------------------------------------------------------

class TestBillingSubscription:
    def test_returns_subscription_info_for_free_user(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "alice@example.com")
        resp = client.get("/billing/subscription", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["subscription_tier"] == "free"
        assert data["subscription_status"] is None
        assert data["paddle_customer_id"] is None

    def test_requires_auth(self, client: TestClient):
        resp = client.get("/billing/subscription")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /billing/cancel — free user gets 403
# ---------------------------------------------------------------------------

class TestBillingCancel:
    def test_cancel_returns_403_for_free_user(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "bob@example.com")
        resp = client.post("/billing/cancel", headers=_auth(token))
        assert resp.status_code == 403

    def test_cancel_requires_auth(self, client: TestClient):
        resp = client.post("/billing/cancel")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Paddle webhooks
# ---------------------------------------------------------------------------

class TestPaddleWebhook:
    def _activated_payload(self, email: str, event_id: str = "evt-001") -> dict:
        return {
            "event_id": event_id,
            "event_type": "subscription.activated",
            "data": {
                "id": "sub_001",
                "status": "active",
                "customer_id": "cus_001",
                "customer": {"email": email},
                "items": [{"price": {"id": "pri_pro"}}],
                "current_billing_period": {"ends_at": "2026-05-15T00:00:00Z"},
            },
        }

    def test_activated_sets_tier_pro_and_logs_event(self, client: TestClient, db_session):
        from app.models.user import User
        from app.models.paddle_event import PaddleEvent

        _register(client, "carol@example.com")

        # Disable signature checking for this test
        with patch("app.api.webhooks.settings") as ms:
            ms.paddle_webhook_secret = ""
            resp = _webhook(client, self._activated_payload("carol@example.com", "evt-001"))

        assert resp.status_code == 200

        user = db_session.query(User).filter(User.email == "carol@example.com").first()
        db_session.refresh(user)
        assert user.subscription_tier == "pro"
        assert user.plan == "paid"
        assert user.subscription_status == "active"

        event = db_session.query(PaddleEvent).filter(PaddleEvent.event_id == "evt-001").first()
        assert event is not None
        assert event.event_type == "subscription.activated"

    def test_duplicate_event_id_is_ignored(self, client: TestClient, db_session):
        from app.models.paddle_event import PaddleEvent

        _register(client, "dave@example.com")
        payload = self._activated_payload("dave@example.com", event_id="evt-dup-001")

        with patch("app.api.webhooks.settings") as ms:
            ms.paddle_webhook_secret = ""
            r1 = _webhook(client, payload)
            r2 = _webhook(client, payload)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.json()["status"] == "already_processed"

        count = db_session.query(PaddleEvent).filter(
            PaddleEvent.event_id == "evt-dup-001"
        ).count()
        assert count == 1

    def test_cancelled_does_not_immediately_downgrade_tier(self, client: TestClient, db_session):
        from app.models.user import User

        _register(client, "eve@example.com")

        # Activate first
        with patch("app.api.webhooks.settings") as ms:
            ms.paddle_webhook_secret = ""
            _webhook(client, self._activated_payload("eve@example.com", "evt-act-001"))

        user = db_session.query(User).filter(User.email == "eve@example.com").first()
        db_session.refresh(user)
        assert user.subscription_tier == "pro"

        # Cancel
        cancel_payload = {
            "event_id": "evt-cancel-001",
            "event_type": "subscription.canceled",
            "data": {
                "id": "sub_001",
                "status": "canceled",
                "customer": {"email": "eve@example.com"},
                "current_billing_period": {"ends_at": "2026-05-15T00:00:00Z"},
            },
        }
        with patch("app.api.webhooks.settings") as ms:
            ms.paddle_webhook_secret = ""
            with patch("app.api.webhooks._handle_subscription_canceled") as mock_handler:
                # Call the real handler but also mock the Celery task
                from app.api.webhooks import _handle_subscription_canceled as real_handler

                def side_effect(db, data):
                    with patch("app.worker.tasks.downgrade_to_free") as mock_task:
                        mock_task.apply_async = MagicMock()
                        real_handler(db, data)

                mock_handler.side_effect = side_effect
                resp = _webhook(client, cancel_payload)

        assert resp.status_code == 200
        db_session.refresh(user)
        # Tier must NOT be downgraded yet
        assert user.subscription_tier == "pro"
        assert user.subscription_status == "cancelled"

    def test_invalid_signature_returns_400(self, client: TestClient):
        payload = {
            "event_id": "evt-bad-sig",
            "event_type": "subscription.activated",
            "data": {},
        }
        body = json.dumps(payload).encode()
        with patch("app.api.webhooks.settings") as ms:
            ms.paddle_webhook_secret = "real-secret"
            resp = client.post(
                WEBHOOK_URL,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "Paddle-Signature": "ts=1234;h1=wrong-hash",
                },
            )
        assert resp.status_code == 400

    def test_paused_downgrades_tier(self, client: TestClient, db_session):
        from app.models.user import User

        _register(client, "frank@example.com")

        # Activate first
        with patch("app.api.webhooks.settings") as ms:
            ms.paddle_webhook_secret = ""
            _webhook(client, self._activated_payload("frank@example.com", "evt-act-002"))

        user = db_session.query(User).filter(User.email == "frank@example.com").first()
        db_session.refresh(user)
        assert user.subscription_tier == "pro"

        pause_payload = {
            "event_id": "evt-pause-001",
            "event_type": "subscription.paused",
            "data": {
                "id": "sub_001",
                "status": "paused",
                "customer": {"email": "frank@example.com"},
            },
        }
        with patch("app.api.webhooks.settings") as ms:
            ms.paddle_webhook_secret = ""
            resp = _webhook(client, pause_payload)

        assert resp.status_code == 200
        db_session.refresh(user)
        assert user.subscription_tier == "free"
        assert user.subscription_status == "paused"


# ---------------------------------------------------------------------------
# POST /billing/internal/provision-trial
# ---------------------------------------------------------------------------

PROVISION_URL = "/billing/internal/provision-trial"
TEST_INTERNAL_TOKEN = "test-internal-secret"


class TestProvisionTrial:
    """Tests for the internal trial provisioning endpoint."""

    def _headers(self, token: str | None = None) -> dict:
        if token is not None:
            return {"X-Internal-Token": token}
        return {}

    # --- Auth / token validation ---

    def test_missing_token_returns_401(self, client: TestClient):
        resp = client.post(PROVISION_URL, json={"email": "a@b.com"})
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, client: TestClient):
        resp = client.post(
            PROVISION_URL,
            json={"email": "a@b.com"},
            headers={"X-Internal-Token": "wrong-token"},
        )
        assert resp.status_code == 401

    def test_empty_token_returns_401(self, client: TestClient):
        resp = client.post(
            PROVISION_URL,
            json={"email": "a@b.com"},
            headers={"X-Internal-Token": ""},
        )
        assert resp.status_code == 401

    # --- New user creation ---

    def test_new_user_created_with_pro_trial(self, client: TestClient, db_session):
        from app.models.user import User
        from app.models.password_reset_token import PasswordResetToken

        with patch("app.api.billing.INTERNAL_TOKEN", TEST_INTERNAL_TOKEN):
            with patch("app.worker.email._send_smtp"):
                resp = client.post(
                    PROVISION_URL,
                    json={
                        "email": "newuser@example.com",
                        "full_name": "New User",
                        "trial_days": 60,
                        "source": "course-n8n-webhook",
                    },
                    headers=self._headers(TEST_INTERNAL_TOKEN),
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["email"] == "newuser@example.com"
        assert data["trial_ends_at"] is not None

        user = db_session.query(User).filter(User.email == "newuser@example.com").first()
        assert user is not None
        assert user.plan == "paid"
        assert user.subscription_tier == "pro"
        assert user.subscription_status == "active"
        assert user.is_trial_provisioned is True
        assert user.trial_source == "course-n8n-webhook"
        assert user.name == "New User"
        assert user.trial_ends_at is not None

        # Password reset token created
        token_count = db_session.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id
        ).count()
        assert token_count == 1

    def test_new_user_email_sent(self, client: TestClient):
        with patch("app.api.billing.INTERNAL_TOKEN", TEST_INTERNAL_TOKEN):
            with patch("app.worker.email._send_smtp") as mock_smtp:
                client.post(
                    PROVISION_URL,
                    json={"email": "emailtest@example.com"},
                    headers=self._headers(TEST_INTERNAL_TOKEN),
                )
                mock_smtp.assert_called_once()


class TestTrialSubscriptionDisplay:
    """Tests for trial banner fields in GET /billing/subscription."""

    def test_returns_trial_fields_for_trial_user(self, client: TestClient, db_session):
        from app.models.user import User

        user = User(
            email="trial@example.com",
            hashed_password="hashed",
            plan="paid",
            subscription_tier="pro",
            subscription_status="active",
            is_trial_provisioned=True,
            trial_ends_at=datetime.now(UTC) + timedelta(days=30),
        )
        db_session.add(user)
        db_session.commit()

        from app.services.auth import create_access_token
        token = create_access_token({"sub": user.email})

        resp = client.get("/billing/subscription", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_trial_provisioned"] is True
        assert data["trial_ends_at"] is not None
        assert data["paddle_subscription_id"] is None


class TestTrialExpiryTasks:
    """Tests for Celery trial expiry email tasks — idempotency."""

    def test_check_trial_expiry_warnings_sends_exactly_one_email(self, db_session):
        from app.models.user import User
        from app.worker.tasks import check_trial_expiry_warnings

        user = User(
            email="warning@example.com",
            hashed_password="hashed",
            plan="paid",
            subscription_tier="pro",
            is_trial_provisioned=True,
            trial_ends_at=datetime.now(UTC) + timedelta(days=10),
        )
        db_session.add(user)
        db_session.commit()

        with patch("app.core.database.SessionLocal", return_value=db_session):
            with patch("app.worker.tasks._subscribe_link", return_value="http://test/billing"):
                with patch("app.worker.email._send_smtp") as mock_smtp:
                    count1 = check_trial_expiry_warnings()

        assert count1 == 1
        mock_smtp.assert_called_once()
        args = mock_smtp.call_args[0]
        assert args[0] == "warning@example.com"
        assert "expires" in args[1].lower()

    def test_check_trial_expired_sends_exactly_one_email(self, db_session):
        from app.models.user import User
        from app.worker.tasks import check_trial_expired

        user = User(
            email="expired@example.com",
            hashed_password="hashed",
            plan="paid",
            subscription_tier="pro",
            is_trial_provisioned=True,
            trial_ends_at=datetime.now(UTC) - timedelta(days=1),
            trial_expiry_email_sent_at=None,
        )
        db_session.add(user)
        db_session.commit()

        with patch("app.core.database.SessionLocal", return_value=db_session):
            with patch("app.worker.tasks._subscribe_link", return_value="http://test/billing"):
                with patch("app.worker.email._send_smtp") as mock_smtp:
                    count1 = check_trial_expired()
                    count2 = check_trial_expired()

        assert count1 == 1
        assert count2 == 0
        mock_smtp.assert_called_once()
        args = mock_smtp.call_args[0]
        assert args[0] == "expired@example.com"
        assert "ended" in args[1].lower()

        refreshed = db_session.query(User).filter(User.email == "expired@example.com").first()
        assert refreshed.trial_expiry_email_sent_at is not None


class TestProvisionTrialAlreadyPro:
    """Tests for already-pro and free-upgrade paths."""

    def test_already_pro_returns_noop(self, client: TestClient, db_session):
        from app.models.user import User

        pro_user = User(
            email="pro@example.com",
            hashed_password="hashed",
            plan="paid",
            subscription_tier="pro",
            subscription_status="active",
        )
        db_session.add(pro_user)
        db_session.commit()

        with patch("app.api.billing.INTERNAL_TOKEN", TEST_INTERNAL_TOKEN):
            with patch("app.worker.email._send_smtp"):
                resp = client.post(
                    PROVISION_URL,
                    json={"email": "pro@example.com"},
                    headers={"X-Internal-Token": TEST_INTERNAL_TOKEN},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_pro"

    def test_free_user_upgraded(self, client: TestClient, db_session):
        from app.models.user import User

        free_user = User(
            email="free@example.com",
            hashed_password="hashed",
            plan="free",
            subscription_tier="free",
        )
        db_session.add(free_user)
        db_session.commit()

        with patch("app.api.billing.INTERNAL_TOKEN", TEST_INTERNAL_TOKEN):
            with patch("app.worker.email._send_smtp"):
                resp = client.post(
                    PROVISION_URL,
                    json={"email": "free@example.com", "source": "upgrade-test"},
                    headers={"X-Internal-Token": TEST_INTERNAL_TOKEN},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "upgraded"

        db_session.refresh(free_user)
        assert free_user.plan == "paid"
        assert free_user.subscription_tier == "pro"
        assert free_user.subscription_status == "active"
        assert free_user.is_trial_provisioned is True
        assert free_user.trial_source == "upgrade-test"
        assert free_user.trial_ends_at is not None

    def test_free_user_upgrade_email_sent(self, client: TestClient, db_session):
        from app.models.user import User

        free_user = User(
            email="emailupgrade@example.com",
            hashed_password="hashed",
            plan="free",
            subscription_tier="free",
        )
        db_session.add(free_user)
        db_session.commit()

        with patch("app.api.billing.INTERNAL_TOKEN", TEST_INTERNAL_TOKEN):
            with patch("app.worker.email._send_smtp") as mock_smtp:
                client.post(
                    PROVISION_URL,
                    json={"email": "emailupgrade@example.com"},
                    headers={"X-Internal-Token": TEST_INTERNAL_TOKEN},
                )
                mock_smtp.assert_called_once()

    def test_previously_trial_downgraded_user_returns_noop(self, client: TestClient, db_session):
        from app.models.user import User

        # User had a trial before, then was downgraded (e.g. expired or cancelled)
        old_user = User(
            email="oldtrial@example.com",
            hashed_password="hashed",
            plan="free",
            subscription_tier="free",
            is_trial_provisioned=True,
            trial_ends_at=datetime.now(UTC) - timedelta(days=5),
        )
        db_session.add(old_user)
        db_session.commit()

        with patch("app.api.billing.INTERNAL_TOKEN", TEST_INTERNAL_TOKEN):
            with patch("app.worker.email._send_smtp") as mock_smtp:
                resp = client.post(
                    PROVISION_URL,
                    json={"email": "oldtrial@example.com", "source": "retry"},
                    headers={"X-Internal-Token": TEST_INTERNAL_TOKEN},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_trial"

        db_session.refresh(old_user)
        # No changes should have been made
        assert old_user.plan == "free"
        assert old_user.subscription_tier == "free"
        assert old_user.trial_source is None
        mock_smtp.assert_not_called()

    def test_new_user_email_sent(self, client: TestClient):
        with patch("app.api.billing.INTERNAL_TOKEN", TEST_INTERNAL_TOKEN):
            with patch("app.worker.email._send_smtp") as mock_smtp:
                client.post(
                    PROVISION_URL,
                    json={"email": "emailtest@example.com"},
                    headers={"X-Internal-Token": TEST_INTERNAL_TOKEN},
                )
                mock_smtp.assert_called_once()
                call_args = mock_smtp.call_args[0]
                subject = call_args[1]
                body = call_args[2]
                assert "password" in subject.lower() or "password" in body.lower() or "reset-password" in body
