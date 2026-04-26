"""
Tests for freemium plan enforcement:
  - Project creation limit (free plan, paid plan, per-user override)
  - BOM import parts-per-project limit
  - Provider query: skipped_providers for free users / absent for paid users
"""

from __future__ import annotations

import hashlib
import io
import secrets
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.providers.base import ComponentProvider
from app.providers.registry import ProviderRegistry, get_registry
from app.providers.schema import (
    DistributorStock,
    ParametricQuery,
    PriceBreak,
    ProviderCapabilities,
)
from app.providers.schema import (
    PartResult as ProviderResult,
)
from app.schemas.preferences import MergedPreferences

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"
PROJECTS_URL = "/projects/"

# ---------------------------------------------------------------------------
# Mock provider (no live API calls)
# ---------------------------------------------------------------------------

_FAKE_RESULT = ProviderResult(
    mpn="RC0402FR-0710KL",
    manufacturer="Yageo",
    description="10k 0402 resistor",
    package="0402",
    pricing=[PriceBreak(quantity=1, unit_price=0.01, currency="USD")],
    stock_total=100000,
    distributors=[DistributorStock(distributor="digikey", stock=100000, url=None)],
    lifecycle_status="active",
    tech_specs=None,
    datasheet_url=None,
    similar_parts=None,
    source_provider="mock",
    retrieved_at=datetime(2026, 4, 10, tzinfo=UTC),
    match_type="exact_mpn",
)


class MockProvider(ComponentProvider):
    async def search_by_mpn(
        self, mpn: str, quantity: int, preferences: MergedPreferences
    ) -> list[ProviderResult]:
        return [_FAKE_RESULT]

    async def search_by_distributor_pn(
        self, distributor: str, pn: str, quantity: int
    ) -> list[ProviderResult]:
        raise NotImplementedError

    async def search_parametric(
        self, params: ParametricQuery, preferences: MergedPreferences
    ) -> list[ProviderResult]:
        raise NotImplementedError

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            has_lifecycle_status=False,
            has_tech_specs=False,
            has_datasheet_urls=False,
            has_similar_parts=False,
            has_parametric_search=False,
            distributor_coverage=["digikey"],
        )


def _mock_registry_with_tiers() -> ProviderRegistry:
    """Registry with nexar=premium and oemsecrets=free, for plan-filtering tests."""
    reg = ProviderRegistry()
    reg.register("nexar", MockProvider(), tier="premium")
    reg.register("oemsecrets", MockProvider(), tier="free")
    reg.set_active("oemsecrets")
    return reg


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _register_and_login(client: TestClient, db_session, email: str, password: str = "password123") -> str:
    # Register with email and name (no password)
    client.post(REGISTER_URL, json={"email": email, "name": "Test User"})

    # Create a PasswordResetToken via db_session
    from app.models.password_reset_token import PasswordResetToken

    user = db_session.query(User).filter(User.email == email).first()
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    db_session.add(PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))
    db_session.commit()

    # Set password via reset-password endpoint
    client.post("/auth/reset-password", json={"token": raw_token, "new_password": password})

    # Login
    resp = client.post(LOGIN_URL, json={"email": email, "password": password})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_project(client: TestClient, token: str, name: str = "Project") -> dict:
    resp = client.post(PROJECTS_URL, json={"name": name}, headers=_auth(token))
    return resp


def _csv_file(num_rows: int) -> dict:
    lines = ["Reference,Value,Footprint,MPN"]
    for i in range(num_rows):
        lines.append(f"R{i},10k,R_0402,RC0402FR-0710KL")
    csv_bytes = "\n".join(lines).encode()
    return {"file": ("bom.csv", io.BytesIO(csv_bytes), "text/csv")}


def _get_user(db: Session, email: str) -> User:
    return db.query(User).filter(User.email == email).one()


# ---------------------------------------------------------------------------
# Project creation limit — free user at default limit → 403
# ---------------------------------------------------------------------------


def test_free_user_at_default_project_limit(client: TestClient, db_session: Session):
    from app.core.database import settings

    token = _register_and_login(client, db_session, "alice@example.com")

    # Fill up to the default limit
    for i in range(settings.free_plan_max_projects):
        resp = _create_project(client, token, f"Project {i}")
        assert resp.status_code == 201

    # One more should be rejected
    resp = _create_project(client, token, "One Too Many")
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["error"] == "plan_limit_exceeded"
    assert detail["limit"] == "projects"
    assert detail["max"] == settings.free_plan_max_projects


