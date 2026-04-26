"""
Tests for MouserProvider.

All HTTP calls are mocked — no live Mouser API calls are made.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.mouser import MouserProvider, _parse_price, _parse_stock
from app.schemas.preferences import MergedPreferences


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def test_parse_stock_plain_integer():
    assert _parse_stock("45000") == 45000


def test_parse_stock_with_comma_and_suffix():
    assert _parse_stock("12,345 In Stock") == 12345


def test_parse_stock_zero():
    assert _parse_stock("0") == 0


def test_parse_stock_empty():
    assert _parse_stock("") == 0


def test_parse_stock_no_digits():
    assert _parse_stock("In Stock") == 0


def test_parse_price_dollar_prefix():
    assert _parse_price("$0.15") == pytest.approx(0.15)


def test_parse_price_plain():
    assert _parse_price("1.234") == pytest.approx(1.234)


def test_parse_price_invalid():
    assert _parse_price("") is None
    assert _parse_price("N/A") is None


# ---------------------------------------------------------------------------
# Fixture: provider instance bypassing credential check
# ---------------------------------------------------------------------------


@pytest.fixture()
def provider(monkeypatch):
    """Return a MouserProvider with a fake API key."""
    monkeypatch.setattr(
        "app.providers.mouser.MouserProvider.__init__",
        lambda self: setattr(self, "_api_key", "FAKE_KEY") or None,
    )
    return MouserProvider()


# ---------------------------------------------------------------------------
# Sample API response
# ---------------------------------------------------------------------------


def _mouser_response(parts: list[dict]) -> dict:
    return {
        "Errors": [],
        "SearchResults": {
            "NumberOfResult": len(parts),
            "Parts": parts,
        },
    }


def _sample_part() -> dict:
    return {
        "MouserPartNumber": "581-GRM155R61A104KA01D",
        "ManufacturerPartNumber": "GRM155R61A104KA01D",
        "Manufacturer": "Murata",
        "Description": "100nF 10V 0402 Ceramic Capacitor X5R",
        "Availability": "50,000 In Stock",
        "PriceBreaks": [
            {"Quantity": 1, "Price": "$0.10", "Currency": "USD"},
            {"Quantity": 100, "Price": "$0.05", "Currency": "USD"},
        ],
        "ImagePath": "https://mouser.com/images/murata/images/grm_rcv1.jpg",
        "ProductDetailUrl": "https://mouser.com/ProductDetail/Murata/GRM155R61A104KA01D",
    }


# ---------------------------------------------------------------------------
# search_by_mpn — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_mpn_returns_mapped_result(provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mouser_response([_sample_part()])
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("app.providers.mouser.httpx.AsyncClient", return_value=mock_client):
        results = await provider.search_by_mpn(
            "GRM155R61A104KA01D", 1, MergedPreferences()
        )

    assert len(results) == 1
    r = results[0]
    assert r.mpn == "GRM155R61A104KA01D"
    assert r.manufacturer == "Murata"
    assert r.description == "100nF 10V 0402 Ceramic Capacitor X5R"
    assert r.stock_total == 50000
    assert r.source_provider == "mouser"
    assert r.match_type == "exact_mpn"
    assert len(r.distributors) == 1
    assert r.distributors[0].distributor == "mouser"
    assert r.distributors[0].stock == 50000
    assert len(r.pricing) == 2
    assert r.pricing[0].unit_price == pytest.approx(0.10)
    assert r.pricing[1].unit_price == pytest.approx(0.05)
    assert r.image_url == "https://mouser.com/images/murata/images/grm_rcv1.jpg"


# ---------------------------------------------------------------------------
# search_by_mpn — no results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_mpn_empty_parts(provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mouser_response([])
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("app.providers.mouser.httpx.AsyncClient", return_value=mock_client):
        results = await provider.search_by_mpn("NOMATCH", 1, MergedPreferences())

    assert results == []


# ---------------------------------------------------------------------------
# HTTP 4xx → empty result, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_mpn_http_4xx_returns_empty(provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("app.providers.mouser.httpx.AsyncClient", return_value=mock_client):
        results = await provider.search_by_mpn("ANYPART", 1, MergedPreferences())

    assert results == []


# ---------------------------------------------------------------------------
# Missing API key raises clear error
# ---------------------------------------------------------------------------


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.setattr(
        "app.core.database.settings",
        MagicMock(mouser_api_key=""),
    )
    with pytest.raises(ValueError, match="MOUSER_API_KEY"):
        MouserProvider()


# ---------------------------------------------------------------------------
# Non-numeric Availability is handled gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_numeric_availability_handled(provider):
    part = _sample_part()
    part["Availability"] = "Call for Availability"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mouser_response([part])
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("app.providers.mouser.httpx.AsyncClient", return_value=mock_client):
        results = await provider.search_by_mpn("GRM155R61A104KA01D", 1, MergedPreferences())

    assert len(results) == 1
    assert results[0].stock_total == 0


# ---------------------------------------------------------------------------
# image_url is None when ImagePath is absent or non-http
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_url_none_when_absent(provider):
    part = _sample_part()
    del part["ImagePath"]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mouser_response([part])
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("app.providers.mouser.httpx.AsyncClient", return_value=mock_client):
        results = await provider.search_by_mpn("GRM155R61A104KA01D", 1, MergedPreferences())

    assert results[0].image_url is None
