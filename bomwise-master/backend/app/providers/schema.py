from datetime import datetime

from pydantic import BaseModel


class PriceBreak(BaseModel):
    quantity: int
    unit_price: float
    currency: str


class DistributorStock(BaseModel):
    distributor: str  # "digikey", "mouser", "element14", etc.
    stock: int
    moq: int | None = None  # minimum order quantity (populated by providers that supply it)
    url: str | None  # direct product page link


class PartResult(BaseModel):
    mpn: str
    manufacturer: str
    description: str | None
    package: str | None

    # Pricing — always a list of quantity breaks
    pricing: list[PriceBreak]

    # Stock
    stock_total: int
    distributors: list[DistributorStock]

    # Optional fields — None when provider does not supply them
    lifecycle_status: str | None  # "active", "nrnd", "eol", None
    tech_specs: dict | None  # {"voltage": "3.3V", "package": "SOIC-8"}
    datasheet_url: str | None
    image_url: str | None = None  # product/part image; populated when provider returns one
    similar_parts: list[str] | None  # list of MPNs

    # Metadata
    source_provider: str  # "nexar", "findchips", "digikey_mouser"
    retrieved_at: datetime
    match_type: str  # "exact_mpn", "distributor_pn", "parametric", "keyword"


class ProviderCapabilities(BaseModel):
    has_lifecycle_status: bool
    has_tech_specs: bool
    has_datasheet_urls: bool
    has_similar_parts: bool
    has_parametric_search: bool
    distributor_coverage: list[str]


class ParametricQuery(BaseModel):
    """Parameters for component specification search. Fully used in item 5."""

    category: str | None = None
    parameters: dict[str, str] = {}
    limit: int = 20


class SkippedProvider(BaseModel):
    """A provider that was excluded from a query due to plan restrictions."""

    name: str
    reason: str  # e.g. "premium_plan_required"
