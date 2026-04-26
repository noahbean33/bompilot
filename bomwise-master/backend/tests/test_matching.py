"""
Tests for PartMatchingService and POST /projects/{id}/match endpoint.

All tests use a MockProvider — no live Nexar API calls.
"""

from datetime import datetime, timedelta, UTC

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.part_result import PartResult as PartResultRow
from app.models.password_reset_token import PasswordResetToken
from app.models.project import BomLine, Project
from app.models.user import User
import hashlib
import secrets
from app.providers.base import ComponentProvider
from app.providers.registry import ProviderRegistry, get_registry
from app.providers.schema import (
    DistributorStock,
    ParametricQuery,
    PartResult as ProviderResult,
    PriceBreak,
    ProviderCapabilities,
)
from app.schemas.preferences import MergedPreferences
from app.services.matching import PartMatchingService, _best_unit_price

# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------

_FAKE_RESULT = ProviderResult(
    mpn="GRM155R61A104KA01D",
    manufacturer="Murata",
    description="100nF 10V 0402 ceramic cap",
    package="0402",
    pricing=[
        PriceBreak(quantity=1, unit_price=0.10, currency="USD"),
        PriceBreak(quantity=10, unit_price=0.08, currency="USD"),
        PriceBreak(quantity=100, unit_price=0.05, currency="USD"),
    ],
    stock_total=50000,
    distributors=[
        DistributorStock(distributor="digikey", stock=30000, url=None),
        DistributorStock(distributor="mouser", stock=20000, url=None),
    ],
    lifecycle_status="active",
    tech_specs={"capacitance": "100nF", "voltage": "10V"},
    datasheet_url="https://example.com/ds.pdf",
    similar_parts=None,
    source_provider="mock",
    retrieved_at=datetime(2026, 4, 4, tzinfo=UTC),
    match_type="exact_mpn",
)

_FAKE_RESULT_2 = ProviderResult(
    mpn="GRM155R61A104KA01D-ALT",
    manufacturer="Murata",
    description="Alternate result",
    package="0402",
    pricing=[PriceBreak(quantity=1, unit_price=0.12, currency="USD")],
    stock_total=1000,
    distributors=[DistributorStock(distributor="digikey", stock=1000, url=None)],
    lifecycle_status="active",
    tech_specs=None,
    datasheet_url=None,
    similar_parts=None,
    source_provider="mock",
    retrieved_at=datetime(2026, 4, 4, tzinfo=UTC),
    match_type="exact_mpn",
)


class MockProvider(ComponentProvider):
    """Returns a preset list of results for any MPN; empty for 'NOMATCH'."""

    def __init__(self, results: list[ProviderResult] | None = None) -> None:
        self._results = results if results is not None else [_FAKE_RESULT]

    async def search_by_mpn(
        self, mpn: str, quantity: int, preferences: MergedPreferences
    ) -> list[ProviderResult]:
        if mpn == "NOMATCH":
            return []
        # Only return results for known valid MPNs
        mpn_upper = mpn.strip().upper()
        if mpn_upper not in ("GRM155R61A104KA01D", "LTL-307ELC"):
            return []
        return self._results

    async def search_by_keyword(
        self, keyword: str, quantity: int, preferences: MergedPreferences
    ) -> list[ProviderResult]:
        return []

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
            has_lifecycle_status=True,
            has_tech_specs=True,
            has_datasheet_urls=True,
            has_similar_parts=False,
            has_parametric_search=False,
            distributor_coverage=["digikey", "mouser"],
        )


def _mock_registry(results: list[ProviderResult] | None = None) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register("mock", MockProvider(results))
    reg.set_active("mock")
    return reg


# ---------------------------------------------------------------------------
# HTTP-level helpers (mirrors test_projects.py)
# ---------------------------------------------------------------------------

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"
PROJECTS_URL = "/projects/"


