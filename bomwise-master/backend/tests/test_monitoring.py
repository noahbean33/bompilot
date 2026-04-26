"""
Tests for the monitoring task (check_and_flag / run_monitor) and the
flags API endpoints.

No live provider calls and no real SMTP are made — everything is mocked.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.part_flag import FLAG_OUT_OF_STOCK, FLAG_PRICE_CHANGE, PartFlag
from app.models.part_result import PartResult as PartResultRow
from app.models.project import BomLine, Project
from app.providers.registry import ProviderRegistry
from app.providers.schema import (
    DistributorStock,
    ParametricQuery,
    PartResult as ProviderResult,
    PriceBreak,
    ProviderCapabilities,
)
from app.schemas.preferences import MergedPreferences
from app.worker.tasks import check_and_flag, run_monitor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 6, tzinfo=UTC)


def _make_provider_result(
    mpn: str = "RC0402",
    stock: int = 1000,
    unit_price: float = 0.10,
) -> ProviderResult:
    return ProviderResult(
        mpn=mpn,
        manufacturer="Yageo",
        description="Resistor",
        package="0402",
        pricing=[PriceBreak(quantity=1, unit_price=unit_price, currency="USD")],
        stock_total=stock,
        distributors=[DistributorStock(distributor="digikey", stock=stock, url=None)],
        lifecycle_status=None,
        tech_specs=None,
        datasheet_url=None,
        similar_parts=None,
        source_provider="mock",
        retrieved_at=_NOW,
        match_type="exact_mpn",
    )


def _make_stored_part(
    db: Session,
    project: Project,
    mpn: str = "RC0402",
    stock: int = 1000,
    unit_price: float = 0.10,
) -> PartResultRow:
    bom_line = BomLine(
        project_id=project.id,
        reference="R1",
        mpn_raw=mpn,
        quantity=1,
        raw_fields={},
    )
    db.add(bom_line)
    db.flush()

    part = PartResultRow(
        bom_line_id=bom_line.id,
        rank=1,
        mpn=mpn,
        manufacturer="Yageo",
        description="Resistor",
        package="0402",
        distributor="digikey",
        unit_price=unit_price,
        stock=stock,
        lifecycle_status=None,
        tech_specs=None,
        datasheet_url=None,
        source_provider="mock",
        match_type="exact_mpn",
        retrieved_at=_NOW,
    )
    db.add(part)
    db.flush()
    return part


def _make_project(db: Session, user_id: int = 1) -> Project:
    project = Project(user_id=user_id, name="Test Project")
    db.add(project)
    db.flush()
    return project


class MockMonitorProvider:
    """Synchronous-friendly mock for the provider; returns preset results."""

    def __init__(self, results: list[ProviderResult]) -> None:
        self._results = results

    async def search_by_mpn(
        self, mpn: str, quantity: int, preferences: MergedPreferences
    ) -> list[ProviderResult]:
        return self._results

    async def search_by_distributor_pn(self, distributor, pn, quantity):
        raise NotImplementedError

    async def search_parametric(self, params, preferences):
        raise NotImplementedError

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            has_lifecycle_status=False,
            has_tech_specs=False,
            has_datasheet_urls=False,
            has_similar_parts=False,
            has_parametric_search=False,
            distributor_coverage=[],
        )


def _mock_registry(results: list[ProviderResult]) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register("mock", MockMonitorProvider(results))
    reg.set_active("mock")
    return reg


# ---------------------------------------------------------------------------
# check_and_flag unit tests
# ---------------------------------------------------------------------------


def test_flag_created_on_stock_drop_to_zero(db_session: Session):
    """Stock drops from > 0 to 0 → out_of_stock flag created."""
    project = _make_project(db_session)
    stored = _make_stored_part(db_session, project, stock=500, unit_price=0.10)

    new_result = _make_provider_result(stock=0, unit_price=0.10)
    flags = check_and_flag(db_session, stored, [new_result])

    assert len(flags) == 1
    assert flags[0].flag_type == FLAG_OUT_OF_STOCK
    assert flags[0].old_value == "500"
    assert flags[0].new_value == "0"
    assert stored.stock == 0  # updated in-place


def test_flag_created_on_large_price_increase(db_session: Session):
    """Price rises by > 10% → price_change flag created."""
    project = _make_project(db_session)
    stored = _make_stored_part(db_session, project, stock=500, unit_price=0.10)

    new_result = _make_provider_result(stock=500, unit_price=0.12)  # +20%
    flags = check_and_flag(db_session, stored, [new_result])

    assert len(flags) == 1
    assert flags[0].flag_type == FLAG_PRICE_CHANGE
    assert float(flags[0].old_value) == pytest.approx(0.10)
    assert float(flags[0].new_value) == pytest.approx(0.12)


def test_flag_created_on_large_price_decrease(db_session: Session):
    """Price drops by > 10% also triggers a price_change flag."""
    project = _make_project(db_session)
    stored = _make_stored_part(db_session, project, stock=500, unit_price=0.10)

    new_result = _make_provider_result(stock=500, unit_price=0.08)  # -20%
    flags = check_and_flag(db_session, stored, [new_result])

    assert len(flags) == 1
    assert flags[0].flag_type == FLAG_PRICE_CHANGE


def test_no_flag_on_small_price_change(db_session: Session):
    """Price change < 10% does NOT create a flag."""
    project = _make_project(db_session)
    stored = _make_stored_part(db_session, project, stock=500, unit_price=0.10)

    new_result = _make_provider_result(stock=500, unit_price=0.105)  # +5%
    flags = check_and_flag(db_session, stored, [new_result])

    assert flags == []


def test_no_flag_when_stock_stays_zero(db_session: Session):
    """Stock was already 0 — no out_of_stock flag on repeated check."""
    project = _make_project(db_session)
    stored = _make_stored_part(db_session, project, stock=0, unit_price=0.10)

    new_result = _make_provider_result(stock=0, unit_price=0.10)
    flags = check_and_flag(db_session, stored, [new_result])

    assert flags == []


def test_both_flags_created_simultaneously(db_session: Session):
    """Stock drops to 0 AND price changes > 10% → two flags."""
    project = _make_project(db_session)
    stored = _make_stored_part(db_session, project, stock=500, unit_price=0.10)

    new_result = _make_provider_result(stock=0, unit_price=0.15)  # stock gone + +50% price
    flags = check_and_flag(db_session, stored, [new_result])

    flag_types = {f.flag_type for f in flags}
    assert FLAG_OUT_OF_STOCK in flag_types
    assert FLAG_PRICE_CHANGE in flag_types


def test_stored_values_updated_after_check(db_session: Session):
    """After check_and_flag the stored row reflects the new stock and price."""
    project = _make_project(db_session)
    stored = _make_stored_part(db_session, project, stock=500, unit_price=0.10)

    new_result = _make_provider_result(stock=200, unit_price=0.09)
    check_and_flag(db_session, stored, [new_result])

    assert stored.stock == 200
    assert stored.unit_price == pytest.approx(0.09)


# ---------------------------------------------------------------------------
# run_monitor integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_monitor_creates_flags(db_session: Session):
    """run_monitor processes all part_results and persists flags."""
    project = _make_project(db_session)
    _make_stored_part(db_session, project, stock=500, unit_price=0.10)

    registry = _mock_registry([_make_provider_result(stock=0, unit_price=0.10)])
    count = await run_monitor(db_session, registry)

    assert count == 1
    flags = db_session.query(PartFlag).all()
    assert len(flags) == 1
    assert flags[0].flag_type == FLAG_OUT_OF_STOCK


@pytest.mark.asyncio
async def test_run_monitor_no_flags_on_no_change(db_session: Session):
    """No flags created when provider returns identical data."""
    project = _make_project(db_session)
    _make_stored_part(db_session, project, stock=500, unit_price=0.10)

    registry = _mock_registry([_make_provider_result(stock=500, unit_price=0.10)])
    count = await run_monitor(db_session, registry)

    assert count == 0
    assert db_session.query(PartFlag).count() == 0


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"
PROJECTS_URL = "/projects/"


def _register_and_login(client: TestClient, db_session, email: str, password: str = "pass1234") -> str:
    import hashlib
    import secrets
    from datetime import UTC, datetime, timedelta
    from app.models.password_reset_token import PasswordResetToken
    from app.models.user import User

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


def test_get_project_flags_empty(client: TestClient, db_session):
    """GET /projects/{id}/flags returns [] when no flags exist."""
    token = _register_and_login(client, db_session, "flagtest1@example.com")
    proj = client.post(PROJECTS_URL, json={"name": "FlagProj"}, headers=_auth(token)).json()

    resp = client.get(f"/projects/{proj['id']}/flags", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_acknowledge_flag_sets_acknowledged(client: TestClient, db_session: Session):
    """POST /flags/{id}/acknowledge sets acknowledged=true."""
    from app.main import app
    from app.core.database import get_db

    # Register user and project via HTTP so the real user row exists
    token = _register_and_login(client, db_session, "flagtest2@example.com")
    proj = client.post(PROJECTS_URL, json={"name": "FlagProj2"}, headers=_auth(token)).json()
    project_id = proj["id"]

    # Create bom_line + part_result + flag directly in the test DB session
    bom_line = BomLine(
        project_id=project_id,
        reference="C1",
        mpn_raw="RC0402",
        quantity=1,
        raw_fields={},
    )
    db_session.add(bom_line)
    db_session.flush()

    part = PartResultRow(
        bom_line_id=bom_line.id,
        rank=1,
        mpn="RC0402",
        manufacturer="Yageo",
        description=None,
        package=None,
        distributor="digikey",
        unit_price=0.10,
        stock=0,
        lifecycle_status=None,
        tech_specs=None,
        datasheet_url=None,
        source_provider="mock",
        match_type="exact_mpn",
        retrieved_at=_NOW,
    )
    db_session.add(part)
    db_session.flush()

    flag = PartFlag(
        part_result_id=part.id,
        flag_type=FLAG_OUT_OF_STOCK,
        old_value="500",
        new_value="0",
        acknowledged=False,
    )
    db_session.add(flag)
    db_session.commit()

    # Acknowledge via API
    resp = client.post(f"/flags/{flag.id}/acknowledge", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["acknowledged"] is True
    assert data["id"] == flag.id


def test_acknowledge_flag_not_found(client: TestClient, db_session):
    """Acknowledging a non-existent flag returns 404."""
    token = _register_and_login(client, db_session, "flagtest3@example.com")
    resp = client.post("/flags/99999/acknowledge", headers=_auth(token))
    assert resp.status_code == 404


def test_get_flags_requires_auth(client: TestClient, db_session):
    resp = client.get("/projects/1/flags")
    assert resp.status_code == 401


def test_acknowledge_requires_auth(client: TestClient, db_session):
    resp = client.post("/flags/1/acknowledge")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Email digest test
# ---------------------------------------------------------------------------


def test_send_digest_email_mocks_smtp(db_session: Session):
    """send_digest_email calls _send_smtp when unacknowledged flags exist."""
    from app.models.user import User
    from app.worker.email import send_digest_email

    # Create minimal user + data in the test DB
    user = User(
        email="digest@example.com",
        hashed_password="x",
        subscription_tier="free",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    project = Project(user_id=user.id, name="DigestProj")
    db_session.add(project)
    db_session.flush()

    bom_line = BomLine(
        project_id=project.id, reference="R1", mpn_raw="RC0402", quantity=1, raw_fields={}
    )
    db_session.add(bom_line)
    db_session.flush()

    part = PartResultRow(
        bom_line_id=bom_line.id,
        rank=1,
        mpn="RC0402",
        manufacturer="Yageo",
        description=None,
        package=None,
        distributor="digikey",
        unit_price=0.10,
        stock=0,
        lifecycle_status=None,
        tech_specs=None,
        datasheet_url=None,
        source_provider="mock",
        match_type="exact_mpn",
        retrieved_at=_NOW,
    )
    db_session.add(part)
    db_session.flush()

    flag = PartFlag(
        part_result_id=part.id,
        flag_type=FLAG_OUT_OF_STOCK,
        old_value="500",
        new_value="0",
        acknowledged=False,
    )
    db_session.add(flag)
    db_session.commit()

    with patch("app.worker.email._send_smtp") as mock_smtp:
        result = send_digest_email(user.id, db=db_session)

    assert result is True
    mock_smtp.assert_called_once()
    _, subject, body = mock_smtp.call_args[0]
    assert "RC0402" in body
    assert "DigestProj" in body


def test_send_digest_email_no_flags_returns_false(db_session: Session):
    """send_digest_email returns False when there are no unacknowledged flags."""
    from app.models.user import User
    from app.worker.email import send_digest_email

    user = User(
        email="noflags@example.com",
        hashed_password="x",
        subscription_tier="free",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    with patch("app.worker.email._send_smtp") as mock_smtp:
        result = send_digest_email(user.id, db=db_session)

    assert result is False
    mock_smtp.assert_not_called()
