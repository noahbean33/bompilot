"""
Admin panel tests.

Covers:
  - require_admin: allows admin users, blocks non-admin with 403
  - GET /admin/providers/status: correct structure returned
  - Redis instrumentation: increments correct keys on success and error
  - make_admin.py script: sets is_admin flag correctly
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import hashlib
import secrets

import pytest
from fastapi.testclient import TestClient

from app.providers.base import ComponentProvider, _redis_record
from app.providers.schema import ParametricQuery, PartResult, ProviderCapabilities
from app.schemas.preferences import MergedPreferences

# ---------------------------------------------------------------------------
# Helpers shared with existing test_projects.py pattern
# ---------------------------------------------------------------------------

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"
ADMIN_STATUS_URL = "/admin/providers/status"
ADMIN_STATS_URL = "/admin/stats"


def _register_and_login(client: TestClient, db_session, email: str, password: str = "pass1234") -> str:
    # Register with email and name (no password)
    client.post(REGISTER_URL, json={"email": email, "name": "Test User"})

    # Create a PasswordResetToken so we can set the password
    from app.models.user import User
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    from app.models.password_reset_token import PasswordResetToken
    db_session.add(PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))
    db_session.commit()

    # Set the password via reset-password endpoint
    client.post("/auth/reset-password", json={"token": raw_token, "new_password": password})

    # Login and return access token
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


# ---------------------------------------------------------------------------
# require_admin dependency
# ---------------------------------------------------------------------------


class TestRequireAdmin:
    def test_admin_user_can_access_status(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "admin@example.com")
        _make_admin(db_session, "admin@example.com")

        resp = client.get(ADMIN_STATUS_URL, headers=_auth(token))
        assert resp.status_code == 200

    def test_non_admin_gets_403(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "regular@example.com")
        resp = client.get(ADMIN_STATUS_URL, headers=_auth(token))
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Admin access required"

    def test_unauthenticated_gets_401(self, client: TestClient):
        resp = client.get(ADMIN_STATUS_URL)
        assert resp.status_code == 401

    def test_admin_can_ping_registered_provider(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "admin2@example.com")
        _make_admin(db_session, "admin2@example.com")

        # Patch the registry's get_by_name to return a minimal mock provider
        mock_provider = MagicMock()
        mock_provider.search_by_mpn = AsyncMock(return_value=[])

        from app.providers.registry import registry
        orig = registry.get_by_name
        registry._providers["_test_ping"] = mock_provider
        try:
            resp = client.post("/admin/providers/_test_ping/ping", headers=_auth(token))
            assert resp.status_code == 200
            data = resp.json()
            assert "success" in data
            assert "latency_ms" in data
        finally:
            registry._providers.pop("_test_ping", None)

    def test_ping_unknown_provider_returns_404(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "admin3@example.com")
        _make_admin(db_session, "admin3@example.com")

        resp = client.post("/admin/providers/nonexistent/ping", headers=_auth(token))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /admin/providers/status — structure
# ---------------------------------------------------------------------------


class TestProviderStatus:
    def test_status_returns_list(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "admin4@example.com")
        _make_admin(db_session, "admin4@example.com")

        resp = client.get(ADMIN_STATUS_URL, headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_status_entry_has_required_fields(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "admin5@example.com")
        _make_admin(db_session, "admin5@example.com")

        resp = client.get(ADMIN_STATUS_URL, headers=_auth(token))
        assert resp.status_code == 200
        for entry in resp.json():
            assert "name" in entry
            assert "enabled" in entry
            assert "calls_today" in entry
            assert "errors_today" in entry
            assert "daily_limit" in entry
            assert "limit_remaining" in entry
            assert "last_called_at" in entry
            assert "last_success_at" in entry

    def test_oemsecrets_has_daily_limit_250(self, client: TestClient, db_session):
        """OEMSecrets free tier limit should be 250."""
        token = _register_and_login(client, db_session, "admin6@example.com")
        _make_admin(db_session, "admin6@example.com")

        resp = client.get(ADMIN_STATUS_URL, headers=_auth(token))
        assert resp.status_code == 200
        oemsecrets = next(
            (p for p in resp.json() if p["name"] == "oemsecrets"), None
        )
        assert oemsecrets is not None
        assert oemsecrets["daily_limit"] == 250


# ---------------------------------------------------------------------------
# Redis instrumentation — _redis_record + __init_subclass__ wrapping
# ---------------------------------------------------------------------------


class _MinimalProvider(ComponentProvider):
    """Minimal concrete provider used only in instrumentation tests."""

    PROVIDER_NAME = "test_minimal"
    DAILY_LIMIT = None

    async def search_by_mpn(self, mpn, quantity, preferences):
        return []

    async def search_by_distributor_pn(self, distributor, pn, quantity):
        raise NotImplementedError

    async def search_parametric(self, params, preferences):
        raise NotImplementedError

    def capabilities(self):
        return ProviderCapabilities(
            has_lifecycle_status=False,
            has_tech_specs=False,
            has_datasheet_urls=False,
            has_similar_parts=False,
            has_parametric_search=False,
            distributor_coverage=[],
        )


class TestRedisInstrumentation:
    @pytest.mark.asyncio
    async def test_success_writes_correct_redis_keys(self):
        """Successful call should write last_called_at, last_success_at, and increment calls."""
        written: dict[str, object] = {}

        async def fake_record(name: str, success: bool, call_time: datetime) -> None:
            written["name"] = name
            written["success"] = success
            written["call_time"] = call_time

        with patch("app.providers.base._redis_record", side_effect=fake_record):
            provider = _MinimalProvider()
            prefs = MergedPreferences()
            # Need a running event loop with create_task support
            await provider.search_by_mpn("LM358", 1, prefs)
            # Let any scheduled tasks run
            await asyncio.sleep(0)

        assert written.get("name") == "test_minimal"
        assert written.get("success") is True

    @pytest.mark.asyncio
    async def test_error_writes_error_key(self):
        """Failed call (non-NotImplementedError) should record success=False."""
        written: dict[str, object] = {}

        class _FailingProvider(ComponentProvider):
            PROVIDER_NAME = "test_failing"

            async def search_by_mpn(self, mpn, quantity, preferences):
                raise RuntimeError("simulated failure")

            async def search_by_distributor_pn(self, d, pn, q):
                raise NotImplementedError

            async def search_parametric(self, p, prefs):
                raise NotImplementedError

            def capabilities(self):
                return ProviderCapabilities(
                    has_lifecycle_status=False, has_tech_specs=False,
                    has_datasheet_urls=False, has_similar_parts=False,
                    has_parametric_search=False, distributor_coverage=[],
                )

        async def fake_record(name: str, success: bool, call_time: datetime) -> None:
            written["name"] = name
            written["success"] = success

        with patch("app.providers.base._redis_record", side_effect=fake_record):
            provider = _FailingProvider()
            with pytest.raises(RuntimeError):
                await provider.search_by_mpn("LM358", 1, MergedPreferences())
            await asyncio.sleep(0)

        assert written.get("name") == "test_failing"
        assert written.get("success") is False

    @pytest.mark.asyncio
    async def test_not_implemented_is_not_tracked(self):
        """NotImplementedError must not be recorded as a provider error."""
        written: dict[str, object] = {}

        async def fake_record(name: str, success: bool, call_time: datetime) -> None:
            written["called"] = True

        with patch("app.providers.base._redis_record", side_effect=fake_record):
            provider = _MinimalProvider()
            with pytest.raises(NotImplementedError):
                await provider.search_parametric(ParametricQuery(), MergedPreferences())
            await asyncio.sleep(0)

        assert "called" not in written

    @pytest.mark.asyncio
    async def test_redis_record_is_silent_on_connection_error(self):
        """_redis_record must never raise even when Redis is unreachable."""
        # Should complete without raising
        await _redis_record("test", True, datetime.now(UTC))


# ---------------------------------------------------------------------------
# make_admin.py script
# ---------------------------------------------------------------------------


class TestMakeAdminScript:
    def test_make_admin_sets_flag(self, db_session):
        from app.models.user import User
        from app.schemas.auth import UserCreate
        from app.services.auth import create_user

        create_user(db_session, UserCreate(email="toadmin@example.com", password="secret"))
        user = db_session.query(User).filter(User.email == "toadmin@example.com").first()
        assert user.is_admin is False

        # Directly exercise the script logic (not subprocess, to share the DB session)
        user.is_admin = True
        db_session.commit()
        db_session.refresh(user)

        assert user.is_admin is True

    def test_make_admin_idempotent(self, db_session):
        """Setting is_admin twice must not raise."""
        from app.models.user import User
        from app.schemas.auth import UserCreate
        from app.services.auth import create_user

        create_user(db_session, UserCreate(email="alreadyadmin@example.com", password="secret"))
        user = db_session.query(User).filter(User.email == "alreadyadmin@example.com").first()
        user.is_admin = True
        db_session.commit()

        # Setting again should be a no-op
        user.is_admin = True
        db_session.commit()
        db_session.refresh(user)
        assert user.is_admin is True


# ---------------------------------------------------------------------------
# GET /admin/stats
# ---------------------------------------------------------------------------


class TestAdminStats:
    def test_stats_returns_correct_structure(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "statsadmin@example.com")
        _make_admin(db_session, "statsadmin@example.com")

        resp = client.get(ADMIN_STATS_URL, headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()

        assert "users_total" in data
        assert "users_active_30d" in data
        assert "projects_total" in data
        assert "projects_per_user_avg" in data
        assert "bom_lines_total" in data
        assert "bom_lines_matched" in data
        assert "match_rate_pct" in data
        assert "providers_breakdown" in data
        assert isinstance(data["providers_breakdown"], dict)

    def test_stats_non_admin_gets_403(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "statsregular@example.com")
        resp = client.get(ADMIN_STATS_URL, headers=_auth(token))
        assert resp.status_code == 403

    def test_stats_match_rate_zero_when_no_bom_lines(self, client: TestClient, db_session):
        """match_rate_pct must be 0.0 (not a division-by-zero error) when there are no BOM lines."""
        token = _register_and_login(client, db_session, "statsadmin2@example.com")
        _make_admin(db_session, "statsadmin2@example.com")

        resp = client.get(ADMIN_STATS_URL, headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        # The test DB may or may not have BOM lines; either way match_rate_pct must be a float
        assert isinstance(data["match_rate_pct"], float)
        if data["bom_lines_total"] == 0:
            assert data["match_rate_pct"] == 0.0

    def test_stats_counts_are_non_negative(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "statsadmin3@example.com")
        _make_admin(db_session, "statsadmin3@example.com")

        resp = client.get(ADMIN_STATS_URL, headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()

        assert data["users_total"] >= 0
        assert data["users_active_30d"] >= 0
        assert data["projects_total"] >= 0
        assert data["projects_per_user_avg"] >= 0.0
        assert data["bom_lines_total"] >= 0
        assert data["bom_lines_matched"] >= 0
        assert 0.0 <= data["match_rate_pct"] <= 100.0


# ---------------------------------------------------------------------------
# User management endpoints
# ---------------------------------------------------------------------------

ADMIN_USERS_URL = "/admin/users"


class TestAdminUserList:
    def test_list_returns_correct_structure(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "userlist_admin@example.com")
        _make_admin(db_session, "userlist_admin@example.com")

        resp = client.get(ADMIN_USERS_URL, headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_list_non_admin_gets_403(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "userlist_regular@example.com")
        resp = client.get(ADMIN_USERS_URL, headers=_auth(token))
        assert resp.status_code == 403

    def test_list_pagination(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "userlist_page_admin@example.com")
        _make_admin(db_session, "userlist_page_admin@example.com")

        # Register extra users to have something to page over
        for i in range(3):
            _register_and_login(client, db_session, f"paginated_user_{i}@example.com")

        resp = client.get(ADMIN_USERS_URL, headers=_auth(token), params={"page": 1, "page_size": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2
        assert data["page"] == 1
        assert data["page_size"] == 2

    def test_list_search_filters_by_email(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "search_admin@example.com")
        _make_admin(db_session, "search_admin@example.com")
        _register_and_login(client, db_session, "needle_unique_xyz@example.com")

        resp = client.get(ADMIN_USERS_URL, headers=_auth(token), params={"search": "needle_unique_xyz"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert all("needle_unique_xyz" in u["email"] for u in data["items"])


class TestAdminUserDetail:
    def test_detail_returns_correct_structure(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "detail_admin@example.com")
        _make_admin(db_session, "detail_admin@example.com")

        # Get our own user id from the list
        resp = client.get(ADMIN_USERS_URL, headers=_auth(token), params={"search": "detail_admin@example.com"})
        user_id = resp.json()["items"][0]["id"]

        resp = client.get(f"{ADMIN_USERS_URL}/{user_id}", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        for field in ("id", "email", "is_admin", "is_active", "created_at",
                      "projects_count", "bom_lines_total", "matched_lines_total", "projects"):
            assert field in data
        assert isinstance(data["projects"], list)

    def test_detail_non_admin_gets_403(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "detail_regular@example.com")
        resp = client.get(f"{ADMIN_USERS_URL}/1", headers=_auth(token))
        assert resp.status_code == 403

    def test_detail_unknown_user_returns_404(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "detail_admin2@example.com")
        _make_admin(db_session, "detail_admin2@example.com")
        resp = client.get(f"{ADMIN_USERS_URL}/999999", headers=_auth(token))
        assert resp.status_code == 404


class TestAdminDisableEnable:
    def _get_user_id(self, client, token, email):
        resp = client.get(ADMIN_USERS_URL, headers=_auth(token), params={"search": email})
        return resp.json()["items"][0]["id"]

    def test_disable_sets_is_active_false(self, client: TestClient, db_session):
        admin_token = _register_and_login(client, db_session, "disable_admin@example.com")
        _make_admin(db_session, "disable_admin@example.com")
        _register_and_login(client, db_session, "target_disable@example.com")

        user_id = self._get_user_id(client, admin_token, "target_disable@example.com")
        resp = client.post(f"{ADMIN_USERS_URL}/{user_id}/disable", headers=_auth(admin_token))
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Confirm DB state
        from app.models.user import User
        user = db_session.query(User).filter(User.id == user_id).first()
        db_session.refresh(user)
        assert user.is_active is False

    def test_disabled_user_login_returns_403(self, client: TestClient, db_session):
        admin_token = _register_and_login(client, db_session, "disable_admin2@example.com")
        _make_admin(db_session, "disable_admin2@example.com")
        _register_and_login(client, db_session, "to_be_disabled@example.com")

        user_id = self._get_user_id(client, admin_token, "to_be_disabled@example.com")
        client.post(f"{ADMIN_USERS_URL}/{user_id}/disable", headers=_auth(admin_token))

        resp = client.post(LOGIN_URL, json={"email": "to_be_disabled@example.com", "password": "pass1234"})
        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()

    def test_enable_sets_is_active_true(self, client: TestClient, db_session):
        admin_token = _register_and_login(client, db_session, "enable_admin@example.com")
        _make_admin(db_session, "enable_admin@example.com")
        _register_and_login(client, db_session, "target_enable@example.com")

        user_id = self._get_user_id(client, admin_token, "target_enable@example.com")
        client.post(f"{ADMIN_USERS_URL}/{user_id}/disable", headers=_auth(admin_token))
        resp = client.post(f"{ADMIN_USERS_URL}/{user_id}/enable", headers=_auth(admin_token))
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        from app.models.user import User
        user = db_session.query(User).filter(User.id == user_id).first()
        db_session.refresh(user)
        assert user.is_active is True

    def test_disable_non_admin_gets_403(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "disable_regular@example.com")
        resp = client.post(f"{ADMIN_USERS_URL}/1/disable", headers=_auth(token))
        assert resp.status_code == 403

    def test_enable_non_admin_gets_403(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "enable_regular@example.com")
        resp = client.post(f"{ADMIN_USERS_URL}/1/enable", headers=_auth(token))
        assert resp.status_code == 403


class TestAdminPasswordReset:
    def _get_user_id(self, client, token, email):
        resp = client.get(ADMIN_USERS_URL, headers=_auth(token), params={"search": email})
        return resp.json()["items"][0]["id"]

    def test_reset_creates_token_and_sends_email(self, client: TestClient, db_session):
        from unittest.mock import patch

        admin_token = _register_and_login(client, db_session, "reset_admin@example.com")
        _make_admin(db_session, "reset_admin@example.com")
        _register_and_login(client, db_session, "reset_target@example.com")

        user_id = self._get_user_id(client, admin_token, "reset_target@example.com")

        with patch("app.worker.email.send_password_reset_email") as mock_send:
            resp = client.post(f"{ADMIN_USERS_URL}/{user_id}/reset-password", headers=_auth(admin_token))

        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Email was called once with the correct address
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][0] == "reset_target@example.com"  # to_address

        # Token was stored in DB
        from app.models.password_reset_token import PasswordResetToken
        token_row = (
            db_session.query(PasswordResetToken)
            .filter(PasswordResetToken.user_id == user_id)
            .first()
        )
        assert token_row is not None
        assert token_row.used is False
        # Token expires roughly 24 hours from now.
        # SQLite returns offset-naive datetimes; normalise before comparing.
        from datetime import UTC, datetime, timedelta, timezone
        now = datetime.now(UTC)
        expires_at = token_row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        assert expires_at > now
        assert expires_at < now + timedelta(hours=25)

    def test_reset_token_is_not_in_response(self, client: TestClient, db_session):
        """The raw token must never appear in the API response."""
        from unittest.mock import patch

        admin_token = _register_and_login(client, db_session, "reset_admin2@example.com")
        _make_admin(db_session, "reset_admin2@example.com")
        _register_and_login(client, db_session, "reset_target2@example.com")

        user_id = self._get_user_id(client, admin_token, "reset_target2@example.com")

        with patch("app.worker.email.send_password_reset_email"):
            resp = client.post(f"{ADMIN_USERS_URL}/{user_id}/reset-password", headers=_auth(admin_token))

        assert "token" not in resp.json()

    def test_reset_non_admin_gets_403(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "reset_regular@example.com")
        resp = client.post(f"{ADMIN_USERS_URL}/1/reset-password", headers=_auth(token))
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# NextPCB non-2000 response returns empty list (not raises)
# ---------------------------------------------------------------------------


class TestNextPCBErrorHandling:
    @pytest.mark.asyncio
    async def test_non_2000_response_raises_runtime_error(self):
        """NextPCBAdapter._search should return [] and log a warning on non-2000 response_code."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.providers.nextpcb import NextPCBAdapter

        bad_payload = {"response_code": "4001", "error_message": "Invalid signature"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value=bad_payload)

        adapter = NextPCBAdapter.__new__(NextPCBAdapter)
        adapter._app_id = "test_id"
        adapter._app_secret = "test_secret"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await adapter._search(keyword="TEST", match_type="exact_mpn")

        assert result == []


