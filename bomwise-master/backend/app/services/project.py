from sqlalchemy.orm import Session

from app.models.project import BomLine, Project
from app.schemas.project import ProjectCreate


def create_project(db: Session, user_id: int, body: ProjectCreate) -> Project:
    project = Project(
        user_id=user_id,
        name=body.name,
        description=body.description,
        variant_tag=body.variant_tag,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session, user_id: int) -> list[Project]:
    return db.query(Project).filter(Project.user_id == user_id).all()


def get_project(db: Session, project_id: int, user_id: int) -> Project | None:
    return (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == user_id)
        .first()
    )


def delete_project(db: Session, project: Project) -> None:
    db.delete(project)
    db.commit()


def clone_project(db: Session, source: Project, user_id: int) -> Project:
    """Copy a project (name + bom_lines) without copying match results."""
    new_project = Project(
        user_id=user_id,
        name=f"{source.name} (copy)",
        description=source.description,
        variant_tag=source.variant_tag,
    )
    db.add(new_project)
    db.flush()  # assign new_project.id

    source_lines = (
        db.query(BomLine).filter(BomLine.project_id == source.id).all()
    )
    for line in source_lines:
        db.add(
            BomLine(
                project_id=new_project.id,
                reference=line.reference,
                value=line.value,
                footprint=line.footprint,
                description=line.description,
                quantity=line.quantity,
                mpn_raw=line.mpn_raw,
                raw_fields=line.raw_fields,
                notes=line.notes,
                datasheet_url=line.datasheet_url,
                # match_type and selected_result_id intentionally omitted
            )
        )

    db.commit()
    db.refresh(new_project)
    return new_project
