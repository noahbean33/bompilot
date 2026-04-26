"""
Provider layer tests.

No live API calls are made — NexarProvider._get_token / httpx are never
invoked. Tests cover:
  - Schema validation (PartResult, PriceBreak, DistributorStock, ProviderCapabilities)
  - ProviderRegistry behaviour
  - NexarProvider.capabilities() and _map_part() (pure data transformation)
  - GET /providers/capabilities HTTP endpoint
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.providers.digikey_mouser import DigiKeyMouserProvider
from app.providers.findchips import FindChipsProvider
from app.providers.nexar import NexarProvider
from app.providers.registry import ProviderRegistry, get_registry
from app.providers.schema import (
    DistributorStock,
    PartResult,
    PriceBreak,
    ProviderCapabilities,
)

# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def test_price_break_valid():
    pb = PriceBreak(quantity=10, unit_price=0.15, currency="USD")
    assert pb.quantity == 10
    assert pb.currency == "USD"


def test_distributor_stock_valid():
    ds = DistributorStock(distributor="digikey", stock=500, url="https://digikey.com/part/x")
    assert ds.distributor == "digikey"
    assert ds.url is not None


def test_distributor_stock_url_optional():
    ds = DistributorStock(distributor="mouser", stock=0, url=None)
    assert ds.url is None


def test_part_result_valid():
    pr = PartResult(
        mpn="RC0402FR-0710KL",
        manufacturer="Yageo",
        description="10 kΩ resistor",
        package="0402",
        pricing=[PriceBreak(quantity=1, unit_price=0.10, currency="USD")],
        stock_total=5000,
        distributors=[DistributorStock(distributor="digikey", stock=5000, url=None)],
        lifecycle_status="active",
        tech_specs={"resistance": "10 kΩ"},
        datasheet_url="https://example.com/ds.pdf",
        similar_parts=["RC0402FR-0715KL"],
        source_provider="nexar",
        retrieved_at=_now(),
        match_type="exact_mpn",
    )
    assert pr.mpn == "RC0402FR-0710KL"
    assert pr.stock_total == 5000
    assert len(pr.pricing) == 1


def test_part_result_optional_fields_none():
    pr = PartResult(
        mpn="ABC123",
        manufacturer="Acme",
        description=None,
        package=None,
        pricing=[],
        stock_total=0,
        distributors=[],
        lifecycle_status=None,
        tech_specs=None,
        datasheet_url=None,
        similar_parts=None,
        source_provider="nexar",
        retrieved_at=_now(),
        match_type="exact_mpn",
    )
    assert pr.description is None
    assert pr.similar_parts is None


def test_part_result_missing_required_field():
    with pytest.raises(Exception):
        PartResult(
            # mpn missing
            manufacturer="Yageo",
            pricing=[],
            stock_total=0,
            distributors=[],
            source_provider="nexar",
            retrieved_at=_now(),
            match_type="exact_mpn",
        )


def test_provider_capabilities_valid():
    caps = ProviderCapabilities(
        has_lifecycle_status=True,
        has_tech_specs=True,
        has_datasheet_urls=True,
        has_similar_parts=True,
        has_parametric_search=True,
        distributor_coverage=["digikey", "mouser"],
    )
    assert caps.has_lifecycle_status is True
    assert "digikey" in caps.distributor_coverage


# ---------------------------------------------------------------------------
# ProviderRegistry
# ---------------------------------------------------------------------------


def test_registry_register_and_get():
    reg = ProviderRegistry()
    provider = NexarProvider()
    reg.register("nexar", provider)
    reg.set_active("nexar")
    assert reg.get() is provider


def test_registry_set_active_unknown_raises():
    reg = ProviderRegistry()
    with pytest.raises(ValueError, match="Unknown provider"):
        reg.set_active("does_not_exist")


def test_registry_get_without_active_raises():
    reg = ProviderRegistry()
    reg.register("nexar", NexarProvider())
    with pytest.raises(RuntimeError, match="No active provider"):
        reg.get()


def test_registry_capabilities_nexar():
    reg = ProviderRegistry()
    reg.register("nexar", NexarProvider())
    reg.set_active("nexar")
    caps = reg.capabilities()
    assert caps.has_lifecycle_status is False
    assert caps.has_similar_parts is True
    assert "digikey" in caps.distributor_coverage


def test_registry_capabilities_findchips():
    reg = ProviderRegistry()
    reg.register("findchips", FindChipsProvider())
    reg.set_active("findchips")
    caps = reg.capabilities()
    assert caps.has_similar_parts is False
    assert caps.has_lifecycle_status is True


def test_registry_capabilities_digikey_mouser():
    reg = ProviderRegistry()
    reg.register("digikey_mouser", DigiKeyMouserProvider())
    reg.set_active("digikey_mouser")
    caps = reg.capabilities()
    assert caps.has_lifecycle_status is False
    assert caps.distributor_coverage == ["digikey", "mouser"]


def test_registry_switch_active_provider():
    reg = ProviderRegistry()
    reg.register("nexar", NexarProvider())
    reg.register("findchips", FindChipsProvider())

    reg.set_active("nexar")
    assert reg.capabilities().has_similar_parts is True

    reg.set_active("findchips")
    assert reg.capabilities().has_similar_parts is False


# ---------------------------------------------------------------------------
# NexarProvider — capabilities and response mapping (no HTTP)
# ---------------------------------------------------------------------------


def test_nexar_capabilities():
    caps = NexarProvider().capabilities()
    assert caps.has_lifecycle_status is False
    assert caps.has_tech_specs is True
    assert caps.has_datasheet_urls is True
    assert caps.has_similar_parts is True
    assert caps.has_parametric_search is True
    assert set(caps.distributor_coverage) >= {"digikey", "mouser", "arrow"}


def _mock_nexar_part() -> dict:
    """
    Minimal Nexar GraphQL SupPart payload mirroring the exact fields requested
    in _MPN_QUERY: mpn, manufacturer{name}, shortDescription, totalAvail,
    bestDatasheet{url}, similarParts{mpn}, specs{attribute{name} value},
    sellers{company{name} offers{inventoryLevel prices{quantity price currency} clickUrl}}.

    totalAvail (75000) is intentionally different from the sum of inventoryLevel
    values (45000 + 12000 = 57000) so tests catch regressions that accidentally
    re-sum per-offer inventory instead of using the top-level field.
    """
    return {
        "mpn": "RC0402FR-0710KL",
        "manufacturer": {"name": "Yageo"},
        "shortDescription": "10 kΩ ±1% 0402 resistor",
        "totalAvail": 75000,
        "bestDatasheet": {"url": "https://example.com/datasheet.pdf"},
        "similarParts": [{"mpn": "RC0402FR-0715KL"}, {"mpn": "RC0402FR-078K2L"}],
        "specs": [
            {"attribute": {"name": "resistance"}, "value": "10 kΩ"},
            {"attribute": {"name": "tolerance"}, "value": "±1%"},
        ],
        "sellers": [
            {
                "company": {"name": "Digi-Key"},
                "offers": [
                    {
                        "inventoryLevel": 45000,
                        "prices": [
                            {"quantity": 1, "price": 0.10, "currency": "USD"},
                            {"quantity": 100, "price": 0.05, "currency": "USD"},
                        ],
                        "clickUrl": "https://digikey.com/part/x",
                    }
                ],
            },
            {
                "company": {"name": "Mouser Electronics"},
                "offers": [
                    {
                        "inventoryLevel": 12000,
                        "prices": [
                            {"quantity": 1, "price": 0.11, "currency": "USD"},
                        ],
                        "clickUrl": "https://mouser.com/part/x",
                    }
                ],
            },
        ],
    }


def test_nexar_map_part_basic_fields():
    part = NexarProvider()._map_part(_mock_nexar_part())
    assert part.mpn == "RC0402FR-0710KL"
    assert part.manufacturer == "Yageo"
    assert part.description == "10 kΩ ±1% 0402 resistor"
    assert part.package is None  # SupPart type does not expose package
    assert part.source_provider == "nexar"
    assert part.match_type == "exact_mpn"


def test_nexar_map_part_lifecycle():
    part = NexarProvider()._map_part(_mock_nexar_part())
    assert part.lifecycle_status is None  # SupPart type does not expose lifecycleStatus


def test_nexar_map_part_pricing():
    part = NexarProvider()._map_part(_mock_nexar_part())
    # 2 price breaks from DigiKey + 1 from Mouser = 3 total
    # price maps from SupPrice.price (not convertedPrice)
    assert len(part.pricing) == 3
    prices = {(p.quantity, p.unit_price) for p in part.pricing}
    assert (1, 0.10) in prices
    assert (100, 0.05) in prices
    assert (1, 0.11) in prices


def test_nexar_map_part_distributors():
    part = NexarProvider()._map_part(_mock_nexar_part())
    by_name = {d.distributor: d for d in part.distributors}
    assert "digikey" in by_name
    assert "mouser" in by_name
    # url maps from SupOffer.clickUrl (not company.homepageUrl or offer.url)
    assert by_name["digikey"].url == "https://digikey.com/part/x"
    assert by_name["mouser"].url == "https://mouser.com/part/x"
    # stock maps from SupOffer.inventoryLevel, independently of totalAvail
    assert by_name["digikey"].stock == 45000
    assert by_name["mouser"].stock == 12000


def test_nexar_map_part_stock_total():
    # stock_total must come from SupPart.totalAvail (75000), NOT from summing
    # DistributorStock.inventoryLevel values (45000 + 12000 = 57000).
    part = NexarProvider()._map_part(_mock_nexar_part())
    assert part.stock_total == 75000


def test_nexar_map_part_tech_specs():
    part = NexarProvider()._map_part(_mock_nexar_part())
    assert part.tech_specs is not None
    # key from specs[].attribute.name (not shortname), value from specs[].value (not displayValue)
    assert part.tech_specs["resistance"] == "10 kΩ"
    assert part.tech_specs["tolerance"] == "±1%"


def test_nexar_map_part_datasheet():
    part = NexarProvider()._map_part(_mock_nexar_part())
    assert part.datasheet_url == "https://example.com/datasheet.pdf"


def test_nexar_map_part_similar_parts():
    part = NexarProvider()._map_part(_mock_nexar_part())
    assert part.similar_parts == ["RC0402FR-0715KL", "RC0402FR-078K2L"]


def test_nexar_map_part_empty_sellers():
    raw = _mock_nexar_part()
    raw["sellers"] = []
    raw["totalAvail"] = 0
    part = NexarProvider()._map_part(raw)
    assert part.stock_total == 0
    assert part.pricing == []
    assert part.distributors == []


def test_nexar_map_mpn_response_full():
    data = {
        "data": {
            "supSearchMpn": {
                "results": [
                    {"part": _mock_nexar_part()},
                    {"part": _mock_nexar_part()},
                ]
            }
        }
    }
    results = NexarProvider()._map_mpn_response(data)
    assert len(results) == 2


def test_nexar_map_mpn_response_empty():
    results = NexarProvider()._map_mpn_response({"data": {"supSearchMpn": {"results": []}}})
    assert results == []


# ---------------------------------------------------------------------------
# GET /providers/capabilities — HTTP endpoint
# ---------------------------------------------------------------------------


def test_capabilities_endpoint(client: TestClient):
    resp = client.get("/providers/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    # Default provider is now OEMSecrets; assert its known capabilities.
    assert data["has_lifecycle_status"] is False
    assert data["has_datasheet_urls"] is True
    assert data["has_tech_specs"] is False
    assert data["has_similar_parts"] is False


def test_capabilities_endpoint_schema(client: TestClient):
    resp = client.get("/providers/capabilities")
    caps = ProviderCapabilities(**resp.json())  # must parse without error
    assert isinstance(caps.distributor_coverage, list)


def test_capabilities_endpoint_override(client: TestClient):
    """Swap the active provider mid-test using dependency override."""
    from app.main import app

    def use_findchips():
        reg = ProviderRegistry()
        reg.register("findchips", FindChipsProvider())
        reg.set_active("findchips")
        return reg

    app.dependency_overrides[get_registry] = use_findchips
    try:
        resp = client.get("/providers/capabilities")
        assert resp.status_code == 200
        assert resp.json()["has_similar_parts"] is False
        assert resp.json()["has_lifecycle_status"] is True
    finally:
        app.dependency_overrides.pop(get_registry, None)
