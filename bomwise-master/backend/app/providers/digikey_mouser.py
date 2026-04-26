"""
DigiKey + Mouser combined provider stub — to be implemented in a future iteration.
Satisfies the ComponentProvider interface so the registry can load it.
"""

from app.providers.base import ComponentProvider
from app.providers.schema import (
    ParametricQuery,
    PartResult,
    ProviderCapabilities,
)
from app.schemas.preferences import MergedPreferences


class DigiKeyMouserProvider(ComponentProvider):
    """Combines DigiKey v4 and Mouser APIs directly. No aggregator."""

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            has_lifecycle_status=False,
            has_tech_specs=False,
            has_datasheet_urls=True,
            has_similar_parts=False,
            has_parametric_search=False,
            distributor_coverage=["digikey", "mouser"],
        )

    async def search_by_mpn(
        self,
        mpn: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        raise NotImplementedError("DigiKey+Mouser adapter not yet implemented")

    async def search_by_distributor_pn(
        self,
        distributor: str,
        pn: str,
        quantity: int,
    ) -> list[PartResult]:
        raise NotImplementedError("DigiKey+Mouser adapter not yet implemented")

    async def search_parametric(
        self,
        params: ParametricQuery,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        raise NotImplementedError("DigiKey+Mouser adapter not yet implemented")
