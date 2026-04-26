from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.part_flag import PartFlag
from app.models.part_result import PartResult as PartResultRow
from app.models.project import BomLine
from app.models.user import User
from app.schemas.flags import PartFlagResponse

router = APIRouter()


@router.post("/{flag_id}/acknowledge", response_model=PartFlagResponse)
def acknowledge_flag(
    flag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    flag = db.query(PartFlag).filter(PartFlag.id == flag_id).first()
    if flag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flag not found")

    # Verify ownership: flag → part_result → bom_line → project → user
    part_result = db.query(PartResultRow).filter(PartResultRow.id == flag.part_result_id).first()
    bom_line = db.query(BomLine).filter(BomLine.id == part_result.bom_line_id).first()
    if bom_line is None or bom_line.project is None or bom_line.project.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flag not found")

    flag.acknowledged = True
    db.commit()
    db.refresh(flag)
    return flag
