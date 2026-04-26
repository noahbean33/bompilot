import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.part_alternatives import PartAlternative
from app.models.part_flag import PartFlag
from app.models.part_result import PartResult as PartResultRow
from app.models.project import BomLine, Project
from app.models.substitution_history import SubstitutionHistory
from app.models.user import User
from app.providers.registry import ProviderRegistry, get_registry
from app.schemas.flags import PartFlagResponse
from app.schemas.preferences import MergedPreferences, ProjectPreferencesRead, ProjectPreferencesUpdate
from app.schemas.project import (
    BomImportResponse,
    BomLinePatch,
    BomLineResponse,
    BomLineSplitResponse,
    BomLineSwapResponse,
    BomLineUpdate,
    ManualAssignRequest,
    ManualSearchRequest,
    ManualSearchResponse,
    MatchResponse,
    PartResultResponse,
    ProjectCreate,
    ProjectResponse,
)
from app.schemas.substitution import PartAlternativeResponse, SubstitutionHistoryEntry, SwapRequest
from app.services.bom import import_bom, parse_csv, split_bom_line
from app.services.freemium import get_effective_limits
from app.services.manual_search import ManualSearchService
from app.services.matching import PartMatchingService, resolve_fallback_order
from app.services.preferences import PreferencesService
from app.services.project import clone_project, create_project, delete_project, get_project, list_projects

router = APIRouter()

_MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB


def _owned_project_or_404(project_id: int, user_id: int, db: Session):
    project = get_project(db, project_id=project_id, user_id=user_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limits = get_effective_limits(current_user, db)
    if limits["max_projects"] is not None:
        project_count = db.query(Project).filter(Project.user_id == current_user.id).count()
        if project_count >= limits["max_projects"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "plan_limit_exceeded",
                    "limit": "projects",
                    "max": limits["max_projects"],
                },
            )
    return create_project(db, user_id=current_user.id, body=body)


@router.get("/", response_model=list[ProjectResponse])
def list_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_projects(db, user_id=current_user.id)


@router.get("/{project_id}", response_model=ProjectResponse)
def get(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _owned_project_or_404(project_id, current_user.id, db)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _owned_project_or_404(project_id, current_user.id, db)
    delete_project(db, project)


@router.post("/{project_id}/bom/import", response_model=BomImportResponse)
async def bom_import(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)

    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 2 MB limit",
        )

    rows = parse_csv(content)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV is empty or has no parseable rows",
        )

    limits = get_effective_limits(current_user, db)
    if limits["max_parts_per_project"] is not None and len(rows) > limits["max_parts_per_project"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "plan_limit_exceeded",
                "limit": "parts_per_project",
                "max": limits["max_parts_per_project"],
            },
        )

    count, warnings = import_bom(db, project_id=project_id, rows=rows)
    return BomImportResponse(project_id=project_id, imported=count, warnings=warnings)


