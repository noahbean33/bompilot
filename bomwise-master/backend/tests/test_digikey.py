"""
Tests for DigiKeyProvider.

All HTTP calls are mocked — no live DigiKey API calls are made.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.digikey import DigiKeyProvider, _TOKEN_CACHE_KEY
from app.schemas.preferences import MergedPreferences


# ---------------------------------------------------------------------------
# Fixture: provider instance bypassing credential check
# ---------------------------------------------------------------------------


@pytest.fixture()
def provider(monkeypatch):
    """Return a DigiKeyProvider with fake credentials and Redis disabled."""
    monkeypatch.setattr(
        "app.providers.digikey.DigiKeyProvider.__init__",
        lambda self: (
            setattr(self, "_client_id", "FAKE_ID")
            or setattr(self, "_client_secret", "FAKE_SECRET")
            or setattr(self, "_mem_token", None)
            or setattr(self, "_mem_token_expiry", 0.0)
            or setattr(self, "_redis", None)
            or setattr(self, "_redis_unavailable", True)  # disable Redis in tests
            or None
        ),
    )
    return DigiKeyProvider()


# ---------------------------------------------------------------------------
# Sample API responses
# ---------------------------------------------------------------------------


def _token_response() -> dict:
    return {"access_token": "TEST_TOKEN_XYZ", "expires_in": 3600}


def _product() -> dict:
    return {
        "ManufacturerProductNumber": "RC0402FR-0710KL",
        "Manufacturer": {"Name": "Yageo"},
        "Description": {"ProductDescription": "10 kΩ ±1% 0402 resistor"},
        "QuantityAvailable": 75000,
        "Currency": "USD",
        "StandardPricing": [
            {"BreakQuantity": 1, "UnitPrice": 0.10},
            {"BreakQuantity": 100, "UnitPrice": 0.05},
        ],
        "PrimaryPhoto": "https://media.digikey.com/Photos/Yageo/RC0402FR-0710KL.jpg",
        "ProductUrl": "https://digikey.com/product-detail/RC0402FR-0710KL",
    }


def _search_response(products: list[dict]) -> dict:
    return {"Products": products, "ProductsCount": len(products)}


# ---------------------------------------------------------------------------
# Token fetch and memory caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_fetched_and_memory_cached(provider):
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = _token_response()
    token_resp.raise_for_status = MagicMock()

    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = _search_response([])
    search_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    # First call = token fetch; second call = keyword search
    mock_client.post = AsyncMock(side_effect=[token_resp, search_resp])

    with patch("app.providers.digikey.httpx.AsyncClient", return_value=mock_client):
        await provider.search_by_mpn("RC0402FR-0710KL", 1, MergedPreferences())

    # Token should now be cached in memory
    assert provider._mem_token == "TEST_TOKEN_XYZ"


@pytest.mark.asyncio
async def test_cached_token_reused_on_second_call(provider):
    """Second search_by_mpn call must NOT re-fetch the token."""
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = _token_response()
    token_resp.raise_for_status = MagicMock()

    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = _search_response([])
    search_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=[token_resp, search_resp, search_resp])

    with patch("app.providers.digikey.httpx.AsyncClient", return_value=mock_client):
        await provider.search_by_mpn("RC0402FR-0710KL", 1, MergedPreferences())
        await provider.search_by_mpn("RC0402FR-0710KL", 1, MergedPreferences())

    # post() called 3 times: 1 token fetch + 2 searches (not 4 = 2 token + 2 searches)
    assert mock_client.post.call_count == 3


# ---------------------------------------------------------------------------
# Successful MPN lookup — correctly mapped MatchResult
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_mpn_returns_mapped_result(provider):
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = _token_response()
    token_resp.raise_for_status = MagicMock()

    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = _search_response([_product()])
    search_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=[token_resp, search_resp])

    with patch("app.providers.digikey.httpx.AsyncClient", return_value=mock_client):
        results = await provider.search_by_mpn("RC0402FR-0710KL", 1, MergedPreferences())

    assert len(results) == 1
    r = results[0]
    assert r.mpn == "RC0402FR-0710KL"
    assert r.manufacturer == "Yageo"
    assert r.description == "10 kΩ ±1% 0402 resistor"
    assert r.stock_total == 75000
    assert r.source_provider == "digikey"
    assert r.match_type == "exact_mpn"
    assert len(r.distributors) == 1
    assert r.distributors[0].distributor == "digikey"
    assert len(r.pricing) == 2
    assert r.pricing[0].unit_price == pytest.approx(0.10)
    assert r.pricing[1].unit_price == pytest.approx(0.05)
    assert r.image_url == "https://media.digikey.com/Photos/Yageo/RC0402FR-0710KL.jpg"


# ---------------------------------------------------------------------------
# HTTP 4xx → empty result, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_mpn_http_4xx_returns_empty(provider):
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = _token_response()
    token_resp.raise_for_status = MagicMock()

    search_resp = MagicMock()
    search_resp.status_code = 401
    search_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=[token_resp, search_resp])

    with patch("app.providers.digikey.httpx.AsyncClient", return_value=mock_client):
        results = await provider.search_by_mpn("ANYPART", 1, MergedPreferences())

    assert results == []


# ---------------------------------------------------------------------------
# Missing credentials raises clear error
# ---------------------------------------------------------------------------


def test_missing_credentials_raises(monkeypatch):
    monkeypatch.setattr(
        "app.core.database.settings",
        MagicMock(digikey_client_id="", digikey_client_secret=""),
    )
    with pytest.raises(ValueError, match="DIGIKEY_CLIENT_ID"):
        DigiKeyProvider()


# ---------------------------------------------------------------------------
# search_by_keyword sets match_type = "keyword"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_keyword_sets_match_type(provider):
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = _token_response()
    token_resp.raise_for_status = MagicMock()

    product = _product()
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = _search_response([product])
    search_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=[token_resp, search_resp])

    with patch("app.providers.digikey.httpx.AsyncClient", return_value=mock_client):
        results = await provider.search_by_keyword("10k 0402", 1, MergedPreferences())

    assert len(results) == 1
    assert results[0].match_type == "keyword"


# ---------------------------------------------------------------------------
# image_url is None when PrimaryPhoto absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_url_none_when_absent(provider):
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = _token_response()
    token_resp.raise_for_status = MagicMock()

    product = _product()
    del product["PrimaryPhoto"]

    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = _search_response([product])
    search_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=[token_resp, search_resp])

    with patch("app.providers.digikey.httpx.AsyncClient", return_value=mock_client):
        results = await provider.search_by_mpn("RC0402FR-0710KL", 1, MergedPreferences())

    assert results[0].image_url is None