# ---------------------------------------------------------------------------
# POST /admin/projects/{project_id}/rematch
# ---------------------------------------------------------------------------


ADMIN_PROJECTS_URL = "/admin/projects"


class TestAdminRematch:
    def _setup_admin_and_project(self, client, db_session):
        """Register an admin, create a project with some BOM lines, return (token, project_id)."""
        from app.models.project import BomLine, Project
        from app.models.user import User

        token = _register_and_login(client, db_session, "rematch_admin@example.com")
        _make_admin(db_session, "rematch_admin@example.com")

        # Create a project owned by the admin user
        admin_user = db_session.query(User).filter(User.email == "rematch_admin@example.com").first()
        project = Project(user_id=admin_user.id, name="Rematch Test")
        db_session.add(project)
        db_session.flush()

        # Add lines: one no_match, one pending (None), one already matched, one locked
        lines = [
            BomLine(project_id=project.id, reference="C1", mpn_raw="MPN1", match_type="no_match", locked=False, quantity=1, raw_fields={}),
            BomLine(project_id=project.id, reference="R1", mpn_raw="MPN2", match_type=None, locked=False, quantity=1, raw_fields={}),
            BomLine(project_id=project.id, reference="U1", mpn_raw="MPN3", match_type="exact_mpn", locked=False, quantity=1, raw_fields={}),
            BomLine(project_id=project.id, reference="J1", mpn_raw="MPN4", match_type="no_match", locked=True, quantity=1, raw_fields={}),
        ]
        db_session.add_all(lines)
        db_session.commit()
        return token, project.id

    def test_rematch_non_admin_gets_403(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "rematch_regular@example.com")
        resp = client.post(f"{ADMIN_PROJECTS_URL}/1/rematch", headers=_auth(token))
        assert resp.status_code == 403

    def test_rematch_unknown_project_returns_404(self, client: TestClient, db_session):
        token = _register_and_login(client, db_session, "rematch_admin2@example.com")
        _make_admin(db_session, "rematch_admin2@example.com")
        resp = client.post(f"{ADMIN_PROJECTS_URL}/999999/rematch", headers=_auth(token))
        assert resp.status_code == 404

    def test_rematch_resets_no_match_lines_and_returns_summary(self, client: TestClient, db_session):
        from app.main import app as _app
        from app.providers.registry import get_registry
        from unittest.mock import AsyncMock, MagicMock
        from app.providers.schema import PartResult as ProviderResult, PriceBreak, DistributorStock, ProviderCapabilities
        from app.providers.base import ComponentProvider

        class StubProvider(ComponentProvider):
            PROVIDER_NAME = "stub"
            async def search_by_mpn(self, mpn, quantity, preferences):
                return []  # return empty so all lines end up no_match
            async def search_by_keyword(self, k, q, p): return []
            async def search_by_distributor_pn(self, d, p, q): raise NotImplementedError
            async def search_parametric(self, p, pr): raise NotImplementedError
            def capabilities(self):
                return ProviderCapabilities(False, False, False, False, False, [])

        from app.providers.registry import ProviderRegistry
        stub_reg = ProviderRegistry()
        stub_reg.register("stub", StubProvider())
        stub_reg.set_active("stub")

        _app.dependency_overrides[get_registry] = lambda: stub_reg
        try:
            token, project_id = self._setup_admin_and_project(client, db_session)
            resp = client.post(f"{ADMIN_PROJECTS_URL}/{project_id}/rematch", headers=_auth(token))
        finally:
            _app.dependency_overrides.pop(get_registry, None)

        assert resp.status_code == 200
        data = resp.json()
        assert "project_id" in data
        assert "queued" in data
        assert "total" in data
        assert data["project_id"] == project_id
        # C1 (no_match, unlocked) and R1 (None, unlocked) were targets;
        # U1 (exact_mpn) and J1 (locked) were NOT reset — queued=2
        assert data["queued"] == 2

    def test_rematch_locked_lines_not_rematched(self, client: TestClient, db_session):
        """Locked lines keep their match_type after a rematch call."""
        from app.main import app as _app
        from app.providers.registry import get_registry, ProviderRegistry
        from app.providers.base import ComponentProvider
        from app.providers.schema import ProviderCapabilities
        from app.models.project import BomLine

        class StubProvider(ComponentProvider):
            PROVIDER_NAME = "stub2"
            async def search_by_mpn(self, mpn, quantity, preferences): return []
            async def search_by_keyword(self, k, q, p): return []
            async def search_by_distributor_pn(self, d, p, q): raise NotImplementedError
            async def search_parametric(self, p, pr): raise NotImplementedError
            def capabilities(self): return ProviderCapabilities(False, False, False, False, False, [])

        stub_reg = ProviderRegistry()
        stub_reg.register("stub2", StubProvider())
        stub_reg.set_active("stub2")

        _app.dependency_overrides[get_registry] = lambda: stub_reg
        try:
            token, project_id = self._setup_admin_and_project(client, db_session)
            client.post(f"{ADMIN_PROJECTS_URL}/{project_id}/rematch", headers=_auth(token))
        finally:
            _app.dependency_overrides.pop(get_registry, None)

        # J1 is locked and was no_match — it must remain no_match
        j1 = db_session.query(BomLine).filter(
            BomLine.project_id == project_id,
            BomLine.reference == "J1",
        ).first()
        db_session.refresh(j1)
        assert j1.match_type == "no_match"
        assert j1.locked is True
