"""
Tests for the AI Assist feature (Item 13).

Covers:
  - GET /projects/{id}/ai-assist/budget: returns budget structure
  - POST /projects/{id}/ai-assist: copper-only → no_part_needed
  - POST /projects/{id}/ai-assist: real part + provider results → ai_suggested
  - POST /projects/{id}/ai-assist: real part + no provider results → no_match
  - POST /projects/{id}/ai-assist: budget enforcement (skipped_budget)
  - POST /projects/{id}/ai-assist: 429 when budget is exhausted
  - _parse_claude_response handles markdown fences
  - get_budget_state: unlimited when limit is None
"""

from __future__ import annotations

import json
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(client: TestClient, db_session, email: str, password: str = "pass1234") -> str:
    """Register user (no password), create reset token, set password, then login."""
    from app.models.password_reset_token import PasswordResetToken
    from app.models.user import User

    with patch("app.worker.email._send_smtp"):
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


def _create_project(client: TestClient, token: str, name: str = "AI Test Project") -> int:
    resp = client.post("/projects/", json={"name": name}, headers=_auth(token))
    assert resp.status_code == 201
    return resp.json()["id"]


def _import_bom(client: TestClient, token: str, project_id: int, csv_content: str) -> None:
    import io
    resp = client.post(
        f"/projects/{project_id}/bom/import",
        files={"file": ("bom.csv", io.BytesIO(csv_content.encode()), "text/csv")},
        headers=_auth(token),
    )
    assert resp.status_code == 200


def _make_mock_claude_response(classifications: list[dict]) -> MagicMock:
    """Build a fake Anthropic Messages response."""
    content_block = MagicMock()
    content_block.text = json.dumps(classifications)

    usage = MagicMock()
    usage.input_tokens = 50
    usage.output_tokens = 20

    message = MagicMock()
    message.content = [content_block]
    message.usage = usage
    return message


def _make_mock_provider_results(mpns: list[str]) -> list[MagicMock]:
    results = []
    for mpn in mpns:
        r = MagicMock()
        r.mpn = mpn
        r.manufacturer = "ACME"
        r.description = f"Mock part {mpn}"
        r.datasheet_url = None
        results.append(r)
    return results


# ---------------------------------------------------------------------------
# Unit tests: _parse_claude_response
# ---------------------------------------------------------------------------

class TestParseClaudeResponse:
    def test_plain_json(self):
        from app.services.ai_matching import _parse_claude_response
        data = [{"copper_only": False, "search_queries": ["10k 0402"]}]
        result = _parse_claude_response(json.dumps(data))
        assert result == data

    def test_strips_json_markdown_fence(self):
        from app.services.ai_matching import _parse_claude_response
        fenced = '```json\n[{"copper_only": true, "search_queries": []}]\n```'
        result = _parse_claude_response(fenced)
        assert result == [{"copper_only": True, "search_queries": []}]

    def test_strips_plain_markdown_fence(self):
        from app.services.ai_matching import _parse_claude_response
        fenced = '```\n[{"copper_only": false, "search_queries": ["foo"]}]\n```'
        result = _parse_claude_response(fenced)
        assert result == [{"copper_only": False, "search_queries": ["foo"]}]


# ---------------------------------------------------------------------------
# Unit tests: get_budget_state
# ---------------------------------------------------------------------------

class TestGetBudgetState:
    def test_unlimited_when_limit_is_none(self):
        import asyncio
        from app.services.ai_matching import get_budget_state

        async def run():
            with patch("app.services.ai_matching._get_lines_used_this_month", return_value=0):
                state = await get_budget_state(user_id=1, limit=None)
            return state

        state = asyncio.get_event_loop().run_until_complete(run())
        assert state["unlimited"] is True
        assert state["limit"] is None
        assert state["remaining"] is None

    def test_remaining_counts_down(self):
        import asyncio
        from app.services.ai_matching import get_budget_state

        async def run():
            with patch("app.services.ai_matching._get_lines_used_this_month", return_value=10):
                state = await get_budget_state(user_id=1, limit=50)
            return state

        state = asyncio.get_event_loop().run_until_complete(run())
        assert state["used"] == 10
        assert state["limit"] == 50
        assert state["remaining"] == 40
        assert state["unlimited"] is False

    def test_remaining_floored_at_zero(self):
        import asyncio
        from app.services.ai_matching import get_budget_state

        async def run():
            with patch("app.services.ai_matching._get_lines_used_this_month", return_value=999):
                state = await get_budget_state(user_id=1, limit=50)
            return state

        state = asyncio.get_event_loop().run_until_complete(run())
        assert state["remaining"] == 0


