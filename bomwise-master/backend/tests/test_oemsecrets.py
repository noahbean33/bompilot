"""
OEMSecretsProvider unit tests.

No live HTTP calls are made — httpx.AsyncClient.get is patched throughout.
Covers:
  - Successful match: correct PartResult fields, DistributorStock, PriceBreak mapping
  - Empty stock array: returns empty list
  - Missing price currency key: falls back to first available key
  - life_cycle empty string maps to None
  - life_cycle non-empty string is preserved
  - capabilities() assertions
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.oemsecrets import OEMSecretsProvider
from app.schemas.preferences import MergedPreferences


# ---------------------------------------------------------------------------
# Fixtures and sample data
# ---------------------------------------------------------------------------

_DEFAULT_PREFS = MergedPreferences(preferred_currency="USD", preferred_distributors=[])

_STOCK_ITEM = {
    "part_number": "RC0402FR-0710KL",
    "manufacturer": "Yageo",
    "description": "RES 10K OHM 1% 1/16W 0402",
    "quantity_in_stock": 5000,
    "moq": 10,
    "prices": {
        "USD": [
            {"unit_break": 1, "unit_price": "0.10"},
            {"unit_break": 100, "unit_price": "0.08"},
        ]
    },
    "buy_now_url": "https://oemsecrets.com/buy/RC0402FR-0710KL",
    "datasheet_url": "https://oemsecrets.com/ds/yageo-rc0402.pdf",
    "image_url": "https://oemsecrets.com/img/rc0402.jpg",
    "life_cycle": "Active",
    "lead_time_weeks": "2",
    "distributor": {
        "distributor_name": "Digi-Key",
        "distributor_common_name": "DigiKey",
        "distributor_region": "US",
        "distributor_country": "US",
    },
    "distributor_authorisation_status": "authorised",
}

_RESPONSE_ONE = {
    "version": "1.0",
    "status": "ok",
    "search_term": "RC0402FR-0710KL",
    "country_code": "US",
    "parts_returned": 1,
    "stock": [_STOCK_ITEM],
}


def _make_provider() -> OEMSecretsProvider:
    provider = OEMSecretsProvider.__new__(OEMSecretsProvider)
    provider._api_key = "test-key"
    return provider


def _mock_get(payload: dict):
    """Return an async context-manager mock that yields an httpx-like response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOEMSecretsCapabilities:
    def test_capabilities(self):
        provider = _make_provider()
        caps = provider.capabilities()
        assert caps.has_datasheet_urls is True
        assert caps.has_lifecycle_status is False
        assert caps.has_tech_specs is False
        assert caps.has_similar_parts is False
        assert caps.has_parametric_search is False