# ---------------------------------------------------------------------------
# Project creation limit — free user with override hits override value (not default)
# ---------------------------------------------------------------------------


def test_free_user_with_project_override_uses_override_value(
    client: TestClient, db_session: Session
):
    from app.core.database import settings

    token = _register_and_login(client, db_session, "bob@example.com")

    # Set a per-user override lower than the default
    override = max(1, settings.free_plan_max_projects - 1)
    db_session.query(User).filter(User.email == "bob@example.com").update(
        {"max_projects_override": override}
    )
    db_session.commit()

    # Fill to the override limit
    for i in range(override):
        resp = _create_project(client, token, f"Project {i}")
        assert resp.status_code == 201

    # Should be blocked at the override value, not the default
    resp = _create_project(client, token, "Blocked")
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["max"] == override
    assert detail["max"] != settings.free_plan_max_projects


# ---------------------------------------------------------------------------
# Paid user never blocked regardless of override values
# ---------------------------------------------------------------------------


def test_paid_user_not_blocked_regardless_of_override(
    client: TestClient, db_session: Session
):
    from app.core.database import settings

    token = _register_and_login(client, db_session, "carol@example.com")

    # Upgrade to paid and set an override that would block a free user
    db_session.query(User).filter(User.email == "carol@example.com").update(
        {"plan": "paid", "max_projects_override": 1}
    )
    db_session.commit()

    # Create more projects than the override and the default limit allow
    for i in range(settings.free_plan_max_projects + 2):
        resp = _create_project(client, token, f"Project {i}")
        assert resp.status_code == 201, f"Paid user blocked on project {i}: {resp.json()}"


# ---------------------------------------------------------------------------
# BOM import parts limit — free user hitting parts limit → 403
# ---------------------------------------------------------------------------


def test_free_user_hitting_parts_limit(client: TestClient, db_session: Session):
    from app.core.database import settings

    token = _register_and_login(client, db_session, "dave@example.com")
    resp = _create_project(client, token, "BigBoard")
    assert resp.status_code == 201
    project_id = resp.json()["id"]

    # Import a CSV with one more row than the parts limit
    too_many = settings.free_plan_max_parts_per_project + 1
    resp = client.post(
        f"/projects/{project_id}/bom/import",
        files=_csv_file(too_many),
        headers=_auth(token),
    )
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["error"] == "plan_limit_exceeded"
    assert detail["limit"] == "parts_per_project"
    assert detail["max"] == settings.free_plan_max_parts_per_project


# ---------------------------------------------------------------------------
# Provider query — free user sees skipped_providers
# ---------------------------------------------------------------------------


def test_free_user_query_returns_skipped_providers(
    client: TestClient, db_session: Session
):
    from app.core.database import settings

    token = _register_and_login(client, db_session, "eve@example.com")
    resp = _create_project(client, token, "Board")
    assert resp.status_code == 201
    project_id = resp.json()["id"]

    # Override the provider registry and fallback order so nexar (premium) is in
    # the chain but gets filtered out for this free user.
    mock_reg = _mock_registry_with_tiers()
    app.dependency_overrides[get_registry] = lambda: mock_reg
    original_fallback = settings.provider_fallback_order
    settings.provider_fallback_order = "nexar,oemsecrets"

    try:
        resp = client.post(f"/projects/{project_id}/match", headers=_auth(token))
    finally:
        app.dependency_overrides.pop(get_registry, None)
        settings.provider_fallback_order = original_fallback

    assert resp.status_code == 200
    data = resp.json()
    assert "skipped_providers" in data
    skipped_names = [sp["name"] for sp in data["skipped_providers"]]
    assert "nexar" in skipped_names
    for sp in data["skipped_providers"]:
        assert sp["reason"] == "premium_plan_required"


# ---------------------------------------------------------------------------
# Provider query — paid user does not see skipped_providers
# ---------------------------------------------------------------------------


