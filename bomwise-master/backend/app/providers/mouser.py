"""
Mouser Electronics API adapter.

Transport:  POST https://api.mouser.com/api/v1/search/partnumber via httpx.AsyncClient.
            POST https://api.mouser.com/api/v1/search/keyword for keyword search.
Auth:       API key passed as query param `apiKey`.

One call returns up to N parts; we create one PartResult per returned part.
search_by_mpn and search_by_keyword are implemented.
search_by_distributor_pn and search_parametric raise NotImplementedError.
"""

import logging
import re
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

_SEARCH_URL = "https://api.mouser.com/api/v1/search/partnumber"
_KEYWORD_SEARCH_URL = "https://api.mouser.com/api/v1/search/keyword"

# Strip everything that is not a digit from Mouser's Availability field.
# Examples: "12,345 In Stock", "45000", "0" → 12345, 45000, 0
_DIGITS_RE = re.compile(r"[^\d]")


def _parse_stock(availability: str) -> int:
    """Extract a non-negative integer from a Mouser availability string."""
    digits = _DIGITS_RE.sub("", availability)
    return int(digits) if digits else 0


def _parse_price(price_str: str) -> float | None:
    """Parse a price string that may start with a currency symbol, e.g. '$0.15'."""
    cleaned = price_str.strip().lstrip("$€£¥").replace(",", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


class MouserProvider(ComponentProvider):
    PROVIDER_NAME = "mouser"
    DAILY_LIMIT = None

    def __init__(self) -> None:
        from app.core.database import settings  # avoid circular import

        self._api_key = settings.mouser_api_key
        if not self._api_key:
            raise ValueError(
                "MOUSER_API_KEY is not configured. "
                "Set it in the environment or .env file."
            )

    # ------------------------------------------------------------------
    # ComponentProvider interface
    # ------------------------------------------------------------------

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            has_lifecycle_status=False,
            has_tech_specs=False,
            has_datasheet_urls=False,
            has_similar_parts=False,
            has_parametric_search=False,
            distributor_coverage=["mouser"],
        )

    async def search_by_mpn(
        self,
        mpn: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        logger.debug("MouserProvider.search_by_mpn: MPN=%r", mpn)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _SEARCH_URL,
                params={"apiKey": self._api_key},
                json={
                    "SearchByPartRequest": {
                        "mouserPartNumber": mpn,
                        "partSearchOptions": "",
                    }
                },
            )
            logger.debug("MouserProvider HTTP %d for MPN=%r", resp.status_code, mpn)
            if resp.status_code >= 400:
                logger.warning(
                    "MouserProvider: HTTP %d for MPN=%r — returning empty",
                    resp.status_code,
                    mpn,
                )
                return []
            resp.raise_for_status()

        payload = resp.json()
        errors = payload.get("Errors") or []
        if errors:
            logger.warning("MouserProvider: API errors for MPN=%r: %s", mpn, errors)

        parts = (payload.get("SearchResults") or {}).get("Parts") or []
        return [self._map_part(p) for p in parts if p.get("ManufacturerPartNumber")]

    async def search_by_keyword(
        self,
        keyword: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        logger.debug("MouserProvider.search_by_keyword: keyword=%r", keyword)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _KEYWORD_SEARCH_URL,
                params={"apiKey": self._api_key},
                json={
                    "KeywordSearchRequest": {
                        "keyword": keyword,
                        "MaxRecords": 10,
                        "SearchOptions": "",
                    }
                },
            )
            logger.debug("MouserProvider HTTP %d for keyword=%r", resp.status_code, keyword)
            if resp.status_code >= 400:
                logger.warning(
                    "MouserProvider: HTTP %d for keyword=%r — returning empty",
                    resp.status_code,
                    keyword,
                )
                return []
            resp.raise_for_status()

        payload = resp.json()
        errors = payload.get("Errors") or []
        if errors:
            logger.warning("MouserProvider: API errors for keyword=%r: %s", keyword, errors)

        parts = (payload.get("KeywordSearchResults") or {}).get("Parts") or []
        results = [self._map_keyword_part(p) for p in parts if p.get("ManufacturerPartNumber")]
        return [r.model_copy(update={"match_type": "keyword"}) for r in results]

    async def search_by_distributor_pn(
        self,
        distributor: str,
        pn: str,
        quantity: int,
    ) -> list[PartResult]:
        raise NotImplementedError("search_by_distributor_pn not implemented for Mouser")

    async def search_parametric(
        self,
        params: ParametricQuery,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        raise NotImplementedError("search_parametric not implemented for Mouser")

    # ------------------------------------------------------------------
    # Response mapping
    # ------------------------------------------------------------------

    def _map_keyword_part(self, part: dict) -> PartResult:
        """Map a keyword search result to PartResult — similar to _map_part
        but keyword search response has slightly different structure.
        """
        mpn = (part.get("ManufacturerPartNumber") or "").strip()

        # Stock: keyword search returns stock differently
        availability_raw = part.get("Availability") or "0"
        stock = _parse_stock(str(availability_raw))

        pricing: list[PriceBreak] = []
        for pb in part.get("PriceBreaks") or []:
            price = _parse_price(str(pb.get("Price") or ""))
            try:
                qty = int(pb.get("Quantity") or 1)
            except (ValueError, TypeError):
                qty = 1
            currency = (pb.get("Currency") or "USD").strip()
            if price is not None:
                pricing.append(PriceBreak(quantity=qty, unit_price=price, currency=currency))

        distributor = DistributorStock(
            distributor="mouser",
            stock=stock,
            moq=None,
            url=part.get("ProductDetailUrl") or None,
        )

        image_url: str | None = part.get("ImagePath") or None
        if image_url and not image_url.startswith("http"):
            image_url = None

        return PartResult(
            mpn=mpn,
            manufacturer=(part.get("ManufacturerName") or "").strip(),
            description=(part.get("Description") or None),
            package=None,
            pricing=pricing,
            stock_total=stock,
            distributors=[distributor],
            lifecycle_status=None,
            tech_specs=None,
            datasheet_url=None,
            image_url=image_url,
            similar_parts=None,
            source_provider="mouser",
            retrieved_at=datetime.now(UTC),
            match_type="exact_mpn",
        )

    def _map_part(self, part: dict) -> PartResult:
        mpn = (part.get("ManufacturerPartNumber") or "").strip()

        # Stock: Mouser returns strings like "12,345 In Stock"
        availability_raw = part.get("Availability") or "0"
        stock = _parse_stock(str(availability_raw))

        # Price breaks
        pricing: list[PriceBreak] = []
        for pb in part.get("PriceBreaks") or []:
            price = _parse_price(str(pb.get("Price") or ""))
            try:
                qty = int(pb.get("Quantity") or 1)
            except (ValueError, TypeError):
                qty = 1
            currency = (pb.get("Currency") or "USD").strip()
            if price is not None:
                pricing.append(PriceBreak(quantity=qty, unit_price=price, currency=currency))

        distributor = DistributorStock(
            distributor="mouser",
            stock=stock,
            moq=None,
            url=part.get("ProductDetailUrl") or None,
        )

        # image_url: Mouser returns ImagePath; treat empty string as None
        image_url: str | None = part.get("ImagePath") or None
        if image_url and not image_url.startswith("http"):
            image_url = None

        return PartResult(
            mpn=mpn,
            manufacturer=(part.get("Manufacturer") or "").strip(),
            description=(part.get("Description") or None),
            package=None,
            pricing=pricing,
            stock_total=stock,
            distributors=[distributor],
            lifecycle_status=None,
            tech_specs=None,
            datasheet_url=None,
            image_url=image_url,
            similar_parts=None,
            source_provider="mouser",
            retrieved_at=datetime.now(UTC),
            match_type="exact_mpn",
        )
