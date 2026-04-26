from datetime import datetime

from pydantic import BaseModel


class SubstitutionHistoryEntry(BaseModel):
    id: int
    bom_line_id: int
    from_mpn: str | None
    to_mpn: str
    swapped_at: datetime
    swapped_by: int | None

    model_config = {"from_attributes": True}


class PartAlternativeResponse(BaseModel):
    id: int
    bom_line_id: int
    mpn: str
    manufacturer: str | None
    description: str | None
    package: str | None
    distributor: str | None
    stock: int | None
    datasheet_url: str | None
    source: str
    match_score: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SwapRequest(BaseModel):
    mpn: str
    manufacturer: str | None = None
