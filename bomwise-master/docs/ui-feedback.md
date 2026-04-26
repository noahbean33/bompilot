# UI Feedback & Improvement Log

Items noted during usability testing for action in a future session.
Each item includes context so Claude Code can action it without verbal explanation.

---

## Item 7c — Variants / Distributor Offers Page

**UIF-001: Use table layout for part candidates**
Currently renders as cards. Change to a table with columns:
Distributor, Stock, MOQ, Unit Price (qty 1), Price Breaks, Buy Now.
Consistent with the BOM table style elsewhere in the app.

**UIF-002: Quantity column from CSV**
The quantity cell in the BOM table should be populated from the imported
CSV. Verify that the CSV parser extracts a quantity field (column may be
named "Qty", "Quantity", or "qty") and stores it on the bom_line.
If the column is missing from the CSV, default to 1 and show a dash in
the UI rather than blank. Confirm end-to-end: CSV import → bom_line.quantity
→ BOM table display.

---

## Item 7c — Preferences Page

**UIF-003: Currency field should be a dropdown**
Replace the free-text currency input with a dropdown. Include the following
currencies as options: USD, EUR, GBP, AUD, CAD, JPY, CNY, SGD, INR, BRL,
MXN, CHF, HKD, NZD, SEK, NOK, DKK. Apply the same change to the project
preferences currency override field.

**UIF-004: Distributors field should use checkboxes**
Replace the free-text / tag input for preferred distributors with a
checkbox list. Populate the list from GET /providers/capabilities or a
hardcoded list of known OEMSecrets distributors. Allow multiple selections.
Apply the same change to the project preferences distributor override field.

---

## BOM Table — General

**UIF-005: Trigger matching manually via button**
Add a "Match Parts" button above the BOM table. On click, POST to
/projects/{id}/match and show a loading state. Once complete, refresh
the BOM table data. If the project has existing match results, label
the button "Re-match Parts" instead. Disable the button during the
request to prevent double-submission.

**UIF-006: Clone project**
Add a "Clone Project" action on the project list and project detail pages.
Creates a new project with the same name (suffixed " (copy)"), copies all
bom_lines with their raw_fields and quantity, but does not copy match
results — the cloned project starts unmatched. Requires a new backend
endpoint: POST /projects/{id}/clone.

**UIF-007: Per-row notes**
Add a notes field to each BOM row. Stored on bom_line (requires a new
nullable text column `notes` and a migration). Editable inline in the
table. Notes are included as a column in CSV and Excel exports.

**UIF-008: Editable cells**
Allow inline editing of the following BOM table cells: QTY, REF,
datasheet link. Changes are saved via PATCH /projects/{id}/bom/{lineId}.
Show a subtle edit indicator on hover. Confirm save on blur or Enter key.

**UIF-009: Column sorting**
Add sortable column headers for REF and QTY. Clicking a header cycles
through ascending → descending → default. Sorting is client-side on
the loaded data.

**UIF-010: Default sort order**
Define a default sort that groups components by type (derived from the
REF prefix: U = ICs, C = capacitors, R = resistors, L = inductors,
D = diodes, Q = transistors, J = connectors, Y = crystals, other)
and sorts groups alphabetically by REF within each group. Add a
"Reset Order" button that restores this default sort.

**UIF-011: Summary row**
Add a fixed summary row at the bottom of the BOM table showing:
- QTY: sum of all row quantities
- Price: sum of (unit price × quantity) for all matched rows in the
  effective currency. Show "—" for unmatched rows and exclude them
  from the sum. Display the currency code next to the total.

  **UIF-012: Show "No match" status for unmatched parts**
After matching runs, bom_lines with no results should show "No match"
status (red indicator) rather than staying as "Pending" (grey). The
matching service should write match_type = "none" on failure.

**UIF-013: Passive component matching**
OEMSecrets has limited coverage of passive MPNs (Murata GRM series,
Yageo RC series). Investigate whether a keyword/value-based fallback
search (e.g. searching "100nF 0402" from the Value field) improves
match rates for passives. This is a matching service improvement, not
a UI change.

**BUG-001: Unmatched parts show "Pending" instead of "No match"**
After matching runs, bom_lines with no results should show "No match"
with a red indicator. The matching service should write match_type = "no_match"
on failure. Currently leaves status as "Pending" (grey), which is
indistinguishable from not-yet-matched.

**UIF-013: Improve passive component matching**
Current exact MPN matching fails for many passives. Implement a two-stage
fallback in the matching service:
1. If exact MPN returns no results, retry with hyphens stripped from the MPN.
2. If still no results, and Value + Footprint fields are present, extract
   the package size from the footprint name (e.g. "R_0402_1005Metric" → "0402")
   and search OEMSecrets with "{Value} {package_size}" as the keyword
   (e.g. "10k 0402"). Set match_type = "keyword" for these results.
This is a matching service change, not a UI change.

**UIF-014: Smart CSV re-import for existing projects**
When importing a CSV into a project that already has BOM lines, do not
replace all rows. Instead apply a merge strategy:
- Match incoming rows to existing bom_lines by REF
- If REF matches and Value + Footprint are identical: retain all existing
  data (match results, notes, selected_result_id, flags)
- If REF matches but Value or Footprint changed: overwrite raw fields,
  clear match_type, selected_result_id, and flags — row needs re-matching
- If REF is new: create a new bom_line
- If an existing REF is absent from the new CSV: leave it unchanged
  (do not delete — user may have added it manually). Consider a warning.
This logic belongs in the BOM import service on the backend.

**UIF-015: Part thumbnail column in BOM table**
Add an optional thumbnail column showing the part image from
part_result.image_url. Display as 40×40px with a generic component
icon as fallback. Column is hidden by default, toggled via a
"Columns" control above the table. Ensure image_url is being stored
in part_results by the OEMSecrets adapter.

**UIF-016: Column visibility toggle**
Add a "Columns" button above the BOM table that opens a dropdown
checklist of all available columns. Users can show/hide individual
columns. The visible set is persisted to localStorage so it survives
page refresh. Default visible columns: REF, Value, MPN (Raw),
Matched MPN, Manufacturer, QTY, Stock, Price, Status, Alerts, Notes.
Default hidden: Footprint, Description, Thumbnail (UIF-015).