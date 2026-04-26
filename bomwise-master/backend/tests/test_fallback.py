"""
Tests for provider fallback chain logic in PartMatchingService.

All provider calls are mocked — no live API calls.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.models.part_result import PartResult as PartResultRow
from app.models.project import BomLine, Project
from app.providers.base import ComponentProvider
from app.providers.registry import ProviderRegistry
from app.providers.schema import (
    DistributorStock,
    ParametricQuery,
    PartResult as ProviderResult,
    PriceBreak,
    ProviderCapabilities,
)
from app.schemas.preferences import MergedPreferences
from app.services.matching import PartMatchingService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(mpn: str, source: str) -> ProviderResult:
    return ProviderResult(
        mpn=mpn,
        manufacturer="Acme",
        description=None,
        package=None,
        pricing=[PriceBreak(quantity=1, unit_price=0.10, currency="USD")],
        stock_total=1000,
        distributors=[DistributorStock(distributor=source, stock=1000, url=None)],
        lifecycle_status=None,
        tech_specs=None,
        datasheet_url=None,
        similar_parts=None,
        source_provider=source,
        retrieved_at=datetime(2026, 4, 7, tzinfo=UTC),
        match_type="exact_mpn",
    )


class RecordingProvider(ComponentProvider):
    """Provider that optionally returns results; records every call."""

    def __init__(self, name: str, results: list[ProviderResult] | None = None) -> None:
        self.name = name
        self._results = results if results is not None else []
        self.calls: list[str] = []

    async def search_by_mpn(
        self, mpn: str, quantity: int, preferences: MergedPreferences
    ) -> list[ProviderResult]:
        self.calls.append(f"search_by_mpn:{mpn}")
        return self._results

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
            distributor_coverage=[self.name],
        )


def _registry(*providers: RecordingProvider) -> ProviderRegistry:
    reg = ProviderRegistry()
    for p in providers:
        reg.register(p.name, p)
    # Set a dummy active provider (required by registry internals but unused
    # in fallback-chain tests — we pass an explicit fallback_order).
    if providers:
        reg.set_active(providers[0].name)
    return reg


def _line(db: Session, *, mpn: str | None = "ABC123") -> BomLine:
    project = Project(user_id=1, name="p")
    db.add(project)
    db.flush()
    line = BomLine(
        project_id=project.id,
        reference="R1",
        mpn_raw=mpn,
        quantity=1,
        raw_fields={},
    )
    db.add(line)
    db.flush()
    return line


# ---------------------------------------------------------------------------
# First provider returns a match → used, second not called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_provider_wins(db_session: Session):
    p1 = RecordingProvider("p1", [_result("ABC123", "p1")])
    p2 = RecordingProvider("p2", [_result("ABC123", "p2")])
    reg = _registry(p1, p2)

    service = PartMatchingService(reg, fallback_order=["p1", "p2"])
    line = _line(db_session)
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is True
    assert line.matched_provider == "p1"
    # p2 must not have been queried at all
    assert p2.calls == []
    rows = db_session.query(PartResultRow).filter(PartResultRow.bom_line_id == line.id).all()
    assert rows[0].source_provider == "p1"


# ---------------------------------------------------------------------------
# First provider returns empty → second provider called, its match used
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_provider_fallback(db_session: Session):
    p1 = RecordingProvider("p1", [])          # empty
    p2 = RecordingProvider("p2", [_result("ABC123", "p2")])
    reg = _registry(p1, p2)

    service = PartMatchingService(reg, fallback_order=["p1", "p2"])
    line = _line(db_session)
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is True
    assert line.matched_provider == "p2"
    assert len(p1.calls) > 0   # p1 was tried
    assert len(p2.calls) > 0   # p2 was tried
    rows = db_session.query(PartResultRow).filter(PartResultRow.bom_line_id == line.id).all()
    assert rows[0].source_provider == "p2"


# ---------------------------------------------------------------------------
# All providers return empty → line unmatched, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_providers_empty(db_session: Session):
    p1 = RecordingProvider("p1", [])
    p2 = RecordingProvider("p2", [])
    reg = _registry(p1, p2)

    service = PartMatchingService(reg, fallback_order=["p1", "p2"])
    line = _line(db_session)
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is False
    assert line.matched_provider is None
    assert line.match_type == "no_match"
    assert db_session.query(PartResultRow).filter(PartResultRow.bom_line_id == line.id).count() == 0


# ---------------------------------------------------------------------------
# Unconfigured provider (not in registry) → skipped, next provider tried
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unconfigured_provider_skipped(db_session: Session):
    p2 = RecordingProvider("p2", [_result("ABC123", "p2")])
    # "p1" is listed in fallback_order but NOT registered → should be skipped
    reg = _registry(p2)

    service = PartMatchingService(reg, fallback_order=["p1", "p2"])
    line = _line(db_session)
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is True
    assert line.matched_provider == "p2"


# ---------------------------------------------------------------------------
# matched_provider is correctly set to the winning provider name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matched_provider_reflects_winner(db_session: Session):
    p_a = RecordingProvider("supplier_a", [])
    p_b = RecordingProvider("supplier_b", [_result("ABC123", "supplier_b")])
    p_c = RecordingProvider("supplier_c", [_result("ABC123", "supplier_c")])
    reg = _registry(p_a, p_b, p_c)

    service = PartMatchingService(reg, fallback_order=["supplier_a", "supplier_b", "supplier_c"])
    line = _line(db_session)
    await service._match_line(db_session, line, MergedPreferences())

    assert line.matched_provider == "supplier_b"
    # supplier_c must not have been called once supplier_b succeeded
    assert p_c.calls == []


# ---------------------------------------------------------------------------
# matched_provider is None for unmatched lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matched_provider_null_when_unmatched(db_session: Session):
    p = RecordingProvider("p", [])
    reg = _registry(p)

    service = PartMatchingService(reg, fallback_order=["p"])
    line = _line(db_session, mpn="NOMATCH")
    await service._match_line(db_session, line, MergedPreferences())

    assert line.matched_provider is None


# ---------------------------------------------------------------------------
# Single-item fallback order behaves like the old single-provider path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_provider_chain(db_session: Session):
    p = RecordingProvider("only", [_result("ABC123", "only")])
    reg = _registry(p)

    service = PartMatchingService(reg, fallback_order=["only"])
    line = _line(db_session)
    matched = await service._match_line(db_session, line, MergedPreferences())

    assert matched is True
    assert line.matched_provider == "only"
