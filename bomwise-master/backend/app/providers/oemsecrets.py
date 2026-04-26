"""
OEMSecrets API adapter.

Transport:  GET https://oemsecretsapi.com/partsearch via httpx.AsyncClient.
Auth:       API key passed as query param `apiKey`.
Currency / country:  derived from MergedPreferences.

Each item in `stock[]` represents one distributor selling the searched part,
so one search can return multiple stock items for the same MPN.  We create
one PartResult per stock item; the matching service then ranks them.
"""

import logging
from datetime import UTC, datetime

import httpx

from app.providers.base import ComponentProvider
from app.providers.schema import (
    DistributorStock,
    ParametricQuery,
    PartResult,
    PriceBreak,
    ProviderCapabilities,
)
from app.schemas.preferences import MergedPreferences

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://oemsecretsapi.com/partsearch"

# Minimal currency → ISO-3166 country code mapping.  Defaults to "US".
_CURRENCY_TO_COUNTRY: dict[str, str] = {
    "USD": "US",
    "CAD": "CA",
    "GBP": "GB",
    "EUR": "DE",
    "AUD": "AU",
    "JPY": "JP",
    "CNY": "CN",
    "INR": "IN",
    "BRL": "BR",
    "MXN": "MX",
}


def _country_from_currency(currency: str) -> str:
    return _CURRENCY_TO_COUNTRY.get(currency.upper(), "US")


class OEMSecretsProvider(ComponentProvider):
    PROVIDER_NAME = "oemsecrets"
    DAILY_LIMIT = 250  # free tier; paid tier allows 1000

    def __init__(self) -> None:
        from app.core.database import settings  # avoid circular import

        self._api_key = settings.oemsecrets_api_key

    # ------------------------------------------------------------------
    # ComponentProvider interface
    # ------------------------------------------------------------------

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            has_lifecycle_status=False,  # field exists but is usually empty
            has_tech_specs=False,
            has_datasheet_urls=True,
            has_similar_parts=False,
            has_parametric_search=False,
            distributor_coverage=[],  # varies per response; not statically known
        )

    async def search_by_mpn(
        self,
        mpn: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        currency = preferences.preferred_currency or "USD"
        country_code = _country_from_currency(currency)

        params = {
            "apiKey": self._api_key,
            "searchTerm": mpn,
            "countryCode": country_code,
            "currency": currency,
        }

        logger.debug("OEMSecrets search_by_mpn: MPN=%r currency=%s country=%s", mpn, currency, country_code)

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_SEARCH_URL, params=params)
            logger.debug("OEMSecrets HTTP %d for MPN=%r", resp.status_code, mpn)
            resp.raise_for_status()

        payload = resp.json()
        return self._map_response(payload, currency)

    async def search_by_keyword(
        self,
        keyword: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        """Search OEMSecrets by a free-text keyword (e.g. '10k 0402')."""
        currency = preferences.preferred_currency or "USD"
        country_code = _country_from_currency(currency)

        params = {
            "apiKey": self._api_key,
            "searchTerm": keyword,
            "countryCode": country_code,
            "currency": currency,
        }

        logger.debug("OEMSecrets search_by_keyword: keyword=%r", keyword)

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_SEARCH_URL, params=params)
            resp.raise_for_status()

        payload = resp.json()
        results = self._map_response(payload, currency)
        # Override match_type for all results to signal keyword origin
        return [r.model_copy(update={"match_type": "keyword"}) for r in results]

    async def search_by_distributor_pn(
        self,
        distributor: str,
        pn: str,
        quantity: int,
    ) -> list[PartResult]:
        raise NotImplementedError("search_by_distributor_pn not implemented for OEMSecrets")

    async def search_parametric(
        self,
        params: ParametricQuery,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        raise NotImplementedError("search_parametric not implemented for OEMSecrets")

    # ------------------------------------------------------------------
    # Response mapping
    # ------------------------------------------------------------------

    def _map_response(self, data: dict, currency: str) -> list[PartResult]:
        results: list[PartResult] = []
        for item in data.get("stock") or []:
            result = self._map_stock_item(item, currency)
            if result is not None:
                results.append(result)
        return results

    def _map_stock_item(self, item: dict, currency: str) -> PartResult | None:
        mpn = item.get("part_number", "").strip()
        if not mpn:
            return None

        # Pricing: use the requested currency; fall back to first available key.
        prices_by_currency: dict = item.get("prices") or {}
        price_list = prices_by_currency.get(currency) or next(iter(prices_by_currency.values()), [])
        pricing: list[PriceBreak] = []
        for p in price_list:
            try:
                pricing.append(
                    PriceBreak(
                        quantity=int(p["unit_break"]),
                        unit_price=float(p["unit_price"]),
                        currency=currency,
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue

        # Distributor
        dist_obj = item.get("distributor") or {}
        dist_name = dist_obj.get("distributor_name") or dist_obj.get("distributor_common_name") or "unknown"
        moq_raw = item.get("moq")
        try:
            moq = int(moq_raw) if moq_raw is not None else None
        except (ValueError, TypeError):
            moq = None

        distributor = DistributorStock(
            distributor=dist_name,
            stock=int(item.get("quantity_in_stock") or 0),
            moq=moq,
            url=item.get("buy_now_url") or None,
        )

        # lifecycle_status: treat empty string as None
        lifecycle_raw = item.get("life_cycle") or ""
        lifecycle_status = lifecycle_raw.strip() or None

        # OEMSecrets does not return an image URL in its partsearch response.
        # image_url is left null.
        return PartResult(
            mpn=mpn,
            manufacturer=item.get("manufacturer") or "",
            description=item.get("description") or None,
            package=None,
            pricing=pricing,
            stock_total=int(item.get("quantity_in_stock") or 0),
            distributors=[distributor],
            lifecycle_status=lifecycle_status,
            tech_specs=None,
            datasheet_url=item.get("datasheet_url") or None,
            image_url=None,
            similar_parts=None,
            source_provider="oemsecrets",
            retrieved_at=datetime.now(UTC),
            match_type="exact_mpn",
        )
