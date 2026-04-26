"""
FindChips provider stub — to be implemented in a future iteration.
Satisfies the ComponentProvider interface so the registry can load it.
"""

from app.providers.base import ComponentProvider
from app.providers.schema import (
    ParametricQuery,
    PartResult,
    ProviderCapabilities,
)
from app.schemas.preferences import MergedPreferences


class FindChipsProvider(ComponentProvider):
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            has_lifecycle_status=True,
            has_tech_specs=True,
            has_datasheet_urls=True,
            has_similar_parts=False,
            has_parametric_search=True,
            distributor_coverage=["digikey", "mouser", "arrow", "avnet"],
        )

    async def search_by_mpn(
        self,
        mpn: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        raise NotImplementedError("FindChips adapter not yet implemented")

    async def search_by_distributor_pn(
        self,
        distributor: str,
        pn: str,
        quantity: int,
    ) -> list[PartResult]:
        raise NotImplementedError("FindChips adapter not yet implemented")

    async def search_parametric(
        self,
        params: ParametricQuery,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        raise NotImplementedError("FindChips adapter not yet implemented")
