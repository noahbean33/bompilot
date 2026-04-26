"""
NextPCBAdapter unit tests.

No live HTTP calls are made — httpx.AsyncClient is patched throughout.
Covers:
  - Correct signature generation for a known input (algorithm verification)
  - Successful response parsing into PartResult objects including price tiers
  - Non-2000 response_code returns empty list and logs a warning
  - Missing NEXTPCB_APP_ID / APP_SECRET causes ValueError at construction
    (provider is not raised at import time)
"""

import hashlib
import logging
import urllib.parse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.nextpcb import NextPCBAdapter
from app.schemas.preferences import MergedPreferences

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_PREFS = MergedPreferences(preferred_currency="USD", preferred_distributors=[])

_TEST_APP_ID = "79eadc3949ba59abbe56e057f20f883e"
_TEST_APP_SECRET = "test_app_secret"


def _make_adapter() -> NextPCBAdapter:
    """Build a NextPCBAdapter instance bypassing __init__ settings lookup."""
    adapter = NextPCBAdapter.__new__(NextPCBAdapter)
    adapter._app_id = _TEST_APP_ID
    adapter._app_secret = _TEST_APP_SECRET
    return adapter


def _mock_http(payload: dict, headers: dict | None = None):
    """Return an async context-manager mock that yields an httpx-like response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = headers or {}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return mock_client


# ---------------------------------------------------------------------------
# Sample API response data
# ---------------------------------------------------------------------------

_ITEM_LM358 = {
    "goods_name": "LM358DR",
    "brand_name": "Texas Instruments",
    "encap": "SOIC-8",
    "last_cat_name": "Op Amps",
    "goods_desc": "Dual Operational Amplifier, 1MHz, SOIC-8",
    "min": 10,
    "max": 5000,
    "dt": "3-5 days",
    "url": "https://www.nextpcb.com/part/LM358DR",
    "goods_img": "https://cdn.nextpcb.com/img/lm358dr.jpg",
    "price_step": [
        {"purchases": 1, "unit_price": 0.35},
        {"purchases": 10, "unit_price": 0.28},
        {"purchases": 100, "unit_price": 0.20},
    ],
}

_SUCCESS_RESPONSE = {
    "response_code": "2000",
    "error_message": "",
    "data": [_ITEM_LM358],
}

_ERROR_RESPONSE = {
    "response_code": "4001",
    "error_message": "Invalid signature",
    "data": [],
}


# ---------------------------------------------------------------------------
# 1. Signature generation — algorithm verification
# ---------------------------------------------------------------------------


class TestSignParams:
    def test_signature_algorithm_matches_spec(self):
        """
        Verify the MD5 signing algorithm matches the NextPCB API specification.

        From the NextPCB API docs:
          appid = 79eadc3949ba59abbe56e057f20f883e
          timestamp = 1374908054
          expected sig = 5541f9c529dae41c417e59dbde934ba6

        The docs example uses only appid + timestamp with the specific AppSecret
        published alongside those test credentials.  Here we verify the algorithm
        structure against a locally-constructed known case using the same appid and
        timestamp.  The expected value is derived from a step-by-step reference
        implementation of the spec, which acts as an independent oracle.
        """
        adapter = _make_adapter()

        params = {
            "appid": _TEST_APP_ID,
            "timestamp": 1374908054,
            "keyword": "LM358",
            "offset": 0,
            "limit": 20,
        }

        # Reference implementation — step-by-step per the spec:
        # 1. Sort keys alphabetically.
        # 2. URL-encode values (UTF-8), concatenate as key=val&key=val → StringA.
        # 3. StringB = AppSecret + StringA + AppSecret.
        # 4. MD5(StringB).hexdigest()
        sorted_pairs = "&".join(
            f"{k}={urllib.parse.quote(str(v), safe='')}"
            for k, v in sorted(params.items())
        )
        string_b = _TEST_APP_SECRET + sorted_pairs + _TEST_APP_SECRET
        expected = hashlib.md5(string_b.encode("utf-8")).hexdigest()

        assert adapter._sign_params(params) == expected

    def test_signature_is_32_hex_chars(self):
        """MD5 hexdigest is always 32 lowercase hex characters."""
        adapter = _make_adapter()
        sig = adapter._sign_params({"appid": "x", "timestamp": 1})
        assert len(sig) == 32
        assert sig == sig.lower()

    def test_signature_depends_on_all_param_values(self):
        """Changing any single param value changes the signature."""
        adapter = _make_adapter()
        base_params = {"appid": _TEST_APP_ID, "timestamp": 100, "keyword": "LM358"}
        sig_base = adapter._sign_params(base_params)

        # Change keyword
        assert adapter._sign_params({**base_params, "keyword": "NE555"}) != sig_base
        # Change timestamp
        assert adapter._sign_params({**base_params, "timestamp": 101}) != sig_base

    def test_signature_is_deterministic(self):
        """Same inputs always produce the same signature."""
        adapter = _make_adapter()
        params = {"appid": _TEST_APP_ID, "timestamp": 9999, "keyword": "ABC"}
        assert adapter._sign_params(params) == adapter._sign_params(params)

    def test_signature_excludes_signature_key(self):
        """
        If a 'signature' key were accidentally included in params it would change the
        output — caller is responsible for not passing it.  Verify the reference case
        differs from the case where an extra key is injected.
        """
        adapter = _make_adapter()
        clean = {"appid": "a", "timestamp": 1}
        with_sig = {"appid": "a", "timestamp": 1, "signature": "xxx"}
        assert adapter._sign_params(clean) != adapter._sign_params(with_sig)

    def test_url_encoding_applied_to_values(self):
        """Values with special characters are URL-encoded before signing."""
        adapter = _make_adapter()
        params_encoded = {"keyword": "10k 0402"}
        params_plain = {"keyword": "10k0402"}
        # Space gets encoded to %20 — signatures must differ.
        assert adapter._sign_params(params_encoded) != adapter._sign_params(params_plain)


# ---------------------------------------------------------------------------
# 2. Successful response parsing
# ---------------------------------------------------------------------------


class TestSearchByMPN:
    @pytest.mark.asyncio
    async def test_successful_match_returns_part_result(self):
        adapter = _make_adapter()
        with patch("httpx.AsyncClient", return_value=_mock_http(_SUCCESS_RESPONSE)):
            results = await adapter.search_by_mpn("LM358", 10, _DEFAULT_PREFS)

        assert len(results) == 1
        r = results[0]
        assert r.mpn == "LM358DR"
        assert r.manufacturer == "Texas Instruments"
        assert r.package == "SOIC-8"
        assert r.description == "Dual Operational Amplifier, 1MHz, SOIC-8"
        assert r.source_provider == "nextpcb"
        assert r.match_type == "exact_mpn"
        assert r.image_url == "https://cdn.nextpcb.com/img/lm358dr.jpg"

    @pytest.mark.asyncio
    async def test_stock_and_moq_mapped(self):
        adapter = _make_adapter()
        with patch("httpx.AsyncClient", return_value=_mock_http(_SUCCESS_RESPONSE)):
            results = await adapter.search_by_mpn("LM358", 1, _DEFAULT_PREFS)

        r = results[0]
        # max → stock_total (max purchasable qty)
        assert r.stock_total == 5000
        dist = r.distributors[0]
        assert dist.distributor == "nextpcb"
        assert dist.stock == 5000
        # min → moq
        assert dist.moq == 10
        assert dist.url == "https://www.nextpcb.com/part/LM358DR"

    @pytest.mark.asyncio
    async def test_pricing_tiers_mapped(self):
        adapter = _make_adapter()
        with patch("httpx.AsyncClient", return_value=_mock_http(_SUCCESS_RESPONSE)):
            results = await adapter.search_by_mpn("LM358", 1, _DEFAULT_PREFS)

        pricing = results[0].pricing
        assert len(pricing) == 3
        assert pricing[0].quantity == 1
        assert pricing[0].unit_price == pytest.approx(0.35)
        assert pricing[0].currency == "USD"
        assert pricing[1].quantity == 10
        assert pricing[1].unit_price == pytest.approx(0.28)
        assert pricing[2].quantity == 100
        assert pricing[2].unit_price == pytest.approx(0.20)

    @pytest.mark.asyncio
    async def test_lead_time_stored_in_tech_specs(self):
        adapter = _make_adapter()
        with patch("httpx.AsyncClient", return_value=_mock_http(_SUCCESS_RESPONSE)):
            results = await adapter.search_by_mpn("LM358", 1, _DEFAULT_PREFS)

        assert results[0].tech_specs == {"lead_time": "3-5 days"}

    @pytest.mark.asyncio
    async def test_missing_lead_time_gives_none_tech_specs(self):
        item = {**_ITEM_LM358}
        del item["dt"]
        resp = {**_SUCCESS_RESPONSE, "data": [item]}
        adapter = _make_adapter()
        with patch("httpx.AsyncClient", return_value=_mock_http(resp)):
            results = await adapter.search_by_mpn("LM358", 1, _DEFAULT_PREFS)

        assert results[0].tech_specs is None

    @pytest.mark.asyncio
    async def test_empty_data_returns_empty_list(self):
        resp = {**_SUCCESS_RESPONSE, "data": []}
        adapter = _make_adapter()
        with patch("httpx.AsyncClient", return_value=_mock_http(resp)):
            results = await adapter.search_by_mpn("NOTAPART", 1, _DEFAULT_PREFS)

        assert results == []

    @pytest.mark.asyncio
    async def test_multiple_items_all_returned(self):
        item2 = {**_ITEM_LM358, "goods_name": "LM358N", "encap": "DIP-8"}
        resp = {**_SUCCESS_RESPONSE, "data": [_ITEM_LM358, item2]}
        adapter = _make_adapter()
        with patch("httpx.AsyncClient", return_value=_mock_http(resp)):
            results = await adapter.search_by_mpn("LM358", 1, _DEFAULT_PREFS)

        assert len(results) == 2
        assert results[0].mpn == "LM358DR"
        assert results[1].mpn == "LM358N"
        assert results[1].package == "DIP-8"

    @pytest.mark.asyncio
    async def test_keyword_search_sets_match_type(self):
        adapter = _make_adapter()
        with patch("httpx.AsyncClient", return_value=_mock_http(_SUCCESS_RESPONSE)):
            results = await adapter.search_by_keyword("op amp 8-pin", 1, _DEFAULT_PREFS)

        assert results[0].match_type == "keyword"


# ---------------------------------------------------------------------------
# 3. Non-2000 response_code → empty list + warning log
# ---------------------------------------------------------------------------


class TestErrorResponse:
    @pytest.mark.asyncio
    async def test_non_2000_returns_empty_list(self):
        adapter = _make_adapter()
        with patch("httpx.AsyncClient", return_value=_mock_http(_ERROR_RESPONSE)):
            results = await adapter.search_by_mpn("LM358", 1, _DEFAULT_PREFS)

        assert results == []

    @pytest.mark.asyncio
    async def test_non_2000_logs_warning(self, caplog):
        adapter = _make_adapter()
        with caplog.at_level(logging.WARNING, logger="app.providers.nextpcb"):
            with patch("httpx.AsyncClient", return_value=_mock_http(_ERROR_RESPONSE)):
                await adapter.search_by_mpn("LM358", 1, _DEFAULT_PREFS)

        assert any("4001" in msg for msg in caplog.messages)

    @pytest.mark.asyncio
    async def test_missing_response_code_treated_as_error(self):
        """A response with no response_code field is treated as non-2000."""
        resp = {"data": [_ITEM_LM358]}  # no response_code key
        adapter = _make_adapter()
        with patch("httpx.AsyncClient", return_value=_mock_http(resp)):
            results = await adapter.search_by_mpn("LM358", 1, _DEFAULT_PREFS)

        assert results == []


# ---------------------------------------------------------------------------
# 4. Rate-limit header handling
# ---------------------------------------------------------------------------


class TestRateLimitHeader:
    @pytest.mark.asyncio
    async def test_rate_limit_warning_when_low(self, caplog):
        adapter = _make_adapter()
        headers = {"X-Rate-Limit-Remaining": "3"}
        with caplog.at_level(logging.WARNING, logger="app.providers.nextpcb"):
            with patch("httpx.AsyncClient", return_value=_mock_http(_SUCCESS_RESPONSE, headers=headers)):
                await adapter.search_by_mpn("LM358", 1, _DEFAULT_PREFS)

        assert any("rate limit" in msg.lower() for msg in caplog.messages)

    @pytest.mark.asyncio
    async def test_no_rate_limit_warning_when_ample(self, caplog):
        adapter = _make_adapter()
        headers = {"X-Rate-Limit-Remaining": "100"}
        with caplog.at_level(logging.WARNING, logger="app.providers.nextpcb"):
            with patch("httpx.AsyncClient", return_value=_mock_http(_SUCCESS_RESPONSE, headers=headers)):
                await adapter.search_by_mpn("LM358", 1, _DEFAULT_PREFS)

        rate_warnings = [m for m in caplog.messages if "rate limit" in m.lower()]
        assert rate_warnings == []

    @pytest.mark.asyncio
    async def test_no_rate_limit_warning_at_boundary(self, caplog):
        """Exactly 5 remaining should still trigger the warning (≤ 5)."""
        adapter = _make_adapter()
        headers = {"X-Rate-Limit-Remaining": "5"}
        with caplog.at_level(logging.WARNING, logger="app.providers.nextpcb"):
            with patch("httpx.AsyncClient", return_value=_mock_http(_SUCCESS_RESPONSE, headers=headers)):
                await adapter.search_by_mpn("LM358", 1, _DEFAULT_PREFS)

        assert any("rate limit" in msg.lower() for msg in caplog.messages)


# ---------------------------------------------------------------------------
# 5. Missing credentials — ValueError at construction, not at import
# ---------------------------------------------------------------------------


class TestMissingCredentials:
    def test_raises_value_error_when_app_id_missing(self, monkeypatch):
        """Adapter raises ValueError (not ImportError) when APP_ID is absent."""
        import app.core.database as db_module

        monkeypatch.setattr(db_module.settings, "nextpcb_app_id", None)
        monkeypatch.setattr(db_module.settings, "nextpcb_app_secret", "secret")

        with pytest.raises(ValueError, match="NEXTPCB_APP_ID"):
            NextPCBAdapter()

    def test_raises_value_error_when_app_secret_missing(self, monkeypatch):
        import app.core.database as db_module

        monkeypatch.setattr(db_module.settings, "nextpcb_app_id", "some_id")
        monkeypatch.setattr(db_module.settings, "nextpcb_app_secret", None)

        with pytest.raises(ValueError, match="NEXTPCB_APP_SECRET"):
            NextPCBAdapter()

    def test_raises_value_error_when_both_missing(self, monkeypatch):
        import app.core.database as db_module

        monkeypatch.setattr(db_module.settings, "nextpcb_app_id", None)
        monkeypatch.setattr(db_module.settings, "nextpcb_app_secret", None)

        with pytest.raises(ValueError):
            NextPCBAdapter()

    def test_import_does_not_raise(self):
        """Importing the module must never raise even when credentials are absent."""
        import importlib

        import app.providers.nextpcb as mod

        importlib.reload(mod)  # re-execute module-level code — must not raise


# ---------------------------------------------------------------------------
# 6. Capabilities
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_capabilities(self):
        adapter = _make_adapter()
        caps = adapter.capabilities()
        assert caps.has_lifecycle_status is False
        assert caps.has_tech_specs is False
        assert caps.has_datasheet_urls is False
        assert caps.has_similar_parts is False
        assert caps.has_parametric_search is False
        assert "nextpcb" in caps.distributor_coverage
