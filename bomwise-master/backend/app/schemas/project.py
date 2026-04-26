from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.providers.schema import SkippedProvider


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    variant_tag: str | None = None


class ProjectResponse(BaseModel):
    id: int
    user_id: int
    name: str
    description: str | None
    variant_tag: str | None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class PartResultResponse(BaseModel):
    id: int
    rank: int
    mpn: str
    manufacturer: str
    description: str | None
    package: str | None
    distributor: str | None
    unit_price: float | None
    stock: int
    lifecycle_status: str | None
    tech_specs: dict[str, Any] | None
    datasheet_url: str | None
    image_url: str | None
    source_provider: str
    match_type: str
    retrieved_at: datetime

    model_config = {"from_attributes": True}


class BomLineResponse(BaseModel):
    id: int
    project_id: int
    reference: str | None
    value: str | None
    footprint: str | None
    description: str | None
    quantity: int | None
    mpn_raw: str | None
    raw_fields: dict[str, Any]
    match_type: str | None
    pinned: bool
    locked: bool
    notes: str | None = None
    datasheet_url: str | None = None
    matched_provider: str | None = None
    dnp: bool = False
    created_at: datetime
    selected_result: PartResultResponse | None = None

    model_config = {"from_attributes": True}


class BomLineUpdate(BaseModel):
    """Legacy full-update schema kept for the PUT endpoint."""
    selected_result_id: int


class BomLinePatch(BaseModel):
    """PATCH schema — only fields present in the request body are updated."""
    quantity: int | None = None
    reference: str | None = None
    datasheet_url: str | None = None
    notes: str | None = None
    selected_result_id: int | None = None


class BomImportResponse(BaseModel):
    project_id: int
    imported: int
    warnings: list[str] = []


class BomLineSwapResponse(BomLineResponse):
    """BomLineResponse extended with a provider_error flag for the swap endpoint."""
    provider_error: bool = False


class ManualSearchRequest(BaseModel):
    query: str
    provider: str | None = None


class ManualSearchResponse(BaseModel):
    results: list[PartResultResponse]
    provider_error: bool = False


class ManualAssignRequest(BaseModel):
    result_id: int
    assign_to_similar: bool = False


class MatchResponse(BaseModel):
    project_id: int
    total: int
    matched: int
    unmatched: int
    skipped_providers: list[SkippedProvider] = []


class BomLineSplitResponse(BaseModel):
    original_id: int
    new_line_ids: list[int]
    total_lines: int