def test_paid_user_query_has_no_skipped_providers(
    client: TestClient, db_session: Session
):
    from app.core.database import settings

    token = _register_and_login(client, db_session, "frank@example.com")

    db_session.query(User).filter(User.email == "frank@example.com").update({"plan": "paid"})
    db_session.commit()

    resp = _create_project(client, token, "Board")
    assert resp.status_code == 201
    project_id = resp.json()["id"]

    mock_reg = _mock_registry_with_tiers()
    app.dependency_overrides[get_registry] = lambda: mock_reg
    original_fallback = settings.provider_fallback_order
    settings.provider_fallback_order = "nexar,oemsecrets"

    try:
        resp = client.post(f"/projects/{project_id}/match", headers=_auth(token))
    finally:
        app.dependency_overrides.pop(get_registry, None)
        settings.provider_fallback_order = original_fallback

    assert resp.status_code == 200
    data = resp.json()
    assert data["skipped_providers"] == []


# ---------------------------------------------------------------------------
# Trial expiry enforcement — expired trial → free-tier limits
# ---------------------------------------------------------------------------


def test_expired_trial_user_gets_free_limits(
    client: TestClient, db_session: Session
):
    """User with is_trial_provisioned=True and trial_ends_at in the past
    should receive free-tier limits regardless of plan value."""
    from app.core.database import settings

    token = _register_and_login(client, db_session, "expired-trial@example.com")

    # Mark as trial-provisioned with an expired date
    db_session.query(User).filter(User.email == "expired-trial@example.com").update(
        {
            "is_trial_provisioned": True,
            "trial_ends_at": datetime(2025, 1, 1, tzinfo=UTC),  # past
        }
    )
    db_session.commit()

    # Should be subject to free-tier project limits
    for i in range(settings.free_plan_max_projects):
        resp = _create_project(client, token, f"Project {i}")
        assert resp.status_code == 201

    resp = _create_project(client, token, "One Too Many")
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["error"] == "plan_limit_exceeded"


def test_expired_trial_with_paid_plan_still_gets_free_limits(
    client: TestClient, db_session: Session
):
    """Even if plan='paid', an expired trial-provisioned user must get
    free-tier limits (enforcement-only degradation)."""
    from app.core.database import settings

    token = _register_and_login(client, db_session, "expired-paid@example.com")

    db_session.query(User).filter(User.email == "expired-paid@example.com").update(
        {
            "plan": "paid",
            "is_trial_provisioned": True,
            "trial_ends_at": datetime(2025, 6, 1, tzinfo=UTC),  # past
        }
    )
    db_session.commit()

    # Free-tier limit should apply
    for i in range(settings.free_plan_max_projects):
        resp = _create_project(client, token, f"Project {i}")
        assert resp.status_code == 201

    resp = _create_project(client, token, "Blocked")
    assert resp.status_code == 403


def test_active_trial_user_gets_paid_limits(
    client: TestClient, db_session: Session
):
    """Active trial (trial_ends_at in future) should still receive paid limits."""
    from datetime import timedelta

    token = _register_and_login(client, db_session, "active-trial@example.com")

    future = datetime.now(UTC) + timedelta(days=30)
    db_session.query(User).filter(User.email == "active-trial@example.com").update(
        {
            "is_trial_provisioned": True,
            "trial_ends_at": future,
        }
    )
    db_session.commit()

    # Paid users are not blocked by project limits (unlimited)
    for i in range(20):
        resp = _create_project(client, token, f"Project {i}")
        assert resp.status_code == 201


def test_trial_provisioned_without_expiry_not_expired(
    client: TestClient, db_session: Session
):
    """User with is_trial_provisioned=True but trial_ends_at=None
    should NOT be treated as expired.  Without an active trial or plan='paid',
    they get free-tier limits (no trial expiry → no degradation needed)."""
    from app.core.database import settings

    token = _register_and_login(client, db_session, "no-expiry@example.com")

    db_session.query(User).filter(User.email == "no-expiry@example.com").update(
        {
            "is_trial_provisioned": True,
            "trial_ends_at": None,
        }
    )
    db_session.commit()

    # plan="free" + no active trial → free limits apply
    # _is_trial_expired returns False (None → not expired)
    # but _is_trial_active also returns False → is_paid stays False
    # So free-tier limits should apply
    for i in range(settings.free_plan_max_projects):
        resp = _create_project(client, token, f"Project {i}")
        assert resp.status_code == 201

    resp = _create_project(client, token, "One Too Many")
    assert resp.status_code == 403