class TestSearchByMPN:
    @pytest.mark.asyncio
    async def test_successful_match(self):
        provider = _make_provider()
        with patch("httpx.AsyncClient", return_value=_mock_get(_RESPONSE_ONE)):
            results = await provider.search_by_mpn("RC0402FR-0710KL", 10, _DEFAULT_PREFS)

        assert len(results) == 1
        r = results[0]
        assert r.mpn == "RC0402FR-0710KL"
        assert r.manufacturer == "Yageo"
        assert r.description == "RES 10K OHM 1% 1/16W 0402"
        assert r.stock_total == 5000
        assert r.source_provider == "oemsecrets"
        assert r.match_type == "exact_mpn"
        assert r.datasheet_url == "https://oemsecrets.com/ds/yageo-rc0402.pdf"
        assert r.lifecycle_status == "Active"

    @pytest.mark.asyncio
    async def test_distributor_mapped_correctly(self):
        provider = _make_provider()
        with patch("httpx.AsyncClient", return_value=_mock_get(_RESPONSE_ONE)):
            results = await provider.search_by_mpn("RC0402FR-0710KL", 10, _DEFAULT_PREFS)

        dist = results[0].distributors[0]
        assert dist.distributor == "Digi-Key"
        assert dist.stock == 5000
        assert dist.moq == 10
        assert dist.url == "https://oemsecrets.com/buy/RC0402FR-0710KL"

    @pytest.mark.asyncio
    async def test_pricing_mapped_correctly(self):
        provider = _make_provider()
        with patch("httpx.AsyncClient", return_value=_mock_get(_RESPONSE_ONE)):
            results = await provider.search_by_mpn("RC0402FR-0710KL", 10, _DEFAULT_PREFS)

        pricing = results[0].pricing
        assert len(pricing) == 2
        assert pricing[0].quantity == 1
        assert pricing[0].unit_price == pytest.approx(0.10)
        assert pricing[0].currency == "USD"
        assert pricing[1].quantity == 100
        assert pricing[1].unit_price == pytest.approx(0.08)

    @pytest.mark.asyncio
    async def test_empty_stock_returns_empty_list(self):
        provider = _make_provider()
        empty_resp = {**_RESPONSE_ONE, "parts_returned": 0, "stock": []}
        with patch("httpx.AsyncClient", return_value=_mock_get(empty_resp)):
            results = await provider.search_by_mpn("NOTAPART", 1, _DEFAULT_PREFS)

        assert results == []

    @pytest.mark.asyncio
    async def test_missing_currency_key_falls_back_to_first_available(self):
        """If prices dict doesn't have the requested currency, use the first key."""
        item = {
            **_STOCK_ITEM,
            "prices": {
                "EUR": [{"unit_break": 1, "unit_price": "0.09"}]
            },
        }
        resp = {**_RESPONSE_ONE, "stock": [item]}
        provider = _make_provider()
        with patch("httpx.AsyncClient", return_value=_mock_get(resp)):
            results = await provider.search_by_mpn("RC0402FR-0710KL", 1, _DEFAULT_PREFS)

        assert len(results) == 1
        pricing = results[0].pricing
        assert len(pricing) == 1
        assert pricing[0].unit_price == pytest.approx(0.09)

    @pytest.mark.asyncio
    async def test_lifecycle_empty_string_maps_to_none(self):
        """Empty string in life_cycle must become None."""
        item = {**_STOCK_ITEM, "life_cycle": ""}
        resp = {**_RESPONSE_ONE, "stock": [item]}
        provider = _make_provider()
        with patch("httpx.AsyncClient", return_value=_mock_get(resp)):
            results = await provider.search_by_mpn("RC0402FR-0710KL", 1, _DEFAULT_PREFS)

        assert results[0].lifecycle_status is None

    @pytest.mark.asyncio
    async def test_lifecycle_whitespace_only_maps_to_none(self):
        """Whitespace-only life_cycle also maps to None."""
        item = {**_STOCK_ITEM, "life_cycle": "   "}
        resp = {**_RESPONSE_ONE, "stock": [item]}
        provider = _make_provider()
        with patch("httpx.AsyncClient", return_value=_mock_get(resp)):
            results = await provider.search_by_mpn("RC0402FR-0710KL", 1, _DEFAULT_PREFS)

        assert results[0].lifecycle_status is None

    @pytest.mark.asyncio
    async def test_lifecycle_non_empty_preserved(self):
        """Non-empty life_cycle string is preserved as-is."""
        item = {**_STOCK_ITEM, "life_cycle": "End of Life"}
        resp = {**_RESPONSE_ONE, "stock": [item]}
        provider = _make_provider()
        with patch("httpx.AsyncClient", return_value=_mock_get(resp)):
            results = await provider.search_by_mpn("RC0402FR-0710KL", 1, _DEFAULT_PREFS)

        assert results[0].lifecycle_status == "End of Life"

    @pytest.mark.asyncio
    async def test_multiple_stock_items_create_multiple_results(self):
        """Two stock items for the same MPN → two PartResults."""
        item2 = {
            **_STOCK_ITEM,
            "distributor": {
                "distributor_name": "Mouser",
                "distributor_common_name": "Mouser",
                "distributor_region": "US",
                "distributor_country": "US",
            },
            "quantity_in_stock": 3000,
            "buy_now_url": "https://mouser.com/buy/RC0402FR-0710KL",
        }
        resp = {**_RESPONSE_ONE, "parts_returned": 2, "stock": [_STOCK_ITEM, item2]}
        provider = _make_provider()
        with patch("httpx.AsyncClient", return_value=_mock_get(resp)):
            results = await provider.search_by_mpn("RC0402FR-0710KL", 1, _DEFAULT_PREFS)

        assert len(results) == 2
        assert results[0].distributors[0].distributor == "Digi-Key"
        assert results[1].distributors[0].distributor == "Mouser"
