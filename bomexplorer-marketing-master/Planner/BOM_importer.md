---

# BOM IMPORTER ENHANCEMENT — PROMPT FOR AI CODING AGENT

## CONTEXT

BOMExplorer marketing site claims: "Drag-and-drop CSV import with intelligent parsing. Supports KiCad Symbol Fields Table, Altium BOM exports, and generic formats. Auto-detects column headers (Refs, RefDes, Designator, Qty, MPN, Value)."

Audit revealed:
- ❌ **Drag-and-drop**: NOT implemented — only `<input type="file">` button exists
- ✓ **Alias system**: 20+ aliases for 6 canonical fields — functional but limited
- ✓ **Format support**: Works for KiCad/Altium via aliases, but no explicit format detection

## OBJECTIVE

1. **Implement drag-and-drop** in frontend to match marketing claim
2. **Expand header aliases** to cover additional EDA/CAD formats
3. **Add explicit format auto-detection** with feedback to user
4. **Add sample test files** for each supported format

---

## TASKS

### TASK 1: Add Drag-and-Drop to Frontend
**File**: `frontend/src/components/CsvImport.tsx`

**Actions**:
- Wrap existing upload UI in a dropzone container
- Implement native HTML5 drag-and-drop (`onDragOver`, `onDrop`, `onDragLeave`)
- Visual feedback: dashed border highlight on drag-over, drop animation
- Maintain existing click-to-browse as fallback
- Accept types: `.csv`, `.tsv`, `.xlsx` (if expanding later)
- Show filename + file size on selection
- Handle error states (wrong file type, too large)

**UX states**:
- Idle: "Drop BOM CSV here or click to browse"
- Dragging-over: highlight border + icon
- Processing: spinner + "Importing..."
- Success: green checkmark + count
- Error: red message + retry button

---

### TASK 2: Expand Header Alias Coverage
**File**: `backend/app/services/bom.py` — `_ALIASES` dict

**Current aliases cover**: `reference, ref, refs, designator, refdes`, `value, val`, `footprint, package`, `description, desc`, `quantity, qty`, `mpn, part_number, manufacturer_pn, mfr_pn, part#`, and DNP headers.

**Add these new aliases**:

```python
_ALIASES: dict[str, list[str]] = {
    "reference": [
        # existing
        "reference", "ref", "refs", "designator", "references", "refdes",
        # KiCad SFT additions
        "ref_des", "designators",
        # Altium additions
        "comment", "designator", "item",
        # EasyEDA
        "designator", "item_name",
        # OrCAD/Allegro
        "reference", "ref_des",
        # Fusion 360
        "designator", "component",
    ],
    "value": [
        # existing
        "value", "val", "component value",
        # Altium
        "comment", "description",
        # KiCad
        "value",
        # EasyEDA
        "value", "lcsc",
    ],
    "footprint": [
        # existing
        "footprint", "package", "footprint/package", "footprint / package",
        # Altium
        "footprint", "pcb footprint", "pattern",
        # KiCad
        "footprint",
        # EasyEDA
        "package", "footprint",
        # OrCAD
        "pcb_footprint",
    ],
    "description": [
        # existing
        "description", "desc", "comment", "comments",
        # Altium
        "description", "component_link",
        # KiCad
        "description",
    ],
    "quantity": [
        # existing
        "quantity", "qty", "count", "amount",
        # Altium
        "quantity", "qty",
        # OrCAD
        "quantity",
        # EasyEDA
        "quantity",
    ],
    "mpn_raw": [
        # existing
        "mpn", "part_number", "manufacturer_pn", "mfr_pn", "part#", "partno",
        "mfr part #", "manufacturer part number",
        # Altium
        "manufacturer part number", "part_number", "supplier_part_number",
        # OrCAD
        "manufacturer_pn",
        # EasyEDA
        "lcsc part #", "lcsc", "lcsc_part#",
        # Generic
        "part_number", "p/n", "pn",
    ],
}
```

**Also add LCSC-specific detection** (for JLCPCB/JLCPCM workflows since EasyEDA is very common in maker/hobbyist space).

---

### TASK 3: Add Format Auto-Detection + User Feedback
**File**: `backend/app/services/bom.py`

**Actions**:
- Create `_detect_format(headers: list[str]) -> str` function
- Return one of: `"kicad_sft"`, `"altium"`, `"easyeda"`, `"orcad"`, `"generic"`, `"unknown"`
- Detection logic: check header combinations unique to each format
  - KiCad SFT: has "Footprint" + "Value" + "Reference" (KiCad exports "Footprint" capitalized, often has "Datasheet")
  - Altium: has "Comment" + "Designator" + "Description" (Altium uses "Comment" for value, not "Value")
  - EasyEDA/JLCPCB: has "LCSC Part#" or "Manufacturer Part" columns
  - OrCAD: has "Reference" + "PCB Footprint"
- Return format string in `BomImportResponse`
- Frontend displays: "Detected format: KiCad Symbol Fields Table ✓"

---

### TASK 4: Update API Response Schema
**File**: `backend/app/schemas/project.py`

**Actions**:
- Add `detected_format: str | None` to `BomImportResponse`
- Add `columns_found: dict[str, str | None]` — shows which canonical fields were mapped

Example response:
```json
{
  "project_id": 1,
  "imported": 42,
  "warnings": [],
  "detected_format": "kicad_sft",
  "columns_found": {
    "reference": "Reference",
    "value": "Value",
    "footprint": "Footprint",
    "description": "Description",
    "quantity": null,
    "mpn_raw": "LCSC Part#"
  }
}
```

---

### TASK 5: Add Sample Test Files
**Directory**: `backend/tests/fixtures/`

Create test CSV files:

| File | Format | Headers |
|------|--------|---------|
| `kicad_sft_sample.csv` | KiCad Symbol Fields Table | Reference, Value, Footprint, Datasheet, Description |
| `altium_bom_sample.csv` | Altium BOM | Comment, Designator, Footprint, Description, Quantity, Manufacturer Part Number |
| `easyeda_sample.csv` | EasyEDA / JLCPCB | Designator, Value, Footprint, LCSC Part#, Quantity |
| `generic_sample.csv` | Generic | Ref, MPN, Qty, Description |

Update `backend/tests/test_matching.py` or create `backend/tests/test_bom_import.py` with tests that:
- Load each fixture
- Verify correct row count
- Verify header detection for each format
- Verify `_detect_format()` returns correct format

---

### TASK 6: Update Marketing Claim
Once Task 1 is done, the claim "Drag-and-drop CSV import" becomes truthful. Until then, consider updating to "Click or drag-and-drop CSV import".

---

## PRIORITY ORDER

1. **TASK 1** (drag-and-drop) — highest priority, false marketing claim
2. **TASK 2** (expand aliases) — broadens format compatibility
3. **TASK 5** (test fixtures) — validates Tasks 1-2
4. **TASK 3** (format detection) — UX enhancement
5. **TASK 4** (response schema) — supports Task 3

---

## ACCEPTANCE CRITERIA

- [ ] User can drag CSV file onto import area and trigger upload
- [ ] Alias system recognizes headers from KiCad, Altium, EasyEDA, OrCAD
- [ ] `_detect_format()` correctly identifies at least KiCad + Altium
- [ ] API returns `detected_format` in import response
- [ ] Test fixtures exist for all 4 formats and pass
- [ ] Marketing claim "drag-and-drop" is now truthful