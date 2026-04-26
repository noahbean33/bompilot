"""BOM CSV parsing and import service."""

import csv
import io

from sqlalchemy.orm import Session

from app.models.part_flag import PartFlag
from app.models.part_result import PartResult as PartResultRow
from app.models.project import BomLine

# Aliases recognised for each canonical BOM field (checked case-insensitively).
# Keys are canonical field names; values are lists of lowercased aliases that
# map to that field.  The normalisation step (strip + lowercase) is applied to
# CSV header names before lookup, so aliases here must already be lowercase.
_ALIASES: dict[str, list[str]] = {
    "reference": ["reference", "ref", "refs", "designator", "references", "refdes"],
    "value": ["value", "val", "component value"],
    "footprint": ["footprint", "package", "footprint/package", "footprint / package"],
    "description": ["description", "desc", "comment", "comments"],
    "quantity": ["quantity", "qty", "count", "amount"],
    # MPN is optional — absence of all aliases → mpn_raw = None (no error)
    "mpn_raw": [
        "mpn",
        "part_number",
        "manufacturer_pn",
        "mfr_pn",
        "part#",
        "partno",
        "mfr part #",
        "manufacturer part number",
    ],
}

# Normalised header names that trigger dnp=True when the cell is non-empty.
_DNP_HEADERS = {"dnp", "exclude from bom", "dnp?", "do not populate"}


def _normalise_header(raw: str) -> str:
    """Strip whitespace and lowercase a header name for alias lookup."""
    return raw.strip().lower()


def _build_header_map(headers: list[str]) -> dict[str, str]:
    """Return {normalised_header: original_header} for quick lookup."""
    return {_normalise_header(h): h for h in headers}


def _extract(row: dict[str, str], header_map: dict[str, str], field: str) -> str | None:
    for alias in _ALIASES[field]:
        original = header_map.get(alias)
        if original is not None:
            val = row.get(original, "").strip()
            return val if val else None
    return None


def _is_dnp_row(row: dict[str, str], header_map: dict[str, str]) -> bool:
    """Return True if any DNP-sentinel column is present and non-empty for this row."""
    for norm_key in _DNP_HEADERS:
        original = header_map.get(norm_key)
        if original is not None and row.get(original, "").strip():
            return True
    return False


def parse_csv(content: bytes) -> list[dict]:
    """Parse CSV bytes and return a list of raw row dicts."""
    text = content.decode("utf-8-sig")  # strip BOM if present
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    return [dict(row) for row in reader]


