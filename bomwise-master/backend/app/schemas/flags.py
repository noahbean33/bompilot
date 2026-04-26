from datetime import datetime

from pydantic import BaseModel


class PartFlagResponse(BaseModel):
    id: int
    part_result_id: int
    flag_type: str
    old_value: str | None = None
    new_value: str | None = None
    acknowledged: bool
    created_at: datetime

    model_config = {"from_attributes": True}