# ---------------------------------------------------------------------------
# Integration tests via HTTP endpoints
# ---------------------------------------------------------------------------

MINIMAL_BOM = "reference,value,footprint\nC1,100nF,C_0402_1005Metric\n"
FIDUCIAL_BOM = "reference,value,footprint\nFID1,Fiducial,Fiducial_1mm_Copper\n"
TWO_LINE_BOM = (
    "reference,value,footprint\n"
    "C1,100nF,C_0402_1005Metric\n"
    "FID1,Fiducial,Fiducial_1mm_Copper\n"
)


class TestAiAssistBudgetEndpoint:
    def test_budget_structure(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "aibudget@example.com")
        project_id = _create_project(client, token)

        with patch("app.services.ai_matching._get_lines_used_this_month", return_value=5):
            resp = client.get(
                f"/projects/{project_id}/ai-assist/budget",
                headers=_auth(token),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "used" in data
        assert "limit" in data
        assert "remaining" in data
        assert "resets_at" in data
        assert "unlimited" in data

    def test_budget_unauthenticated_401(self, client: TestClient):
        resp = client.get("/projects/1/ai-assist/budget")
        assert resp.status_code == 401


class TestAiAssistRun:
    def test_copper_only_becomes_no_part_needed(self, client: TestClient, db_session):
        """Fiducial line → AI classifies as copper_only → match_type = no_part_needed."""
        token = _register_and_login(client, db_session, "airun_copper@example.com")
        project_id = _create_project(client, token)
        _import_bom(client, token, project_id, FIDUCIAL_BOM)

        # Mock: Claude says copper_only=True; provider is never called
        mock_response = _make_mock_claude_response([{"copper_only": True, "search_queries": []}])

        with (
            patch("app.services.ai_matching._get_lines_used_this_month", return_value=0),
            patch("app.services.ai_matching._increment_lines_used", new_callable=AsyncMock),
            patch("app.services.ai_matching._track_tokens", new_callable=AsyncMock),
            patch("anthropic.Anthropic") as mock_anthropic_cls,
        ):
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic_cls.return_value = mock_client

            resp = client.post(
                f"/projects/{project_id}/ai-assist",
                headers=_auth(token),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["no_part_needed"] == 1
        assert data["ai_suggested"] == 0
        assert data["processed"] == 1

        # Verify the BOM line was updated in the DB
        bom_resp = client.get(f"/projects/{project_id}/bom", headers=_auth(token))
        lines = bom_resp.json()
        assert lines[0]["match_type"] == "no_part_needed"

    def test_real_part_with_provider_hit_becomes_ai_suggested(self, client: TestClient, db_session):
        """Real component → provider finds results → match_type = ai_suggested."""
        token = _register_and_login(client, db_session, "airun_real@example.com")
        project_id = _create_project(client, token)
        _import_bom(client, token, project_id, MINIMAL_BOM)

        mock_response = _make_mock_claude_response([
            {"copper_only": False, "search_queries": ["100nF 0402 capacitor"]}
        ])
        provider_results = _make_mock_provider_results(["GRM155R71C104KA88D"])

        with (
            patch("app.services.ai_matching._get_lines_used_this_month", return_value=0),
            patch("app.services.ai_matching._increment_lines_used", new_callable=AsyncMock),
            patch("app.services.ai_matching._track_tokens", new_callable=AsyncMock),
            patch("anthropic.Anthropic") as mock_anthropic_cls,
            patch("app.services.ai_matching._search_queries", new_callable=AsyncMock, return_value=provider_results),
        ):
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic_cls.return_value = mock_client

            resp = client.post(
                f"/projects/{project_id}/ai-assist",
                headers=_auth(token),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ai_suggested"] == 1
        assert data["no_part_needed"] == 0
        assert data["no_match"] == 0

        bom_resp = client.get(f"/projects/{project_id}/bom", headers=_auth(token))
        assert bom_resp.json()[0]["match_type"] == "ai_suggested"

    def test_real_part_no_provider_results_becomes_no_match(self, client: TestClient, db_session):
        """Real component → no provider results → match_type = no_match."""
        token = _register_and_login(client, db_session, "airun_nomatch@example.com")
        project_id = _create_project(client, token)
        _import_bom(client, token, project_id, MINIMAL_BOM)

        mock_response = _make_mock_claude_response([
            {"copper_only": False, "search_queries": ["obscure part"]}
        ])

        # Create a mock registry that returns empty results for any search
        mock_provider = MagicMock()
        mock_provider.search_by_mpn = AsyncMock(return_value=[])
        mock_provider.search_by_keyword = AsyncMock(return_value=[])
        mock_registry = MagicMock()
        mock_registry.get_by_name.return_value = mock_provider

        with (
            patch("app.services.ai_matching._get_lines_used_this_month", return_value=0),
            patch("app.services.ai_matching._increment_lines_used", new_callable=AsyncMock),
            patch("app.services.ai_matching._track_tokens", new_callable=AsyncMock),
            patch("anthropic.Anthropic") as mock_anthropic_cls,
            patch("app.services.ai_matching._search_queries", new_callable=AsyncMock, return_value=[]),
            patch("app.services.matching.resolve_fallback_order", return_value=[]),
        ):
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic_cls.return_value = mock_client

            resp = client.post(
                f"/projects/{project_id}/ai-assist",
                headers=_auth(token),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["no_match"] == 1
        assert data["ai_suggested"] == 0

        bom_resp = client.get(f"/projects/{project_id}/bom", headers=_auth(token))
        assert bom_resp.json()[0]["match_type"] == "no_match"

    def test_budget_exhausted_returns_429(self, client: TestClient, db_session):
        """When used >= limit, POST /ai-assist returns 429."""
        token = _register_and_login(client, db_session, "airun_429@example.com")
        project_id = _create_project(client, token)
        _import_bom(client, token, project_id, MINIMAL_BOM)

        # Simulate budget fully consumed
        with patch("app.services.ai_matching._get_lines_used_this_month", return_value=50):
            # Also patch get_effective_limits so the limit = 50
            with patch("app.api.projects.get_effective_limits", return_value={
                "max_projects": 5,
                "max_parts_per_project": 50,
                "ai_assist_monthly_lines": 50,
            }):
                resp = client.post(
                    f"/projects/{project_id}/ai-assist",
                    headers=_auth(token),
                )

        assert resp.status_code == 429

    def test_partial_budget_skips_excess_lines(self, client: TestClient, db_session):
        """Only processes lines up to remaining budget; skipped_budget reports the rest."""
        token = _register_and_login(client, db_session, "airun_partial@example.com")
        project_id = _create_project(client, token)
        # 2 eligible lines but only 1 remaining in budget
        _import_bom(client, token, project_id, TWO_LINE_BOM)

        mock_response = _make_mock_claude_response([
            {"copper_only": True, "search_queries": []}
        ])

        with (
            patch("app.services.ai_matching._get_lines_used_this_month", return_value=49),
            patch("app.services.ai_matching._increment_lines_used", new_callable=AsyncMock),
            patch("app.services.ai_matching._track_tokens", new_callable=AsyncMock),
            patch("app.api.projects.get_effective_limits", return_value={
                "max_projects": 5,
                "max_parts_per_project": 50,
                "ai_assist_monthly_lines": 50,
            }),
            patch("anthropic.Anthropic") as mock_anthropic_cls,
        ):
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic_cls.return_value = mock_client

            resp = client.post(
                f"/projects/{project_id}/ai-assist",
                headers=_auth(token),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 1
        assert data["skipped_budget"] == 1

    def test_unauthenticated_401(self, client: TestClient):
        resp = client.post("/projects/1/ai-assist")
        assert resp.status_code == 401