def import_bom(db: Session, project_id: int, rows: list[dict]) -> tuple[int, list[str]]:
    """
    Merge-import CSV rows into an existing project's bom_lines.

    Merge rules (matched by REF):
    - REF matches, Value + Footprint identical → retain all existing data
    - REF matches, Value or Footprint changed → overwrite raw fields,
      clear match_type / selected_result_id / flags (needs re-matching)
    - New REF → create new bom_line
    - Existing REF absent from CSV → leave unchanged; add to warnings list

    Column normalisation:
    - All header names are stripped of whitespace and lowercased before alias
      lookup, so "Qty", "QTY", " qty " all resolve to quantity.
    - MPN is optional — rows without any MPN-alias column get mpn_raw=None.
    - DNP / Exclude from BOM columns (if present) set dnp=True when non-empty.
    - The reference field may contain comma-separated designators (e.g.
      "U702,U703") — this is treated as a single opaque reference string,
      which is the correct behaviour for grouped BOM rows.

    Returns (imported_count, warnings).
    imported_count = number of rows processed from the CSV.
    """
    if not rows:
        db.commit()
        return 0, []

    headers = list(rows[0].keys())
    header_map = _build_header_map(headers)

    # Build lookup of existing lines by reference
    existing_lines: dict[str, BomLine] = {}
    for line in db.query(BomLine).filter(BomLine.project_id == project_id).all():
        if line.reference:
            existing_lines[line.reference] = line

    incoming_refs: set[str] = set()

    for row in rows:
        raw = {k: v for k, v in row.items() if v is not None}
        ref = _extract(row, header_map, "reference")
        value = _extract(row, header_map, "value")
        footprint = _extract(row, header_map, "footprint")
        description = _extract(row, header_map, "description")
        mpn_raw = _extract(row, header_map, "mpn_raw")  # None if column absent
        dnp = _is_dnp_row(row, header_map)

        qty_str = _extract(row, header_map, "quantity") or ""
        try:
            qty = int(qty_str)
        except ValueError:
            qty = 1

        if ref:
            incoming_refs.add(ref)

        if ref and ref in existing_lines:
            existing = existing_lines[ref]
            # Compare value + footprint (treating None as "")
            same_value = (existing.value or "") == (value or "")
            same_footprint = (existing.footprint or "") == (footprint or "")

            if same_value and same_footprint:
                # Identical component — only update fields that can't break matching
                existing.quantity = qty
                existing.mpn_raw = mpn_raw
                existing.description = description
                existing.dnp = dnp
                existing.raw_fields = raw
                # Retain: match_type, selected_result_id, notes, datasheet_url
            else:
                # Component changed — overwrite and clear match state
                existing.value = value
                existing.footprint = footprint
                existing.description = description
                existing.quantity = qty
                existing.mpn_raw = mpn_raw
                existing.dnp = dnp
                existing.raw_fields = raw
                # Clear match state so the line gets re-matched
                existing.match_type = None
                existing.selected_result_id = None
                # Clear flags referencing any part_results for this line
                _clear_flags_for_line(db, existing.id)
        else:
            # New reference — insert
            db.add(
                BomLine(
                    project_id=project_id,
                    reference=ref,
                    value=value,
                    footprint=footprint,
                    description=description,
                    quantity=qty,
                    mpn_raw=mpn_raw,
                    dnp=dnp,
                    raw_fields=raw,
                )
            )

    # Warn about existing REFs absent from new CSV (left unchanged)
    missing_refs = sorted(
        ref for ref in existing_lines if ref not in incoming_refs
    )
    warnings = [
        f"REF {ref!r} exists in project but was not present in the imported CSV — row retained unchanged"
        for ref in missing_refs
    ]

    db.commit()
    return len(rows), warnings


def _clear_flags_for_line(db: Session, bom_line_id: int) -> None:
    """Delete all part_flags whose part_result belongs to this bom_line."""
    result_ids = [
        r.id
        for r in db.query(PartResultRow.id)
        .filter(PartResultRow.bom_line_id == bom_line_id)
        .all()
    ]
    if result_ids:
        db.query(PartFlag).filter(PartFlag.part_result_id.in_(result_ids)).delete(
            synchronize_session="fetch"
        )


def split_bom_line(db: Session, line_id: int) -> list[int]:
    """
    Split a BOM line whose reference contains multiple designators (e.g. "D1,D2,D3")
    into individual lines, each with a single designator.

    Returns a list of the new BomLine IDs (excluding the original line which keeps
    the first designator).

    Raises ValueError if the reference has no commas (nothing to split).
    """
    line = db.query(BomLine).filter(BomLine.id == line_id).first()
    if line is None:
        raise ValueError("BOM line not found")

    if not line.reference or "," not in line.reference:
        raise ValueError("Reference has no commas — nothing to split")

    refs = [r.strip() for r in line.reference.split(",") if r.strip()]
    if len(refs) < 2:
        raise ValueError("Reference has no valid designators to split")

    # Original line keeps the first designator
    original_ref = refs[0]
    line.reference = original_ref

    new_line_ids: list[int] = []

    for ref in refs[1:]:
        new_line = BomLine(
            project_id=line.project_id,
            reference=ref,
            value=line.value,
            footprint=line.footprint,
            description=line.description,
            quantity=line.quantity,
            mpn_raw=line.mpn_raw,
            dnp=line.dnp,
            raw_fields=dict(line.raw_fields) if line.raw_fields else {},
            # These stay None — new lines need re-matching
            match_type=None,
            selected_result_id=None,
            pinned=False,
            locked=False,
        )
        db.add(new_line)
        db.flush()
        new_line_ids.append(new_line.id)

    db.commit()
    return new_line_ids