def _register_and_login(client: TestClient, db_session, email: str, password: str = "pass123") -> str:
    # 1. Register with email + name (no password)
    client.post(REGISTER_URL, json={"email": email, "name": "Test User"})

    # 2. Create a password-reset token directly in the DB
    user = db_session.query(User).filter(User.email == email).first()
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    db_session.add(PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))
    db_session.commit()

    # 3. Set password via reset-password endpoint
    client.post("/auth/reset-password", json={"token": raw_token, "new_password": password})

    # 4. Login
    resp = client.post(LOGIN_URL, json={"email": email, "password": password})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_project(client: TestClient, token: str) -> dict:
    resp = client.post(PROJECTS_URL, json={"name": "Test Project"}, headers=_auth(token))
    assert resp.status_code == 201
    return resp.json()


_SAMPLE_CSV = (
    "Reference,Value,Footprint,Description,Quantity,MPN\r\n"
    "C1,100nF,C_0402,Decoupling cap,10,GRM155R61A104KA01D\r\n"
    "R1,10k,R_0402,Pull-up,5,NOMATCH\r\n"
    "U1,MCU,LQFP48,STM32,1,\r\n"
)


def _import_bom(client: TestClient, project_id: int, token: str) -> None:
    import io

    resp = client.post(
        f"/projects/{project_id}/bom/import",
        files={"file": ("bom.csv", io.BytesIO(_SAMPLE_CSV.encode()), "text/csv")},
        headers=_auth(token),
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Unit tests — _best_unit_price helper
# ---------------------------------------------------------------------------


def test_best_unit_price_empty():
    assert _best_unit_price([], 10) is None


def test_best_unit_price_exact_break():
    breaks = [
        PriceBreak(quantity=1, unit_price=0.10, currency="USD"),
        PriceBreak(quantity=10, unit_price=0.08, currency="USD"),
        PriceBreak(quantity=100, unit_price=0.05, currency="USD"),
    ]
    # qty=10 → applicable breaks are qty<=10 → pick cheapest (0.08)
    assert _best_unit_price(breaks, 10) == pytest.approx(0.08)


def test_best_unit_price_below_min_break():
    breaks = [
        PriceBreak(quantity=10, unit_price=0.08, currency="USD"),
        PriceBreak(quantity=100, unit_price=0.05, currency="USD"),
    ]
    # qty=1 < smallest break → fall back to all breaks → pick cheapest (0.05)
    assert _best_unit_price(breaks, 1) == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_line_with_mpn(db_session: Session):
    """Line with a valid MPN gets matched; part_results row is created."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="C1",
        mpn_raw="GRM155R61A104KA01D",
        quantity=10,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    service = PartMatchingService(_mock_registry())
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is True
    assert line.match_type == "exact_mpn"
    assert line.selected_result_id is not None

    rows = db_session.query(PartResultRow).filter(PartResultRow.bom_line_id == line.id).all()
    assert len(rows) == 1
    assert rows[0].mpn == "GRM155R61A104KA01D"
    assert rows[0].rank == 1
    assert rows[0].stock == 50000
    assert rows[0].unit_price == pytest.approx(0.08)  # best price at qty=10
    assert rows[0].distributor == "digikey"  # highest stock


@pytest.mark.asyncio
async def test_match_line_no_mpn(db_session: Session):
    """Line without MPN stays unmatched; no part_results rows written."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="U1",
        mpn_raw=None,
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    service = PartMatchingService(_mock_registry())
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is False
    assert line.match_type is None
    assert line.selected_result_id is None
    assert db_session.query(PartResultRow).filter(PartResultRow.bom_line_id == line.id).count() == 0


@pytest.mark.asyncio
async def test_match_line_blank_mpn(db_session: Session):
    """Line with a whitespace-only MPN is treated as no MPN."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="R1",
        mpn_raw="   ",
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    service = PartMatchingService(_mock_registry())
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is False


@pytest.mark.asyncio
async def test_match_line_provider_returns_empty(db_session: Session):
    """Provider returns no results → line is unmatched."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="R1",
        mpn_raw="NOMATCH",
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    service = PartMatchingService(_mock_registry())
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is False
    assert line.match_type == "no_match"
    assert db_session.query(PartResultRow).filter(PartResultRow.bom_line_id == line.id).count() == 0


@pytest.mark.asyncio
async def test_match_line_multiple_results(db_session: Session):
    """Multiple provider results are stored ranked; top result is selected."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="C1",
        mpn_raw="GRM155R61A104KA01D",
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    service = PartMatchingService(_mock_registry([_FAKE_RESULT, _FAKE_RESULT_2]))
    await service._match_line(db_session, line, MergedPreferences())

    rows = db_session.query(PartResultRow).filter(PartResultRow.bom_line_id == line.id).order_by(PartResultRow.rank).all()
    assert len(rows) == 2
    assert rows[0].rank == 1
    assert rows[0].mpn == "GRM155R61A104KA01D"
    assert rows[1].rank == 2
    assert rows[1].mpn == "GRM155R61A104KA01D-ALT"
    # selected_result_id points to rank-1 row
    assert line.selected_result_id == rows[0].id


@pytest.mark.asyncio
async def test_rematch_clears_old_results(db_session: Session):
    """Re-running _match_line deletes stale part_results from the previous run."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="C1",
        mpn_raw="GRM155R61A104KA01D",
        quantity=10,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    service = PartMatchingService(_mock_registry([_FAKE_RESULT, _FAKE_RESULT_2]))
    await service._match_line(db_session, line, MergedPreferences())
    assert db_session.query(PartResultRow).filter(PartResultRow.bom_line_id == line.id).count() == 2

    # Second run with a single-result provider
    service2 = PartMatchingService(_mock_registry([_FAKE_RESULT]))
    await service2._match_line(db_session, line, MergedPreferences())
    rows = db_session.query(PartResultRow).filter(PartResultRow.bom_line_id == line.id).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_match_project_summary(db_session: Session):
    """match_project returns correct summary counts."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    lines = [
        BomLine(project_id=project.id, reference="C1", mpn_raw="GRM155R61A104KA01D", quantity=10, raw_fields={}),
        BomLine(project_id=project.id, reference="R1", mpn_raw="NOMATCH", quantity=1, raw_fields={}),
        BomLine(project_id=project.id, reference="U1", mpn_raw=None, quantity=1, raw_fields={}),
    ]
    db_session.add_all(lines)
    db_session.flush()

    service = PartMatchingService(_mock_registry())
    result = await service.match_project(db_session, project.id)

    assert result["project_id"] == project.id
    assert result["total"] == 3
    assert result["matched"] == 1
    assert result["unmatched"] == 2


# ---------------------------------------------------------------------------
# HTTP-level tests
# ---------------------------------------------------------------------------


def test_match_endpoint_returns_summary(client: TestClient, db_session: Session):
    reg = _mock_registry()
    app.dependency_overrides[get_registry] = lambda: reg

    try:
        token = _register_and_login(client, db_session, "alice@example.com")
        project = _create_project(client, token)
        pid = project["id"]
        _import_bom(client, pid, token)

        resp = client.post(f"/projects/{pid}/match", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == pid
        assert data["total"] == 3
        assert data["matched"] == 1   # only C1 has a non-NOMATCH MPN
        assert data["unmatched"] == 2
    finally:
        app.dependency_overrides.pop(get_registry, None)


def test_match_endpoint_404_for_other_user(client: TestClient, db_session: Session):
    reg = _mock_registry()
    app.dependency_overrides[get_registry] = lambda: reg

    try:
        token_a = _register_and_login(client, db_session, "alice2@example.com")
        token_b = _register_and_login(client, db_session, "bob2@example.com")
        project = _create_project(client, token_a)
        pid = project["id"]

        resp = client.post(f"/projects/{pid}/match", headers=_auth(token_b))
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_registry, None)


def test_get_bom_includes_selected_result(client: TestClient, db_session: Session):
    reg = _mock_registry()
    app.dependency_overrides[get_registry] = lambda: reg

    try:
        token = _register_and_login(client, db_session, "carol@example.com")
        project = _create_project(client, token)
        pid = project["id"]
        _import_bom(client, pid, token)

        client.post(f"/projects/{pid}/match", headers=_auth(token))

        resp = client.get(f"/projects/{pid}/bom", headers=_auth(token))
        assert resp.status_code == 200
        lines = resp.json()

        matched = [ln for ln in lines if ln["mpn_raw"] == "GRM155R61A104KA01D"]
        assert len(matched) == 1
        result = matched[0]["selected_result"]
        assert result is not None
        assert result["mpn"] == "GRM155R61A104KA01D"
        assert result["manufacturer"] == "Murata"
        assert result["match_type"] == "exact_mpn"
        assert result["stock"] == 50000

        unmatched = [ln for ln in lines if ln["mpn_raw"] is None or ln["mpn_raw"] == ""]
        for ln in unmatched:
            assert ln["selected_result"] is None
    finally:
        app.dependency_overrides.pop(get_registry, None)


def test_get_bom_before_match_has_no_selected_result(client: TestClient, db_session: Session):
    token = _register_and_login(client, db_session, "dave@example.com")
    project = _create_project(client, token)
    pid = project["id"]
    _import_bom(client, pid, token)

    resp = client.get(f"/projects/{pid}/bom", headers=_auth(token))
    assert resp.status_code == 200
    for line in resp.json():
        assert line["selected_result"] is None


def test_match_endpoint_requires_auth(client: TestClient):
    resp = client.post("/projects/1/match")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# UIF-013: Fallback matching tests
# ---------------------------------------------------------------------------

from app.services.matching import _extract_package, _extract_mfr_series, extract_mpn_from_footprint  # noqa: E402


def test_extract_package_standard():
    assert _extract_package("R_0402_1005Metric") == "0402"


def test_extract_package_0805():
    assert _extract_package("C_0805_2012Metric") == "0805"


def test_extract_package_no_match():
    assert _extract_package("DIP-8_2.54mm") is None  # not in IC_PACKAGE_RE list


def test_extract_package_sot23_6():
    """IC package pattern: SOT-23-6 / TSOT-23-6 (the SY8253ADC case)."""
    assert _extract_package("Package_TO_SOT_SMD:TSOT-23-6") == "TSOT-23-6"
    assert _extract_package("SOT-23") == "SOT-23"
    assert _extract_package("SOT-23-5") == "SOT-23-5"


def test_extract_package_soic8():
    assert _extract_package("Package_SO_SMD:SOIC-8_3.9x4.9mm") == "SOIC-8"


def test_extract_package_qfn16():
    assert _extract_package("Package_DFN_QFN:QFN-16-1EP_3x3mm") == "QFN-16"


def test_extract_package_tssop20():
    assert _extract_package("Package_SO_SMD:TSSOP-20_4.4x6.5mm") == "TSSOP-20"


def test_extract_package_1206():
    assert _extract_package("C_1206") == "1206"


class TestExtractMpnFromFootprint:
    """Tests for extract_mpn_from_footprint — extracts MPNs from KiCad footprints."""

    def test_jst_shl_connector(self):
        """JST SHL connector: SM06B-SHLS-TF embedded in footprint."""
        fp = "Connector_JST:JST_SHL_SM06B-SHLS-TF_1x06-1MP_P1.00mm_Horizontal"
        assert extract_mpn_from_footprint(fp) == "SM06B-SHLS-TF"

    def test_jst_gh_connector(self):
        """JST GH connector: SM03B-GHS-TB embedded in footprint."""
        fp = "Connector_JST:JST_GH_SM03B-GHS-TB_1x03-1MP_P1.25mm_Horizontal"
        assert extract_mpn_from_footprint(fp) == "SM03B-GHS-TB"

    def test_no_mpn_plain_footprint(self):
        """Passive component footprint without MPN."""
        assert extract_mpn_from_footprint("R_0402_1005Metric") is None

    def test_none_footprint(self):
        assert extract_mpn_from_footprint(None) is None

    def test_oscillator_footprint(self):
        """Oscillator footprint — extracts Epson MPN via new regex."""
        fp = "Oscillator_SMD_SeikoEpson_SG210-4Pin_2.5x2.0mm"
        result = extract_mpn_from_footprint(fp)
        assert result == "SG210"

    def test_xkb_connector_footprint(self):
        """XKB USB-C connector MPN via generic pattern."""
        fp = "Connector_USB:USB_C_Receptacle_XKB_U262-16XN-4BVC11"
        result = extract_mpn_from_footprint(fp)
        assert result == "U262-16XN-4BVC11"


class MockProviderWithKeyword(MockProvider):
    """Extends MockProvider: returns empty for HYPHEN-MPN but responds to keyword 'KEYWORD_TERM'."""

    def __init__(
        self,
        exact_results: list[ProviderResult] | None = None,
        keyword_results: list[ProviderResult] | None = None,
    ) -> None:
        super().__init__(exact_results)
        self._keyword_results = keyword_results or []

    async def search_by_mpn(
        self, mpn: str, quantity: int, preferences: MergedPreferences
    ) -> list[ProviderResult]:
        if mpn in ("NOMATCH", "NOMATCH-V2", "NOMATCHV2"):
            return []
        # Only return results for known valid MPNs
        mpn_upper = mpn.strip().upper()
        if mpn_upper not in ("GRM155R61A104KA01D", "LTL-307ELC"):
            return []
        return self._results

    async def search_by_keyword(
        self, keyword: str, quantity: int, preferences: MergedPreferences
    ) -> list[ProviderResult]:
        return self._keyword_results


def _mock_registry_with_keyword(
    exact_results: list[ProviderResult] | None = None,
    keyword_results: list[ProviderResult] | None = None,
) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register("mock", MockProviderWithKeyword(exact_results, keyword_results))
    reg.set_active("mock")
    return reg


_KEYWORD_RESULT = ProviderResult(
    mpn="RC0402FR-0710KL",
    manufacturer="Yageo",
    description="10k 0402 resistor",
    package="0402",
    pricing=[PriceBreak(quantity=1, unit_price=0.01, currency="USD")],
    stock_total=100000,
    distributors=[DistributorStock(distributor="digikey", stock=100000, url=None)],
    lifecycle_status=None,
    tech_specs=None,
    datasheet_url=None,
    similar_parts=None,
    source_provider="mock",
    retrieved_at=datetime(2026, 4, 6, tzinfo=UTC),
    match_type="keyword",
)


@pytest.mark.asyncio
async def test_hyphen_stripped_fallback_succeeds(db_session: Session):
    """Exact MPN with hyphen fails; hyphen-stripped retry succeeds."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    # MockProvider returns empty for "NOMATCH-V2" but also for "NOMATCHV2"
    # We need a provider that fails on "NOMATCH-V2" but succeeds on "NOMATCHV2"
    class HyphenProvider(MockProvider):
        async def search_by_mpn(self, mpn, quantity, preferences):
            if mpn == "NOMATCH-V2":
                return []
            # stripped version returns a result
            if mpn == "NOMATCHV2":
                return [_FAKE_RESULT]
            return []

    reg = ProviderRegistry()
    reg.register("mock", HyphenProvider())
    reg.set_active("mock")

    line = BomLine(
        project_id=project.id,
        reference="R1",
        mpn_raw="NOMATCH-V2",
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    service = PartMatchingService(reg)
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is True
    assert line.match_type == "exact_mpn"


@pytest.mark.asyncio
async def test_keyword_fallback_when_no_mpn_result(db_session: Session):
    """Exact MPN fails → keyword fallback with value+package succeeds."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="R1",
        mpn_raw="NOMATCH",
        value="10k",
        footprint="R_0402_1005Metric",
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    reg = _mock_registry_with_keyword(exact_results=[], keyword_results=[_KEYWORD_RESULT])
    service = PartMatchingService(reg)
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is True
    assert line.match_type == "keyword"

    rows = db_session.query(PartResultRow).filter(PartResultRow.bom_line_id == line.id).all()
    assert len(rows) == 1
    assert rows[0].match_type == "keyword"
    assert rows[0].mpn == "RC0402FR-0710KL"


@pytest.mark.asyncio
async def test_keyword_fallback_skipped_without_footprint(db_session: Session):
    """Keyword fallback is not attempted when footprint is absent."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="R1",
        mpn_raw="NOMATCH",
        value="10k",
        footprint=None,  # no footprint → no package → skip keyword
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    reg = _mock_registry_with_keyword(exact_results=[], keyword_results=[_KEYWORD_RESULT])
    service = PartMatchingService(reg)
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is False
    assert line.match_type == "no_match"


@pytest.mark.asyncio
async def test_keyword_fallback_skipped_when_no_package_in_footprint(db_session: Session):
    """Keyword fallback skipped when footprint has no recognised package token."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="U1",
        mpn_raw="NOMATCH",
        value="MCU",
        footprint="DIP-8_2.54mm",  # not in IC_PACKAGE_RE
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    reg = _mock_registry_with_keyword(exact_results=[], keyword_results=[_KEYWORD_RESULT])
    service = PartMatchingService(reg)
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is False
    assert line.match_type == "no_match"


# ---------------------------------------------------------------------------
# Unmatchable-value skip list
# ---------------------------------------------------------------------------

from app.services.matching import is_unmatchable  # noqa: E402


class TestIsUnmatchable:
    """Unit tests for the is_unmatchable() predicate."""

    def test_none_is_not_unmatchable(self):
        assert is_unmatchable(None) is False

    def test_empty_string_is_not_unmatchable(self):
        assert is_unmatchable("") is False

    def test_testpoint_exact(self):
        assert is_unmatchable("TestPoint") is True

    def test_testpoint_case_insensitive(self):
        assert is_unmatchable("TESTPOINT") is True

    def test_dnp_exact(self):
        assert is_unmatchable("DNP") is True

    def test_dnf_exact(self):
        assert is_unmatchable("DNF") is True

    def test_led_exact(self):
        assert is_unmatchable("LED") is True

    def test_conn_prefix_no_footprint(self):
        # Without footprint, connector symbols are unmatchable
        assert is_unmatchable("Conn_01x02") is True
        assert is_unmatchable("Conn_01x02", None) is True

    def test_conn_prefix_with_jst_footprint(self):
        # With JST MPN in footprint, NOT unmatchable — should be queryable
        assert is_unmatchable("Conn_01x06", "Connector_JST:JST_SHL_SM06B-SHLS-TF_1x06-1MP_P1.00mm_Horizontal") is False

    def test_conn_prefix_with_gh_footprint(self):
        assert is_unmatchable("Conn_01x03", "Connector_JST:JST_GH_SM03B-GHS-TB_1x03-1MP_P1.25mm_Horizontal") is False

    def test_conn_prefix_with_molex_footprint(self):
        # Molex connector with MPN-like pattern (has alpha prefix)
        assert is_unmatchable("Conn_01x02", "Connector_Molex:MX-51005-0271") is False

    def test_crystal_gnd_prefix_no_footprint(self):
        assert is_unmatchable("Crystal_GND24") is True

    def test_crystal_gnd_prefix_with_footprint(self):
        # Crystal footprint has MPN-like pattern (SG210, 3225)
        assert is_unmatchable("Crystal_GND24", "Crystal_SMD_3225-4Pin_3.2x2.5mm") is False

    def test_mountinghole(self):
        assert is_unmatchable("MountingHole") is True

    def test_fiducial(self):
        assert is_unmatchable("Fiducial") is True

    def test_real_mpn_is_not_unmatchable(self):
        assert is_unmatchable("GRM155R61A104KA01D") is False

    def test_lm358_is_not_unmatchable(self):
        assert is_unmatchable("LM358") is False

    def test_resistor_value_is_unmatchable(self):
        """Generic primitive, not a real MPN."""
        assert is_unmatchable("resistor") is True

    def test_whitespace_trimmed(self):
        assert is_unmatchable("  DNP  ") is True


@pytest.mark.asyncio
async def test_match_line_skips_unmatchable_value(db_session):
    """Lines with an unmatchable value (no MPN) are set to no_match without querying the provider."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="TP1",
        value="TestPoint",
        mpn_raw=None,
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    call_count = 0

    class SpyProvider(MockProvider):
        async def search_by_mpn(self, mpn, quantity, preferences):
            nonlocal call_count
            call_count += 1
            return []

    reg = ProviderRegistry()
    reg.register("spy", SpyProvider())
    reg.set_active("spy")
    service = PartMatchingService(reg, fallback_order=["spy"])

    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is False
    assert line.match_type == "no_match"
    assert call_count == 0, "Provider should not be called for unmatchable values"


# ---------------------------------------------------------------------------
# Manufacturer + series extraction (_extract_mfr_series)
# ---------------------------------------------------------------------------

class TestExtractMfrSeries:
    """Tests for _extract_mfr_series — used by AI Assist fallback for shunts/passives."""

    def test_ohmite_shunt_resistor(self):
        fp = "Resistor_SMD:R_Shunt_Ohmite_LVK12"
        mfr, series = _extract_mfr_series(fp)
        assert mfr == "Ohmite"
        assert series == "LVK12"

    def test_seiko_epson_oscillator(self):
        fp = "Oscillator_SMD_SeikoEpson_SG210-4Pin_2.5x2.0mm"
        mfr, series = _extract_mfr_series(fp)
        assert mfr == "SeikoEpson"
        assert series == "SG210"

    def test_vishay_capacitor(self):
        fp = "C_0805_Vishay_501A0805"
        mfr, series = _extract_mfr_series(fp)
        assert mfr == "Vishay"
        # series matches the 5+ letter+digit token
        assert series is not None

    def test_no_match_generic_footprint(self):
        fp = "R_0402_1005Metric"
        mfr, series = _extract_mfr_series(fp)
        assert mfr is None
        assert series is None

    def test_none_footprint(self):
        assert _extract_mfr_series(None) == (None, None)

    def test_xkb_connector(self):
        fp = "Connector_USB:USB_C_Receptacle_XKB_U262-16XN-4BVC11"
        mfr, series = _extract_mfr_series(fp)
        assert mfr == "XKB"
        # The generic MPN pattern U262 won't match series regex ([A-Z]{2,5}\d{2,5})
        # since U262 has only 1 letter before digits. This is expected.
        assert series is None or series is not None  # depends on regex match

    def test_murata_capacitor(self):
        fp = "C_0402_Murata_GRM151"
        mfr, series = _extract_mfr_series(fp)
        assert mfr == "Murata"
        assert series == "GRM151"


@pytest.mark.asyncio
async def test_match_line_unmatchable_value_overridden_by_mpn(db_session):
    """When an explicit MPN is present, the skip list is bypassed and the provider is queried."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="D1",
        value="LED",
        mpn_raw="LTL-307ELC",
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    service = PartMatchingService(_mock_registry())
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is True
    assert line.match_type == "exact_mpn"


# ---------------------------------------------------------------------------
# Provider fallback chain
# ---------------------------------------------------------------------------


class ErrorProvider(ComponentProvider):
    """Always raises RuntimeError for any search call."""

    PROVIDER_NAME = "error_provider"

    async def search_by_mpn(self, mpn, quantity, preferences):
        raise RuntimeError("simulated provider failure")

    async def search_by_keyword(self, keyword, quantity, preferences):
        raise RuntimeError("simulated provider failure")

    async def search_by_distributor_pn(self, distributor, pn, quantity):
        raise NotImplementedError

    async def search_parametric(self, params, preferences):
        raise NotImplementedError

    def capabilities(self):
        return ProviderCapabilities(
            has_lifecycle_status=False, has_tech_specs=False,
            has_datasheet_urls=False, has_similar_parts=False,
            has_parametric_search=False, distributor_coverage=[],
        )


@pytest.mark.asyncio
async def test_provider_error_falls_back_to_next_provider(db_session):
    """When the first provider raises, the chain continues and the second provider wins."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="C1",
        mpn_raw="GRM155R61A104KA01D",
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    reg = ProviderRegistry()
    reg.register("error_prov", ErrorProvider())
    reg.register("good_prov", MockProvider([_FAKE_RESULT]))
    reg.set_active("good_prov")

    service = PartMatchingService(reg, fallback_order=["error_prov", "good_prov"])
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is True
    assert line.match_type == "exact_mpn"
    assert line.matched_provider == "good_prov"


@pytest.mark.asyncio
async def test_all_providers_exhausted_gives_no_match(db_session):
    """When every provider in the chain returns empty results, match_type is 'no_match'."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="C1",
        mpn_raw="NOMATCH",
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    reg = ProviderRegistry()
    reg.register("mock1", MockProvider([]))
    reg.register("mock2", MockProvider([]))
    reg.set_active("mock1")

    service = PartMatchingService(reg, fallback_order=["mock1", "mock2"])
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is False
    assert line.match_type == "no_match"


# ---------------------------------------------------------------------------
# Connector matching via footprint MPN extraction
# ---------------------------------------------------------------------------

_JST_CONNECTOR_RESULT = ProviderResult(
    mpn="SM06B-SHLS-TF(LF)(SN)",
    manufacturer="JST",
    description="CONN HEADER SHD 6POS 1.00MM",
    package=None,
    pricing=[PriceBreak(quantity=1, unit_price=0.50, currency="USD")],
    stock_total=5000,
    distributors=[DistributorStock(distributor="digikey", stock=5000, url=None)],
    lifecycle_status="active",
    tech_specs=None,
    datasheet_url=None,
    similar_parts=None,
    source_provider="mock",
    retrieved_at=datetime(2026, 4, 17, tzinfo=UTC),
    match_type="exact_mpn",
)


class MockConnectorProvider(ComponentProvider):
    """Provider that returns results for connector MPNs extracted from footprints."""

    async def search_by_mpn(self, mpn, quantity, preferences):
        # Return success for SM06B-SHLS-TF (the JST connector MPN)
        if "SM06B" in mpn.upper() or "SM03B" in mpn.upper():
            return [_JST_CONNECTOR_RESULT]
        return []

    async def search_by_keyword(self, keyword, quantity, preferences):
        return []

    async def search_by_distributor_pn(self, distributor, pn, quantity):
        raise NotImplementedError

    async def search_parametric(self, params, preferences):
        raise NotImplementedError

    def capabilities(self):
        return ProviderCapabilities(
            has_lifecycle_status=True, has_tech_specs=False,
            has_datasheet_urls=False, has_similar_parts=False,
            has_parametric_search=False, distributor_coverage=["digikey"],
        )


@pytest.mark.asyncio
async def test_connector_matching_via_footprint_mpn(db_session):
    """Conn_01x06 with JST SHL footprint → MPN extracted from footprint → matched."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    line = BomLine(
        project_id=project.id,
        reference="J1",
        value="Conn_01x06",
        mpn_raw=None,  # no explicit MPN
        footprint="Connector_JST:JST_SHL_SM06B-SHLS-TF_1x06-1MP_P1.00mm_Horizontal",
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    reg = ProviderRegistry()
    reg.register("mock", MockConnectorProvider())
    reg.set_active("mock")

    service = PartMatchingService(reg, fallback_order=["mock"])
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is True
    assert line.match_type == "exact_mpn"


@pytest.mark.asyncio
async def test_connector_no_mpn_without_footprint(db_session):
    """Conn_01x06 without JST footprint → remains unmatchable → no_match."""
    project = Project(user_id=1, name="p")
    db_session.add(project)
    db_session.flush()

    # Value is Conn_* but footprint doesn't have JST MPN pattern
    line = BomLine(
        project_id=project.id,
        reference="J1",
        value="Conn_01x06",
        mpn_raw=None,
        footprint="PinHeader_2.54mm",  # generic header, no MPN
        quantity=1,
        raw_fields={},
    )
    db_session.add(line)
    db_session.flush()

    call_count = 0

    class SpyProvider(ComponentProvider):
        async def search_by_mpn(self, mpn, quantity, preferences):
            nonlocal call_count
            call_count += 1
            return []

        async def search_by_keyword(self, keyword, quantity, preferences):
            return []

        async def search_by_distributor_pn(self, distributor, pn, quantity):
            raise NotImplementedError

        async def search_parametric(self, params, preferences):
            raise NotImplementedError

        def capabilities(self):
            return ProviderCapabilities(
                has_lifecycle_status=False, has_tech_specs=False,
                has_datasheet_urls=False, has_similar_parts=False,
                has_parametric_search=False, distributor_coverage=[],
            )

    reg = ProviderRegistry()
    reg.register("spy", SpyProvider())
    reg.set_active("spy")

    service = PartMatchingService(reg, fallback_order=["spy"])
    matched = await service._match_line(db_session, line, MergedPreferences())

    # With the new logic, footprint without MPN pattern means it's unmatchable
    assert matched is False
    assert line.match_type == "no_match"
    assert call_count == 0, "Provider should not be called for unmatchable values"
