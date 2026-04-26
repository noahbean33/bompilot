"""
DigiKey Products API v4 adapter.

Authentication: OAuth2 client_credentials against DigiKey's identity server.
Token caching:  Redis (TTL 3500 s); falls back to in-memory if Redis is
                unavailable.
Transport:      POST https://api.digikey.com/products/v4/search/keyword via
                httpx.AsyncClient.

search_by_mpn and search_by_keyword are implemented.
search_by_distributor_pn and search_parametric raise NotImplementedError.
"""

import logging
import time
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

_TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"

# Tokens expire after 3600 s; we refresh 100 s early.
_TOKEN_CACHE_KEY = "digikey:access_token"
_TOKEN_TTL = 3500


class DigiKeyProvider(ComponentProvider):
    PROVIDER_NAME = "digikey"
    DAILY_LIMIT = None

    def __init__(self) -> None:
        from app.core.database import settings  # avoid circular import

        self._client_id = settings.digikey_client_id
        self._client_secret = settings.digikey_client_secret
        if not self._client_id or not self._client_secret:
            raise ValueError(
                "DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET are not configured. "
                "Set them in the environment or .env file."
            )

        # In-memory token fallback (used when Redis is unavailable)
        self._mem_token: str | None = None
        self._mem_token_expiry: float = 0.0

        # Lazy Redis client — initialised on first use
        self._redis = None
        self._redis_unavailable = False

    # ------------------------------------------------------------------
    # ComponentProvider interface
    # ------------------------------------------------------------------

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            has_lifecycle_status=False,
            has_tech_specs=False,
            has_datasheet_urls=True,
            has_similar_parts=False,
            has_parametric_search=False,
            distributor_coverage=["digikey"],
        )

    async def search_by_mpn(
        self,
        mpn: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        logger.debug("DigiKeyProvider.search_by_mpn: MPN=%r", mpn)
        return await self._keyword_search(mpn)

    async def search_by_keyword(
        self,
        keyword: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        logger.debug("DigiKeyProvider.search_by_keyword: keyword=%r", keyword)
        results = await self._keyword_search(keyword)
        return [r.model_copy(update={"match_type": "keyword"}) for r in results]

    async def search_by_distributor_pn(
        self,
        distributor: str,
        pn: str,
        quantity: int,
    ) -> list[PartResult]:
        raise NotImplementedError("search_by_distributor_pn not implemented for DigiKey")

    async def search_parametric(
        self,
        params: ParametricQuery,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        raise NotImplementedError("search_parametric not implemented for DigiKey")

    # ------------------------------------------------------------------
    # Internal: search
    # ------------------------------------------------------------------

    async def _keyword_search(self, keyword: str) -> list[PartResult]:
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-DIGIKEY-Client-Id": self._client_id,
                    "Content-Type": "application/json",
                },
                # DigiKey v4 uses PascalCase field names.
                # "keywords" (lowercase) is silently ignored by the API,
                # producing empty results with HTTP 200.
                json={"Keywords": keyword, "RecordCount": 10},
            )
            logger.debug("DigiKeyProvider HTTP %d for keyword=%r", resp.status_code, keyword)
            if resp.status_code >= 400:
                logger.warning(
                    "DigiKeyProvider: HTTP %d for keyword=%r — returning empty",
                    resp.status_code,
                    keyword,
                )
                return []
            resp.raise_for_status()

        payload = resp.json()
        logger.debug("DigiKeyProvider response for keyword=%r: ProductsCount=%s Products=%s",
                     keyword, payload.get("ProductsCount"), len(payload.get("Products") or []))
        products = payload.get("Products") or []
        return [self._map_product(p) for p in products if p.get("ManufacturerProductNumber")]

    # ------------------------------------------------------------------
    # Auth — Redis-backed token cache with in-memory fallback
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        # Try Redis first
        cached = self._redis_get()
        if cached:
            return cached

        # In-memory fallback (also used when Redis is down)
        if self._mem_token and time.monotonic() < self._mem_token_expiry - 60:
            return self._mem_token

        token, expires_in = await self._fetch_token()
        ttl = min(expires_in - 100, _TOKEN_TTL)

        # Store in Redis if available; always store in memory as well
        self._redis_set(token, ttl)
        self._mem_token = token
        self._mem_token_expiry = time.monotonic() + ttl

        return token

    async def _fetch_token(self) -> tuple[str, int]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            resp.raise_for_status()
        payload = resp.json()
        return payload["access_token"], int(payload.get("expires_in", 3600))

    # ------------------------------------------------------------------
    # Redis helpers (best-effort; failure falls back to memory)
    # ------------------------------------------------------------------

    def _get_redis(self):
        if self._redis_unavailable:
            return None
        if self._redis is None:
            try:
                import redis as redis_lib
                from app.core.database import settings

                self._redis = redis_lib.Redis.from_url(
                    settings.redis_url, socket_connect_timeout=2, decode_responses=True
                )
                self._redis.ping()
            except Exception as exc:
                logger.warning("DigiKeyProvider: Redis unavailable (%s), using memory cache", exc)
                self._redis = None
                self._redis_unavailable = True
        return self._redis

    def _redis_get(self) -> str | None:
        r = self._get_redis()
        if r is None:
            return None
        try:
            return r.get(_TOKEN_CACHE_KEY)
        except Exception:
            return None

    def _redis_set(self, token: str, ttl: int) -> None:
        r = self._get_redis()
        if r is None:
            return
        try:
            r.setex(_TOKEN_CACHE_KEY, ttl, token)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Response mapping
    # ------------------------------------------------------------------

    def _map_product(self, product: dict) -> PartResult:
        mpn = (product.get("ManufacturerProductNumber") or "").strip()
        manufacturer = ((product.get("Manufacturer") or {}).get("Name") or "").strip()
        description = (
            (product.get("Description") or {}).get("ProductDescription") or None
        )

        stock_raw = product.get("QuantityAvailable")
        try:
            stock = int(stock_raw) if stock_raw is not None else 0
        except (ValueError, TypeError):
            stock = 0

        # Price breaks from StandardPricing
        pricing: list[PriceBreak] = []
        currency = product.get("Currency") or "USD"
        for pb in product.get("StandardPricing") or []:
            try:
                qty = int(pb.get("BreakQuantity") or 1)
                price = float(pb.get("UnitPrice") or 0)
                pricing.append(PriceBreak(quantity=qty, unit_price=price, currency=currency))
            except (ValueError, TypeError):
                continue

        product_url = product.get("ProductUrl") or None
        distributor = DistributorStock(
            distributor="digikey",
            stock=stock,
            moq=None,
            url=product_url,
        )

        # image_url from PrimaryPhoto
        image_url: str | None = product.get("PrimaryPhoto") or None

        return PartResult(
            mpn=mpn,
            manufacturer=manufacturer,
            description=description,
            package=None,
            pricing=pricing,
            stock_total=stock,
            distributors=[distributor],
            lifecycle_status=None,
            tech_specs=None,
            datasheet_url=None,
            image_url=image_url,
            similar_parts=None,
            source_provider="digikey",
            retrieved_at=datetime.now(UTC),
            match_type="exact_mpn",
        )
