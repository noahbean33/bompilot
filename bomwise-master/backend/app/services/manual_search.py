"""Manual component search and assignment service."""

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.part_result import PartResult as PartResultRow
from app.models.project import BomLine
from app.models.substitution_history import SubstitutionHistory
from app.providers.registry import ProviderRegistry
from app.schemas.preferences import MergedPreferences
from app.schemas.project import (
    ManualAssignRequest,
    ManualSearchResponse,
    ManualSearchRequest,
    PartResultResponse,
)


def _part_result_to_response(pr, rank: int = 1) -> PartResultResponse:
    """Convert a transient provider PartResult to a PartResultResponse."""
    # Extract first pricing break for compatibility
    first_price = pr.pricing[0] if pr.pricing else None
    # Extract first distributor for compatibility
    first_dist = pr.distributors[0] if pr.distributors else None

    return PartResultResponse(
        id=0,  # Transient — not persisted yet
        rank=rank,
        mpn=pr.mpn,
        manufacturer=pr.manufacturer,
        description=pr.description,
        package=pr.package,
        distributor=first_dist.distributor if first_dist else None,
        unit_price=first_price.unit_price if first_price else None,
        stock=pr.stock_total,
        lifecycle_status=pr.lifecycle_status,
        tech_specs=pr.tech_specs,
        datasheet_url=pr.datasheet_url,
        image_url=pr.image_url,
        source_provider=pr.source_provider,
        match_type=pr.match_type or "manual",
        retrieved_at=pr.retrieved_at,
    )


class ManualSearchService:
    """Service for manual component search and result assignment."""

    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    async def search(
        self,
        db: Session,
        project_id: int,
        line_id: int,
        body: ManualSearchRequest,
    ) -> ManualSearchResponse:
        """Search providers for components matching the query."""
        # Verify line exists
        line = (
            db.query(BomLine)
            .filter(BomLine.id == line_id, BomLine.project_id == project_id)
            .first()
        )
        if line is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOM line not found",
            )

        # Get provider — requested or active
        if body.provider:
            provider = self.registry.get_by_name(body.provider)
            if provider is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Provider '{body.provider}' not available",
                )
        else:
            provider = self.registry.get()

        # Search by keyword
        quantity = line.quantity or 1
        preferences = MergedPreferences()

        try:
            results = await provider.search_by_keyword(
                keyword=body.query,
                quantity=quantity,
                preferences=preferences,
            )
            response_results = [
                _part_result_to_response(r, rank=i + 1)
                for i, r in enumerate(results)
            ]
            return ManualSearchResponse(
                results=response_results,
                provider_error=False,
            )
        except Exception:
            return ManualSearchResponse(
                results=[],
                provider_error=True,
            )

    @staticmethod
    def assign(
        db: Session,
        line_id: int,
        body: ManualAssignRequest,
        user_id: int,
    ) -> dict:
        """Assign a persisted PartResult to a BOM line.

        The result_id must reference an existing PartResultRow in the database
        (e.g. from a previous automatic match or a swap that stored results).
        """
        line = db.query(BomLine).filter(BomLine.id == line_id).first()
        if line is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOM line not found",
            )

        if line.locked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="BOM line is locked",
            )

        result = (
            db.query(PartResultRow)
            .filter(PartResultRow.id == body.result_id)
            .first()
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Part result not found",
            )

        # Record substitution history
        db.add(SubstitutionHistory(
            bom_line_id=line_id,
            from_mpn=line.selected_result.mpn if line.selected_result else line.mpn_raw,
            to_mpn=result.mpn,
            swapped_by=user_id,
        ))

        # Update line
        from_mpn = line.mpn_raw
        line.selected_result_id = body.result_id
        line.mpn_raw = result.mpn
        line.match_type = "manual"

        # Assign to similar lines if requested
        assigned_count = 0
        if body.assign_to_similar and line.value and line.footprint:
            similar_lines = (
                db.query(BomLine)
                .filter(
                    BomLine.id != line_id,
                    BomLine.project_id == line.project_id,
                    BomLine.value == line.value,
                    BomLine.footprint == line.footprint,
                    BomLine.locked == False,  # noqa: E712
                )
                .all()
            )
            for similar in similar_lines:
                db.add(SubstitutionHistory(
                    bom_line_id=similar.id,
                    from_mpn=similar.selected_result.mpn if similar.selected_result else similar.mpn_raw,
                    to_mpn=result.mpn,
                    swapped_by=user_id,
                ))
                similar.mpn_raw = result.mpn
                similar.match_type = "manual"
                # Find or create matching PartResult for this line
                existing_result = (
                    db.query(PartResultRow)
                    .filter(
                        PartResultRow.bom_line_id == similar.id,
                        PartResultRow.mpn == result.mpn,
                    )
                    .first()
                )
                if existing_result is None:
                    # Clone the result for this line
                    new_result = PartResultRow(
                        bom_line_id=similar.id,
                        rank=1,
                        mpn=result.mpn,
                        manufacturer=result.manufacturer,
                        description=result.description,
                        package=result.package,
                        distributor=result.distributor,
                        unit_price=result.unit_price,
                        stock=result.stock,
                        lifecycle_status=result.lifecycle_status,
                        tech_specs=result.tech_specs,
                        datasheet_url=result.datasheet_url,
                        image_url=result.image_url,
                        source_provider=result.source_provider,
                        match_type="manual",
                        retrieved_at=datetime.now(UTC),
                    )
                    db.add(new_result)
                    db.flush()
                    similar.selected_result_id = new_result.id
                else:
                    similar.selected_result_id = existing_result.id
                assigned_count += 1

        db.commit()

        return {
            "line_id": line_id,
            "assigned_mpns": result.mpn,
            "similar_assigned_count": assigned_count,
        }