@router.get("/{project_id}/bom", response_model=list[BomLineResponse])
def get_bom(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    return (
        db.query(BomLine)
        .filter(BomLine.project_id == project_id)
        .options(joinedload(BomLine.selected_result))
        .all()
    )


@router.get("/{project_id}/bom/{line_id}", response_model=BomLineResponse)
def get_bom_line(
    project_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a single BOM line by ID."""
    _owned_project_or_404(project_id, current_user.id, db)
    line = (
        db.query(BomLine)
        .filter(BomLine.id == line_id, BomLine.project_id == project_id)
        .options(joinedload(BomLine.selected_result))
        .first()
    )
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM line not found")
    return line


@router.get("/{project_id}/preferences", response_model=ProjectPreferencesRead)
def get_project_preferences(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    return PreferencesService.get_or_create_project_preferences(db, project_id=project_id)


@router.put("/{project_id}/preferences", response_model=ProjectPreferencesRead)
def update_project_preferences(
    project_id: int,
    body: ProjectPreferencesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    return PreferencesService.update_project_preferences(
        db,
        project_id=project_id,
        preferred_currency=body.preferred_currency,
        preferred_distributors=body.preferred_distributors,
    )


@router.get("/{project_id}/bom/{line_id}/results", response_model=list[PartResultResponse])
def get_bom_line_results(
    project_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    line = (
        db.query(BomLine)
        .filter(BomLine.id == line_id, BomLine.project_id == project_id)
        .first()
    )
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM line not found")
    return (
        db.query(PartResultRow)
        .filter(PartResultRow.bom_line_id == line_id)
        .order_by(PartResultRow.rank)
        .all()
    )


@router.get(
    "/{project_id}/bom/{line_id}/alternatives",
    response_model=list[PartAlternativeResponse],
)
def get_bom_line_alternatives(
    project_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    line = (
        db.query(BomLine)
        .filter(BomLine.id == line_id, BomLine.project_id == project_id)
        .first()
    )
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM line not found")
    return (
        db.query(PartAlternative)
        .filter(PartAlternative.bom_line_id == line_id)
        .order_by(PartAlternative.match_score.desc().nullslast())
        .all()
    )


@router.post(
    "/{project_id}/bom/{line_id}/swap",
    response_model=BomLineSwapResponse,
)
async def swap_bom_line(
    project_id: int,
    line_id: int,
    body: SwapRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    registry: ProviderRegistry = Depends(get_registry),
):
    _owned_project_or_404(project_id, current_user.id, db)
    line = (
        db.query(BomLine)
        .options(joinedload(BomLine.selected_result))
        .filter(BomLine.id == line_id, BomLine.project_id == project_id)
        .first()
    )
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM line not found")

    # 1. Capture from_mpn before mutation
    if line.selected_result is not None:
        from_mpn: str | None = line.selected_result.mpn
    else:
        from_mpn = line.mpn_raw

    # 2. Record substitution history + update bom_line
    db.add(SubstitutionHistory(
        bom_line_id=line_id,
        from_mpn=from_mpn,
        to_mpn=body.mpn,
        swapped_by=current_user.id,
    ))
    line.mpn_raw = body.mpn
    line.match_type = None
    line.selected_result_id = None
    db.commit()

    # 3. Fresh provider lookup — propagate errors so we can set the flag;
    #    roll back only the in-flight session state (the earlier commit stands).
    provider_error = False
    service = PartMatchingService(registry)
    try:
        await service._match_line(db, line, MergedPreferences(), raise_on_provider_error=True)
    except Exception:
        provider_error = True
        db.rollback()

    # 4. Reload with eager-loaded relationship
    updated = (
        db.query(BomLine)
        .options(joinedload(BomLine.selected_result))
        .filter(BomLine.id == line_id)
        .first()
    )
    line_resp = BomLineResponse.model_validate(updated)
    return BomLineSwapResponse(**line_resp.model_dump(), provider_error=provider_error)


@router.put("/{project_id}/bom/{line_id}", response_model=BomLineResponse)
def update_bom_line(
    project_id: int,
    line_id: int,
    body: BomLineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    line = (
        db.query(BomLine)
        .filter(BomLine.id == line_id, BomLine.project_id == project_id)
        .first()
    )
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM line not found")
    result = (
        db.query(PartResultRow)
        .filter(
            PartResultRow.id == body.selected_result_id,
            PartResultRow.bom_line_id == line_id,
        )
        .first()
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part result not found")

    previous_result_id = line.selected_result_id

    # Record substitution history whenever the selection actually changes
    if previous_result_id != body.selected_result_id:
        prev_result = (
            db.query(PartResultRow).filter(PartResultRow.id == previous_result_id).first()
            if previous_result_id is not None else None
        )
        db.add(SubstitutionHistory(
            bom_line_id=line_id,
            from_mpn=prev_result.mpn if prev_result else None,
            to_mpn=result.mpn,
            swapped_by=current_user.id,
        ))

    line.selected_result_id = body.selected_result_id
    db.commit()
    return (
        db.query(BomLine)
        .options(joinedload(BomLine.selected_result))
        .filter(BomLine.id == line_id)
        .first()
    )


@router.get(
    "/{project_id}/bom/{line_id}/history",
    response_model=list[SubstitutionHistoryEntry],
)
def get_substitution_history(
    project_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    line = (
        db.query(BomLine)
        .filter(BomLine.id == line_id, BomLine.project_id == project_id)
        .first()
    )
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM line not found")
    return (
        db.query(SubstitutionHistory)
        .filter(SubstitutionHistory.bom_line_id == line_id)
        .order_by(SubstitutionHistory.swapped_at.desc(), SubstitutionHistory.id.desc())
        .all()
    )


@router.patch("/{project_id}/bom/{line_id}", response_model=BomLineResponse)
def patch_bom_line(
    project_id: int,
    line_id: int,
    body: BomLinePatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    line = (
        db.query(BomLine)
        .filter(BomLine.id == line_id, BomLine.project_id == project_id)
        .first()
    )
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM line not found")

    updated = body.model_fields_set
    if "quantity" in updated:
        line.quantity = body.quantity
    if "reference" in updated:
        line.reference = body.reference
    if "datasheet_url" in updated:
        line.datasheet_url = body.datasheet_url
    if "notes" in updated:
        line.notes = body.notes
    if "selected_result_id" in updated:
        if body.selected_result_id is not None:
            result = (
                db.query(PartResultRow)
                .filter(
                    PartResultRow.id == body.selected_result_id,
                    PartResultRow.bom_line_id == line_id,
                )
                .first()
            )
            if result is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Part result not found"
                )
        previous_result_id = line.selected_result_id
        if body.selected_result_id is not None and previous_result_id != body.selected_result_id:
            prev_result = (
                db.query(PartResultRow).filter(PartResultRow.id == previous_result_id).first()
                if previous_result_id is not None else None
            )
            new_result_obj = db.query(PartResultRow).filter(
                PartResultRow.id == body.selected_result_id
            ).first()
            db.add(SubstitutionHistory(
                bom_line_id=line_id,
                from_mpn=prev_result.mpn if prev_result else None,
                to_mpn=new_result_obj.mpn if new_result_obj else body.selected_result_id,
                swapped_by=current_user.id,
            ))
        line.selected_result_id = body.selected_result_id

    db.commit()
    return (
        db.query(BomLine)
        .options(joinedload(BomLine.selected_result))
        .filter(BomLine.id == line_id)
        .first()
    )


@router.post("/{project_id}/bom/lock-all")
def lock_all_bom_lines(
    project_id: int,
    body: dict = {},
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    line_ids = body.get("line_ids")
    query = db.query(BomLine).filter(BomLine.project_id == project_id)
    if line_ids is not None:
        query = query.filter(BomLine.id.in_(line_ids))
    count = query.update({"locked": True}, synchronize_session="fetch")
    db.commit()
    return {"locked_count": count}


@router.post("/{project_id}/bom/unlock-all")
def unlock_all_bom_lines(
    project_id: int,
    body: dict = {},
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    line_ids = body.get("line_ids")
    query = db.query(BomLine).filter(BomLine.project_id == project_id)
    if line_ids is not None:
        query = query.filter(BomLine.id.in_(line_ids))
    count = query.update({"locked": False}, synchronize_session="fetch")
    db.commit()
    return {"unlocked_count": count}


@router.post("/{project_id}/bom/{line_id}/lock", response_model=BomLineResponse)
def lock_bom_line(
    project_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    line = (
        db.query(BomLine)
        .filter(BomLine.id == line_id, BomLine.project_id == project_id)
        .first()
    )
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM line not found")
    line.locked = True
    db.commit()
    return (
        db.query(BomLine)
        .options(joinedload(BomLine.selected_result))
        .filter(BomLine.id == line_id)
        .first()
    )


@router.post("/{project_id}/bom/{line_id}/unlock", response_model=BomLineResponse)
def unlock_bom_line(
    project_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    line = (
        db.query(BomLine)
        .filter(BomLine.id == line_id, BomLine.project_id == project_id)
        .first()
    )
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM line not found")
    line.locked = False
    db.commit()
    return (
        db.query(BomLine)
        .options(joinedload(BomLine.selected_result))
        .filter(BomLine.id == line_id)
        .first()
    )


@router.get("/{project_id}/export/manufacturer")
def export_manufacturer_bom(
    project_id: int,
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _owned_project_or_404(project_id, current_user.id, db)
    lines = (
        db.query(BomLine)
        .filter(BomLine.project_id == project_id)
        .options(joinedload(BomLine.selected_result))
        .all()
    )

    COLUMNS = [
        "Reference", "Quantity", "Value", "Footprint", "MPN",
        "Manufacturer", "Description", "Distributor", "Unit Price",
        "Currency", "Stock", "Notes",
    ]

    def build_row(line: BomLine) -> dict:
        r = line.selected_result
        return {
            "Reference": line.reference or "",
            "Quantity": line.quantity or "",
            "Value": line.value or "",
            "Footprint": line.footprint or "",
            "MPN": r.mpn if r else "",
            "Manufacturer": r.manufacturer if r else "",
            "Description": r.description if r else "",
            "Distributor": r.distributor if r else "",
            "Unit Price": r.unit_price if r and r.unit_price is not None else "",
            "Currency": "USD",
            "Stock": r.stock if r else "",
            "Notes": line.notes or "",
        }

    rows = [build_row(ln) for ln in lines]
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in project.name)

    if format == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        # UTF-8 BOM for Excel compatibility
        content = "\ufeff" + buf.getvalue()
        filename = f"{safe_name}_manufacturer_bom.csv"
        return Response(
            content=content.encode("utf-8"),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        import openpyxl
        from openpyxl.styles import Font

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "BOM"

        # Bold header row
        ws.append(COLUMNS)
        for cell in ws[1]:
            cell.font = Font(bold=True)

        for row in rows:
            ws.append([row[col] for col in COLUMNS])

        # Auto-size columns
        for col_cells in ws.columns:
            max_len = max(
                len(str(cell.value)) if cell.value is not None else 0
                for cell in col_cells
            )
            ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 2, 40)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f"{safe_name}_manufacturer_bom.xlsx"
        return Response(
            content=buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.post("/{project_id}/clone", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def clone(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = _owned_project_or_404(project_id, current_user.id, db)
    return clone_project(db, source, user_id=current_user.id)


@router.get("/{project_id}/flags", response_model=list[PartFlagResponse])
def get_project_flags(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_project_or_404(project_id, current_user.id, db)
    return (
        db.query(PartFlag)
        .join(PartResultRow, PartResultRow.id == PartFlag.part_result_id)
        .join(BomLine, BomLine.id == PartResultRow.bom_line_id)
        .filter(BomLine.project_id == project_id, PartFlag.acknowledged == False)  # noqa: E712
        .all()
    )


@router.post("/{project_id}/bom/nl-query")
async def nl_query(
    project_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Translate a plain-English query into a BOM filter expression via Claude Haiku."""
    _owned_project_or_404(project_id, current_user.id, db)

    from pydantic import BaseModel, Field

    class NLQueryRequest(BaseModel):
        query: str = Field(..., max_length=500)

    req = NLQueryRequest(**body)

    from app.services.nl_query import run_nl_query
    return await run_nl_query(req.query)


@router.post("/{project_id}/match", response_model=MatchResponse)
async def match_bom(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    registry: ProviderRegistry = Depends(get_registry),
):
    _owned_project_or_404(project_id, current_user.id, db)

    # Build plan-filtered fallback order and report skipped premium providers
    full_order = resolve_fallback_order(None)
    skipped = registry.skipped_providers(full_order, current_user.plan, current_user.trial_ends_at)
    accessible = set(registry.accessible_names(current_user.plan, current_user.trial_ends_at))
    filtered_order = [p for p in full_order if p in accessible]

    service = PartMatchingService(registry, fallback_order=filtered_order)
    result = await service.match_project(db, project_id)
    return MatchResponse(**result, skipped_providers=skipped)


# ---------------------------------------------------------------------------
# AI Assist endpoints
# ---------------------------------------------------------------------------

@router.get("/{project_id}/ai-assist/budget")
async def get_ai_assist_budget(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the current user's AI Assist monthly budget state."""
    _owned_project_or_404(project_id, current_user.id, db)
    limits = get_effective_limits(current_user, db)
    from app.services.ai_matching import get_budget_state
    return await get_budget_state(current_user.id, limits["ai_assist_monthly_lines"])


@router.post("/{project_id}/ai-assist")
async def run_ai_assist(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    registry: ProviderRegistry = Depends(get_registry),
) -> dict:
    """Run AI Assist on all eligible pending/no_match/ai_suggested lines in the project.

    Eligible lines: match_type IN (NULL, 'no_match', 'ai_suggested')
                    AND locked = False AND dnp = False.

    Returns a summary including per-status counts, lines skipped due to budget,
    and the updated budget state.
    """
    _owned_project_or_404(project_id, current_user.id, db)
    limits = get_effective_limits(current_user, db)
    budget_limit = limits["ai_assist_monthly_lines"]

    # Pre-flight budget check: if the limit is already exhausted, reject early.
    if budget_limit is not None:
        from app.services.ai_matching import _get_lines_used_this_month
        used = await _get_lines_used_this_month(current_user.id)
        if used >= budget_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "ai_assist_limit_exceeded",
                    "used": used,
                    "limit": budget_limit,
                    "message": (
                        f"Monthly AI Assist limit reached ({used}/{budget_limit} lines used). "
                        "Resets on the 1st of next month."
                    ),
                },
            )

    from app.services.ai_matching import ai_assist_project
    return await ai_assist_project(
        db=db,
        project_id=project_id,
        registry=registry,
        user_id=current_user.id,
        budget_limit=budget_limit,
    )


# ---------------------------------------------------------------------------
# AI Advisor endpoint
# ---------------------------------------------------------------------------

class AiAdvisorRequest(BaseModel):
    selected_mpns: list[str]


class AiAdvisorBudget(BaseModel):
    used: int
    limit: int | None
    remaining: int | None
    resets_at: str
    unlimited: bool


class AiAdvisorResponse(BaseModel):
    explanation: str
    recommendation: str
    reasoning: str
    cached: bool
    budget: AiAdvisorBudget
    quota_exceeded: bool = False


@router.post("/{project_id}/bom/{line_id}/ai-advisor", response_model=AiAdvisorResponse)
async def ai_advisor(
    project_id: int,
    line_id: int,
    body: AiAdvisorRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Run AI Advisor on selected part alternatives.

    Compares the selected MPNs and explains differences, recommends best option.
    Available to all users (free + paid) with separate monthly limits.
    """
    _owned_project_or_404(project_id, current_user.id, db)

    if not body.selected_mpns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one MPN must be selected",
        )

    if len(body.selected_mpns) > 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 3 parts can be selected for analysis",
        )

    # Fetch the BOM line for context
    line = (
        db.query(BomLine)
        .filter(BomLine.id == line_id, BomLine.project_id == project_id)
        .first()
    )
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM line not found")

    # Get user's AI Advisor budget limit
    limits = get_effective_limits(current_user, db)
    budget_limit = limits["ai_advisor_monthly_queries"]

    from app.services.ai_advisor import explain_parts
    return await explain_parts(
        db=db,
        mpns=body.selected_mpns,
        line=line,
        user_id=current_user.id,
        budget_limit=budget_limit,
    )


# ---------------------------------------------------------------------------
# Manual Search endpoints
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Row Splitter endpoint
# ---------------------------------------------------------------------------

@router.post("/{project_id}/bom/{line_id}/split", response_model=BomLineSplitResponse)
def split_bom_line_endpoint(
    project_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Split a BOM line with multiple designators (e.g. 'D1,D2,D3') into individual lines."""
    _owned_project_or_404(project_id, current_user.id, db)

    try:
        new_line_ids = split_bom_line(db, line_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Count total lines for this project after split
    total_lines = db.query(BomLine).filter(BomLine.project_id == project_id).count()

    return BomLineSplitResponse(
        original_id=line_id,
        new_line_ids=new_line_ids,
        total_lines=total_lines,
    )


# ---------------------------------------------------------------------------
# Manual Search endpoints
# ---------------------------------------------------------------------------

@router.post("/{project_id}/bom/{line_id}/manual-search", response_model=ManualSearchResponse)
async def manual_search(
    project_id: int,
    line_id: int,
    body: ManualSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    registry: ProviderRegistry = Depends(get_registry),
):
    """Search providers manually for components matching a keyword query."""
    _owned_project_or_404(project_id, current_user.id, db)
    service = ManualSearchService(registry)
    return await service.search(db, project_id, line_id, body)


@router.post("/{project_id}/bom/{line_id}/manual-assign")
def manual_assign(
    project_id: int,
    line_id: int,
    body: ManualAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Assign a previously returned PartResult to a BOM line.

    If assign_to_similar is True, also updates all unlocked lines in the same
    project that share the same value + footprint combination.
    """
    _owned_project_or_404(project_id, current_user.id, db)
    return ManualSearchService.assign(db, line_id, body, user_id=current_user.id)
