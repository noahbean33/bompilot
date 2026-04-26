"""
Tests for Item 12 — Natural language BOM query (AI-5).

Covers:
  - POST /projects/{id}/bom/nl-query: returns correct filter structure
  - Non-filter (general question) input returns empty filters without calling Anthropic
  - Token counts are written to Redis after a successful Anthropic call
  - GET /admin/ai/usage: correct structure and cost calculation
  - Non-admin receives 403 on /admin/ai/usage
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.services.auth import get_user_by_email

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"
AI_USAGE_URL = "/admin/ai/usage"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(client: TestClient, db_session, email: str, password: str = "pass1234") -> str:
    client.post(REGISTER_URL, json={"email": email, "name": "Test User"})
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


def _make_admin(db_session, email: str) -> None:
    from app.models.user import User
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    user.is_admin = True
    db_session.commit()


def _create_project(client: TestClient, token: str, name: str = "Test Project") -> int:
    resp = client.post(
        "/projects/",
        json={"name": name},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# POST /projects/{id}/bom/nl-query
# ---------------------------------------------------------------------------

def _make_mock_anthropic_response(filters: list, highlight_only: bool, explanation: str):
    """Build a fake Anthropic message response matching the SDK structure."""
    content_text = json.dumps({
        "filters": filters,
        "highlight_only": highlight_only,
        "explanation": explanation,
    })
    content_block = MagicMock()
    content_block.text = content_text

    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 30

    message = MagicMock()
    message.content = [content_block]
    message.usage = usage
    return message


class TestNlQuery:
    def test_nl_query_returns_filter_structure(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "nluser@example.com")
        project_id = _create_project(client, token)

        mock_message = _make_mock_anthropic_response(
            filters=[{"field": "matched_mpn", "op": "is_null", "value": None}],
            highlight_only=False,
            explanation="Parts with no matched MPN",
        )

        mock_client_inst = AsyncMock()
        mock_client_inst.messages.create = AsyncMock(return_value=mock_message)

        with patch("app.services.nl_query.anthropic") as mock_anthropic_mod, \
             patch("app.services.nl_query._track_tokens", new=AsyncMock()), \
             patch("app.services.nl_query.settings") as mock_settings:

            mock_settings.anthropic_api_key = "test"
            mock_anthropic_mod.AsyncAnthropic.return_value = mock_client_inst

            resp = client.post(
                f"/projects/{project_id}/bom/nl-query",
                json={"query": "unmatched parts"},
                headers=_auth(token),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "filters" in data
        assert "highlight_only" in data
        assert "explanation" in data
        assert isinstance(data["filters"], list)
        assert isinstance(data["highlight_only"], bool)

    def test_general_question_returns_empty_without_api_call(
        self, client: TestClient, db_session
    ):
        """General questions must bypass the Anthropic API entirely."""
        token = _register_and_login(client, db_session, "nluser2@example.com")
        project_id = _create_project(client, token)

        with patch("app.services.nl_query.anthropic") as mock_anthropic_mod:
            mock_client = AsyncMock()
            mock_anthropic_mod.AsyncAnthropic.return_value = mock_client

            resp = client.post(
                f"/projects/{project_id}/bom/nl-query",
                json={"query": "what is a decoupling capacitor?"},
                headers=_auth(token),
            )

            # Anthropic should NOT have been called
            mock_client.messages.create.assert_not_called()

        assert resp.status_code == 200
        data = resp.json()
        assert data["filters"] == []

    def test_nl_query_requires_auth(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "nluser3@example.com")
        project_id = _create_project(client, token)

        resp = client.post(
            f"/projects/{project_id}/bom/nl-query",
            json={"query": "unmatched parts"},
        )
        assert resp.status_code == 401

    def test_nl_query_wrong_project_returns_404(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "nluser4@example.com")

        with patch("app.services.nl_query.run_nl_query", new=AsyncMock(return_value={"filters": [], "highlight_only": False, "explanation": ""})):
            resp = client.post(
                "/projects/999999/bom/nl-query",
                json={"query": "anything"},
                headers=_auth(token),
            )
        assert resp.status_code == 404

    def test_nl_query_no_api_key_returns_empty(self, client: TestClient, db_session):
        """When ANTHROPIC_API_KEY is empty the endpoint must return empty filters gracefully."""
        token = _register_and_login(client, db_session, "nluser5@example.com")
        project_id = _create_project(client, token)

        with patch("app.services.nl_query.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""

            resp = client.post(
                f"/projects/{project_id}/bom/nl-query",
                json={"query": "parts with low stock"},
                headers=_auth(token),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["filters"] == []


class TestNlQueryTokenTracking:
    @pytest.mark.asyncio
    async def test_tokens_written_to_redis_after_call(self):
        """Token INCRBY calls must be made for a successful Anthropic response."""
        import asyncio
        from app.services.nl_query import run_nl_query

        mock_message = _make_mock_anthropic_response(
            filters=[{"field": "stock", "op": "lt", "value": 100}],
            highlight_only=False,
            explanation="Parts with stock below 100",
        )

        written: dict = {}

        async def fake_track(input_tokens: int, output_tokens: int) -> None:
            written["input"] = input_tokens
            written["output"] = output_tokens

        with patch("app.services.nl_query.anthropic") as mock_anthropic_mod, \
             patch("app.services.nl_query.settings") as mock_settings, \
             patch("app.services.nl_query._track_tokens", side_effect=fake_track):

            mock_settings.anthropic_api_key = "test"

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_message)
            mock_anthropic_mod.AsyncAnthropic.return_value = mock_client

            await run_nl_query("parts with stock below 100")
            # Let the create_task-scheduled _track_tokens coroutine run
            await asyncio.sleep(0)

        assert written.get("input") == 100
        assert written.get("output") == 30


# ---------------------------------------------------------------------------
# GET /admin/ai/usage
# ---------------------------------------------------------------------------

class TestAdminAiUsage:
    def test_ai_usage_returns_correct_structure(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "aiusage_admin@example.com")
        _make_admin(db_session, "aiusage_admin@example.com")

        resp = client.get(AI_USAGE_URL, headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()

        assert "start_date" in data
        assert "end_date" in data
        assert "daily" in data
        assert "summary" in data
        assert "breakdown" in data
        assert "total_cost_usd" in data
        assert "rate_note" in data
        assert isinstance(data["daily"], list)
        assert isinstance(data["summary"], list)
        assert len(data["daily"]) >= 1

        entry = data["daily"][0]
        assert "feature" in entry
        assert "input_tokens" in entry
        assert "output_tokens" in entry
        assert "total_cost_usd" in entry

    def test_ai_usage_cost_calculation(self, client: TestClient, db_session):
        """Cost = (input / 1M * 0.80) + (output / 1M * 4.00)."""
        token = _register_and_login(client, db_session, "aiusage_admin2@example.com")
        _make_admin(db_session, "aiusage_admin2@example.com")

        from datetime import UTC, datetime

        today = datetime.now(UTC).strftime("%Y-%m-%d")

        async def fake_get_int(key: str) -> int:
            # Only inject tokens for NL query; AI Assist keys return 0
            if "nl_query" in key and "input" in key:
                return 1_000_000  # 1 M input tokens → $0.80
            if "nl_query" in key and "output" in key:
                return 1_000_000  # 1 M output tokens → $4.00
            return 0

        with patch("app.api.admin._redis_get_int", side_effect=fake_get_int):
            resp = client.get(AI_USAGE_URL, headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        # NL Query: $0.80 + $4.00 = $4.80; AI Assist: $0.00 → total = $4.80
        assert abs(data["total_cost_usd"] - 4.80) < 0.001

    def test_ai_usage_non_admin_gets_403(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "aiusage_regular@example.com")
        resp = client.get(AI_USAGE_URL, headers=_auth(token))
        assert resp.status_code == 403

    def test_ai_usage_unauthenticated_gets_401(self, client: TestClient):
        resp = client.get(AI_USAGE_URL)
        assert resp.status_code == 401
