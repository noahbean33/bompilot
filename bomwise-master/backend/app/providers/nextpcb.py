"""
NextPCB component search API adapter.

Transport:  GET https://api.nextpcb.com/order/goods_search/ via httpx.AsyncClient.
Auth:       Custom MD5 signature scheme — all request params are sorted, concatenated,
            wrapped with AppSecret, then MD5-hashed.

Each item in the response `data[]` represents one matching part.  A single search
returns up to 20 items; pricing is returned as quantity-break tiers.

Note on stock:  the `max` field represents the maximum purchasable quantity, not a
confirmed warehouse stock count.
"""

import hashlib
import logging
import time
import urllib.parse
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

_BASE_URL = "https://api.nextpcb.com"
_SEARCH_PATH = "/order/goods_search/"

PROVIDER_NAME = "nextpcb"


class NextPCBAdapter(ComponentProvider):
    """Component provider backed by the NextPCB parts search API."""

    PROVIDER_NAME = "nextpcb"
    DAILY_LIMIT = None

    def __init__(self) -> None:
        from app.core.database import settings  # avoid circular import

        if not settings.nextpcb_app_id or not settings.nextpcb_app_secret:
            raise ValueError(
                "NEXTPCB_APP_ID and NEXTPCB_APP_SECRET must both be set to use the NextPCB provider"
            )

        self._app_id: str = settings.nextpcb_app_id
        self._app_secret: str = settings.nextpcb_app_secret

    # ------------------------------------------------------------------
    # Signing utility
    # ------------------------------------------------------------------

    def _sign_params(self, params: dict) -> str:
        """Compute the NextPCB MD5 request signature.

        Algorithm (from NextPCB API specification):
        1. Sort all param keys alphabetically.
        2. URL-encode each value (UTF-8), concatenate as ``key=val&key=val`` → String A.
        3. Prepend and append AppSecret → String B = AppSecret + StringA + AppSecret.
        4. Return ``MD5(StringB).hexdigest()``.

        The ``signature`` param itself must NOT be included in the param dict passed
        to this method.
        """
        sorted_pairs = "&".join(
            f"{k}={urllib.parse.quote(str(v), safe='')}"
            for k, v in sorted(params.items())
        )
        string_b = self._app_secret + sorted_pairs + self._app_secret
        return hashlib.md5(string_b.encode("utf-8")).hexdigest()

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
            distributor_coverage=[PROVIDER_NAME],
        )

    async def search_by_mpn(
        self,
        mpn: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        return await self._search(keyword=mpn, match_type="exact_mpn")

    async def search_by_keyword(
        self,
        keyword: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        return await self._search(keyword=keyword, match_type="keyword")

    async def search_by_distributor_pn(
        self,
        distributor: str,
        pn: str,
        quantity: int,
    ) -> list[PartResult]:
        raise NotImplementedError("search_by_distributor_pn not implemented for NextPCB")

    async def search_parametric(
        self,
        params: ParametricQuery,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        raise NotImplementedError("search_parametric not implemented for NextPCB")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _search(self, keyword: str, match_type: str) -> list[PartResult]:
        timestamp = int(time.time())

        # All five system params are included in the signature calculation.
        sys_params: dict = {
            "appid": self._app_id,
            "timestamp": timestamp,
            "keyword": keyword,
            "offset": 0,
            "limit": 20,
        }

        signature = self._sign_params(sys_params)

        # Include signature in the actual request but NOT in the signature input.
        request_params = {**sys_params, "signature": signature}

        logger.debug("NextPCB search: keyword=%r timestamp=%d", keyword, timestamp)

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_BASE_URL + _SEARCH_PATH, params=request_params)
            logger.debug("NextPCB HTTP %d for keyword=%r", resp.status_code, keyword)

            # Warn when the rate-limit budget is nearly exhausted.
            rate_remaining = resp.headers.get("X-Rate-Limit-Remaining")
            if rate_remaining is not None:
                try:
                    if int(rate_remaining) <= 5:
                        logger.warning(
                            "NextPCB rate limit nearly exhausted: X-Rate-Limit-Remaining=%s",
                            rate_remaining,
                        )
                except ValueError:
                    pass

            resp.raise_for_status()

        payload = resp.json()
        response_code = str(payload.get("response_code", ""))

        if response_code != "2000":
            error_msg = payload.get("error_message") or "(no error_message)"
            logger.warning(
                "NextPCB non-success response: response_code=%r error_message=%r keyword=%r",
                response_code,
                error_msg,
                keyword,
            )
            return []

        items = payload.get("data") or []
        return self._map_response(items, match_type=match_type)

    def _map_response(self, items: list, match_type: str) -> list[PartResult]:
        results: list[PartResult] = []
        for item in items:
            result = self._map_item(item, match_type=match_type)
            if result is not None:
                results.append(result)
        return results

    def _map_item(self, item: dict, match_type: str) -> PartResult | None:
        mpn = (item.get("goods_name") or "").strip()
        if not mpn:
            return None

        # Pricing tiers: purchases → quantity, unit_price → price
        pricing: list[PriceBreak] = []
        for tier in item.get("price_step") or []:
            try:
                pricing.append(
                    PriceBreak(
                        quantity=int(tier["purchases"]),
                        unit_price=float(tier["unit_price"]),
                        currency="USD",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue

        # max → stock (max purchasable quantity, not confirmed warehouse qty)
        try:
            stock = int(item.get("max") or 0)
        except (ValueError, TypeError):
            stock = 0

        # min → moq
        try:
            moq_raw = item.get("min")
            moq = int(moq_raw) if moq_raw is not None else None
        except (ValueError, TypeError):
            moq = None

        # url → product_url (stored in DistributorStock.url)
        product_url = item.get("url") or None

        distributor = DistributorStock(
            distributor=PROVIDER_NAME,
            stock=stock,
            moq=moq,
            url=product_url,
        )

        # dt → lead_time; stored in tech_specs since PartResult has no dedicated field
        lead_time = item.get("dt")
        tech_specs: dict | None = {"lead_time": lead_time} if lead_time else None

        return PartResult(
            mpn=mpn,
            manufacturer=item.get("brand_name") or "",
            description=item.get("goods_desc") or None,
            package=item.get("encap") or None,
            pricing=pricing,
            stock_total=stock,
            distributors=[distributor],
            lifecycle_status=None,
            tech_specs=tech_specs,
            datasheet_url=None,
            image_url=item.get("goods_img") or None,
            similar_parts=None,
            source_provider=PROVIDER_NAME,
            retrieved_at=datetime.now(UTC),
            match_type=match_type,
        )
