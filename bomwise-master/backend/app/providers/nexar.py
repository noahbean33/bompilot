"""
Nexar Supply API adapter.

Authentication: OAuth2 client_credentials against Nexar's identity server.
Transport:      GraphQL over HTTPS via httpx.AsyncClient.

Only search_by_mpn is implemented for item 3. search_by_distributor_pn and
search_parametric raise NotImplementedError and will be wired up in later
build sequence items.
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

# Maps Nexar's seller display names (lowercased) to canonical distributor ids.
_DISTRIBUTOR_MAP: dict[str, str] = {
    "digi-key": "digikey",
    "digikey": "digikey",
    "mouser electronics": "mouser",
    "mouser": "mouser",
    "element14": "element14",
    "newark": "element14",
    "farnell": "element14",
    "arrow electronics": "arrow",
    "arrow": "arrow",
    "rs components": "rs",
    "rs": "rs",
    "avnet": "avnet",
    "future electronics": "future",
    "future": "future",
}

_TOKEN_URL = "https://identity.nexar.com/connect/token"
_GRAPHQL_URL = "https://api.nexar.com/graphql"

_MPN_QUERY = """
query SearchByMPN($q: String!, $limit: Int!) {
  supSearchMpn(q: $q, limit: $limit) {
    results {
      part {
        mpn
        manufacturer { name }
        shortDescription
        totalAvail
        bestDatasheet { url }
        similarParts { mpn }
        specs {
          attribute { name }
          value
        }
        sellers {
          company { name }
          offers {
            inventoryLevel
            prices {
              quantity
              price
              currency
            }
            clickUrl
          }
        }
      }
    }
  }
}
"""


class NexarProvider(ComponentProvider):
    PROVIDER_NAME = "nexar"
    DAILY_LIMIT = None

    def __init__(self) -> None:
        from app.core.database import settings  # avoid circular import at module level

        self._client_id = settings.nexar_client_id
        self._client_secret = settings.nexar_client_secret
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # ------------------------------------------------------------------
    # ComponentProvider interface
    # ------------------------------------------------------------------

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            has_lifecycle_status=False,
            has_tech_specs=True,
            has_datasheet_urls=True,
            has_similar_parts=True,
            has_parametric_search=True,
            distributor_coverage=[
                "digikey",
                "mouser",
                "element14",
                "arrow",
                "rs",
                "avnet",
                "future",
            ],
        )

    async def search_by_mpn(
        self,
        mpn: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        logger.debug("search_by_mpn: searching for MPN=%r qty=%d", mpn, quantity)
        try:
            token = await self._get_token()
            logger.debug("search_by_mpn: token acquired (length=%d)", len(token))
        except Exception as exc:
            logger.error("search_by_mpn: token fetch failed: %s", exc, exc_info=True)
            raise

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    _GRAPHQL_URL,
                    json={"query": _MPN_QUERY, "variables": {"q": mpn, "limit": 10}},
                    headers={"Authorization": f"Bearer {token}"},
                )
                logger.debug(
                    "search_by_mpn: GraphQL HTTP %d for MPN=%r", resp.status_code, mpn
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "search_by_mpn: HTTP error %d for MPN=%r — body: %s",
                exc.response.status_code,
                mpn,
                exc.response.text[:500],
                exc_info=True,
            )
            raise
        except Exception as exc:
            logger.error(
                "search_by_mpn: unexpected error fetching MPN=%r: %s", mpn, exc, exc_info=True
            )
            raise

        payload = resp.json()
        if "errors" in payload:
            logger.warning(
                "search_by_mpn: GraphQL errors for MPN=%r: %s", mpn, payload["errors"]
            )
        logger.debug("search_by_mpn: raw response for MPN=%r: %s", mpn, payload)
        results = self._map_mpn_response(payload)
        logger.debug("search_by_mpn: mapped %d result(s) for MPN=%r", len(results), mpn)
        return results

    async def search_by_distributor_pn(
        self,
        distributor: str,
        pn: str,
        quantity: int,
    ) -> list[PartResult]:
        raise NotImplementedError("search_by_distributor_pn not yet implemented for Nexar")

    async def search_parametric(
        self,
        params: ParametricQuery,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        raise NotImplementedError("search_parametric not yet implemented for Nexar")

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        if self._token and time.monotonic() < self._token_expiry - 60:
            return self._token
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
        self._token = payload["access_token"]
        self._token_expiry = time.monotonic() + payload.get("expires_in", 3600)
        return self._token

    # ------------------------------------------------------------------
    # Response mapping
    # ------------------------------------------------------------------

    def _map_mpn_response(self, data: dict) -> list[PartResult]:
        results = []
        for r in data.get("data", {}).get("supSearchMpn", {}).get("results", []):
            part = r.get("part")
            if part:
                results.append(self._map_part(part))
        return results

    def _map_part(self, part: dict) -> PartResult:
        distributors: list[DistributorStock] = []
        pricing: list[PriceBreak] = []

        for seller in part.get("sellers") or []:
            company_name = (seller.get("company") or {}).get("name", "")
            canonical = _DISTRIBUTOR_MAP.get(company_name.lower(), company_name.lower())

            for offer in seller.get("offers") or []:
                inv = offer.get("inventoryLevel") or 0
                distributors.append(
                    DistributorStock(distributor=canonical, stock=inv, url=offer.get("clickUrl"))
                )
                for p in offer.get("prices") or []:
                    price_val = p.get("price")
                    if price_val is not None:
                        pricing.append(
                            PriceBreak(
                                quantity=p.get("quantity", 1),
                                unit_price=float(price_val),
                                currency=p.get("currency", "USD"),
                            )
                        )

        specs_raw = part.get("specs") or []
        tech_specs: dict | None = (
            {
                s["attribute"]["name"]: s["value"]
                for s in specs_raw
                if s.get("attribute") and s.get("value")
            }
            or None
        )

        similar = part.get("similarParts") or []
        similar_mpns: list[str] | None = (
            [s["mpn"] for s in similar if s.get("mpn")] or None
        )

        datasheet_url: str | None = (part.get("bestDatasheet") or {}).get("url")

        # Nexar's GraphQL schema does not expose a part image URL via the
        # confirmed field set (see CLAUDE.md).  image_url is left null.
        return PartResult(
            mpn=part.get("mpn", ""),
            manufacturer=(part.get("manufacturer") or {}).get("name", ""),
            description=part.get("shortDescription") or None,
            package=None,
            pricing=pricing,
            stock_total=part.get("totalAvail") or 0,
            distributors=distributors,
            lifecycle_status=None,
            tech_specs=tech_specs,
            datasheet_url=datasheet_url,
            image_url=None,
            similar_parts=similar_mpns,
            source_provider="nexar",
            retrieved_at=datetime.now(UTC),
            match_type="exact_mpn",
        )
