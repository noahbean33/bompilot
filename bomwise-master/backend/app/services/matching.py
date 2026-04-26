"""
PartMatchingService — applies the matching hierarchy for BOM lines.

Matching hierarchy (applied per provider in the fallback chain):
  1. Exact MPN          → provider.search_by_mpn(mpn)
  1b. Hyphen-stripped   → provider.search_by_mpn(mpn.replace("-", ""))
  1c. Footprint MPN     → provider.search_by_mpn(extract_mpn_from_footprint(footprint))
                         (extracts JST-style MPNs like SM06B-SHLS-TF from KiCad footprints)
  2. Keyword fallback   → provider.search_by_keyword("{value} {package}")
     (only when Value + Footprint fields are present and package can be extracted)
  3. Distributor PN     — stubbed
  4. Parametric         — stubbed

Provider fallback chain:
  Controlled by PROVIDER_FALLBACK_ORDER (comma-separated list of provider names).
  If not set, falls back to a single-item chain using COMPONENT_PROVIDER.
  Providers that are not registered (missing credentials at startup) are skipped
  with a warning log.  The first provider that returns any results wins; its name
  is stored in bom_lines.matched_provider.
"""

import logging
import re

from sqlalchemy.orm import Session

from app.models.part_alternatives import PartAlternative
from app.models.part_result import PartResult as PartResultRow
from app.models.project import BomLine
from app.providers.base import ComponentProvider
from app.providers.registry import ProviderRegistry
from app.providers.schema import PartResult as ProviderResult, PriceBreak
from app.schemas.preferences import MergedPreferences

logger = logging.getLogger(__name__)

# Matches a 4-digit EIA imperial package code (0402, 0805, 1206, etc.).
# Use digit-boundary lookarounds instead of \b because footprints use '_'
# as separator (e.g. "R_0402_1005Metric") and \b does not fire between _ and digit.
_PACKAGE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")

# ---------------------------------------------------------------------------
# Unmatchable-value skip list
# ---------------------------------------------------------------------------
# Values in this set are clearly schematic primitives or assembly instructions —
# not real MPNs — and should be set to no_match immediately without querying
# any provider.  All comparison is case-insensitive; prefixes are matched with
# str.startswith() after lowercasing.
#
# To extend at runtime (e.g. from a DB setting), replace or extend this set
# before constructing PartMatchingService.

UNMATCHABLE_EXACT: frozenset[str] = frozenset({
    # Generic placeholders
    "dnp", "dnf", "dni", "do not fit", "do not populate", "do not install",
    "not fitted", "not populated", "np", "n/a", "tbd", "unknown",
    # Mechanical / assembly
    "testpoint", "test_point", "tp", "mountinghole", "mounting_hole",
    "fiducial", "fiducial_1", "fiducial_2",
    # Generic passives without MPN context
    "r", "c", "l", "d", "q", "u", "j", "sw",
    # Common schematic primitives
    "led", "diode", "resistor", "capacitor", "inductor", "transistor",
    "mosfet", "crystal", "fuse", "relay", "switch",
    # Logos / artwork
    "logo", "artwork",
})

# Value prefixes (lowercased) that indicate unmatchable generic parts.
# Any value whose lowercase form starts with one of these is checked against
# the footprint — if the footprint contains a manufacturer part number pattern,
# we allow it through rather than skipping.
UNMATCHABLE_PREFIXES: tuple[str, ...] = (
    "conn_",        # KiCad connector symbols: Conn_01x02, Conn_02x05, …
    "crystal_gnd",  # KiCad crystal with GND pads: Crystal_GND24, …
    "testpoint",    # duplicate prefix guard
    "mountinghole", # duplicate prefix guard
    "fiducial",     # duplicate prefix guard
)

# Regex patterns that indicate a footprint carries a real manufacturer part number.
# These signal that the line is worth querying even if the value looks generic.
_FOOTPRINT_HAS_MPN_RE = re.compile(
    r"""
    # Standard JST-style connector MPNs:  SM06B-SHLS-TF, SM03B-GHS-TB, etc.
    (?:SM\d{2}[A-Z]?-[\w-]+)
    # Or any token that looks like an alphanumeric part number with hyphens/underscores
    |[A-Z]{2,5}[-_]?\d{2,5}[A-Z]*[-_]?\d*[A-Z]*
    # Crystal/oscillator metric sizes with pin count: 3225-4Pin, 2520-4Pin, 5032-4Pin
    |\d{4}[-_]\d+[Pp]in
    """,
    re.VERBOSE,
)


# Regex to extract the MPN-like token from a KiCad footprint string.
# KiCad footprints follow pattern: Library_Name:FootprintName_Details
# e.g., "Connector_JST:JST_SHL_SM06B-SHLS-TF_1x06-1MP_P1.00mm_Horizontal"
# We want to extract "SM06B-SHLS-TF" or similar MPN tokens.
_FOOTPRINT_MPN_EXTRACT_RE = re.compile(
    r"""
    # JST-style: SM06B-SHLS-TF, SM03B-GHS-TB, etc.
    (?P<jst>SM\d{2}[A-Z]?-[A-Z]+(?:-[A-Z]+)*)
    # XKB-style connector: U262-16XN-4BVC11, U262-16XN-4BVC33
    |(?P<xkb>U\d{3}-[\w-]+)
    # Epson oscillator style: SG followed by exactly 3 digits (BEFORE generic)
    |(?P<epson>SG\d{3})(?=[-_\s]|$)
    # Generic manufacturer part number: 2+ letters, digits, optional hyphens/underscores
    # Must be 5+ chars to avoid matching generic tokens like "R_0402"
    |(?P<generic>[A-Z]{2,5}[-_]?[\d]{2,5}[A-Z]*(?:[-_][\w]+)*)
    """,
    re.VERBOSE,
)


def _footprint_has_mpn_pattern(footprint: str | None) -> bool:
    """Return True if the footprint string appears to contain a manufacturer MPN."""
    if not footprint:
        return False
    return bool(_FOOTPRINT_HAS_MPN_RE.search(footprint))


def extract_mpn_from_footprint(footprint: str | None) -> str | None:
    """Try to extract a manufacturer part number from a KiCad footprint string.

    Examples:
        "Connector_JST:JST_SHL_SM06B-SHLS-TF_1x06-1MP_P1.00mm_Horizontal" → "SM06B-SHLS-TF"
        "Connector_JST:JST_GH_SM03B-GHS-TB_1x03-1MP_P1.25mm_Horizontal" → "SM03B-GHS-TB"
        "Connector_USB:USB_C_Receptacle_XKB_U262-16XN-4BVC11" → "U262-16XN-4BVC11"
        "Oscillator_SMD_SeikoEpson_SG210-4Pin_2.5x2.0mm" → "SG210"
    """
    if not footprint:
        return None
    m = _FOOTPRINT_MPN_EXTRACT_RE.search(footprint)
    if m:
        # Return first matching group in priority order (epson before generic
        # to prevent "SG210-4Pin_2" from being returned instead of "SG210")
        return (
            m.group("jst")
            or m.group("xkb")
            or m.group("epson")
            or m.group("generic")
        )
    return None


def is_unmatchable(value: str | None, footprint: str | None = None) -> bool:
    """Return True if *value* is a known-unmatchable schematic primitive.

    When *footprint* is provided and contains a manufacturer part-number pattern
    (e.g. JST connector codes), the check is relaxed so the line can still be
    queried via keyword/footprint-based search.
    """
    if not value:
        return False
    v = value.strip().lower()
    if v in UNMATCHABLE_EXACT:
        return True
    is_prefix_match = any(v.startswith(prefix) for prefix in UNMATCHABLE_PREFIXES)
    if not is_prefix_match:
        return False
    # Connector and crystal symbols may still be real parts if the footprint
    # carries a manufacturer MPN (e.g. JST SHL/GH series, crystal packages).
    if _footprint_has_mpn_pattern(footprint):
        return False
    return True


def resolve_fallback_order(fallback_order: list[str] | None) -> list[str]:
    """Return the provider fallback chain.

    Priority:
    1. Explicit ``fallback_order`` argument (used in tests and plan-filtering).
    2. PROVIDER_FALLBACK_ORDER env/setting (comma-separated).
    3. COMPONENT_PROVIDER env/setting (single provider).
    """
    if fallback_order is not None:
        return fallback_order
    from app.core.database import settings  # avoid circular import at module level

    order_str = (settings.provider_fallback_order or "").strip()
    if order_str:
        return [p.strip() for p in order_str.split(",") if p.strip()]
    return [settings.component_provider]


class PartMatchingService:
    def __init__(
        self,
        registry: ProviderRegistry,
        fallback_order: list[str] | None = None,
    ) -> None:
        self._registry = registry
        # Resolve at construction time; tests may pass an explicit list.
        chain = resolve_fallback_order(fallback_order)
        # If none of the configured providers are registered in this specific
        # registry (e.g. a test registry with a "mock" provider), fall back to
        # whatever is currently active.  This keeps existing tests working
        # without requiring every call site to specify fallback_order explicitly.
        if (
            registry._active is not None
            and all(registry.get_by_name(n) is None for n in chain)
        ):
            chain = [registry._active]
        self._fallback_order: list[str] = chain

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def match_project(
        self,
        db: Session,
        project_id: int,
        preferences: MergedPreferences | None = None,
    ) -> dict:
        """Match every BOM line in a project.  Returns a summary dict."""
        if preferences is None:
            preferences = MergedPreferences()

        lines: list[BomLine] = (
            db.query(BomLine)
            .filter(BomLine.project_id == project_id, BomLine.locked == False)  # noqa: E712
            .all()
        )

        matched = 0
        for line in lines:
            ok = await self._match_line(db, line, preferences)
            if ok:
                matched += 1

        return {
            "project_id": project_id,
            "total": len(lines),
            "matched": matched,
            "unmatched": len(lines) - matched,
        }

    # ------------------------------------------------------------------
    # Internal: matching hierarchy
    # ------------------------------------------------------------------

    async def _match_line(
        self,
        db: Session,
        line: BomLine,
        preferences: MergedPreferences,
        raise_on_provider_error: bool = False,
    ) -> bool:
        """Run the hierarchy for a single line.  Returns True if matched.

        When raise_on_provider_error=True, provider exceptions propagate instead
        of being silently treated as no-results (used by the swap endpoint).
        """
        # Short-circuit: schematic primitives and assembly notes are never
        # real MPNs — skip provider lookup and mark no_match immediately.
        # BUT: if the footprint carries an MPN pattern (e.g. JST connector
        # codes), allow it through for keyword-based matching.
        if is_unmatchable(line.value, line.footprint) and not line.mpn_raw:
            line.match_type = "no_match"
            line.matched_provider = None
            line.selected_result_id = None
            db.commit()
            logger.debug("_match_line: skipping unmatchable value %r for line %d", line.value, line.id)
            return False

        # Null out the FK before deleting part_results to avoid a FK violation
        # (bom_lines.selected_result_id → part_results.id).
        line.selected_result_id = None
        db.flush()

        # Wipe any stale results from a previous run
        db.query(PartResultRow).filter(PartResultRow.bom_line_id == line.id).delete(
            synchronize_session="fetch"
        )

        results: list[ProviderResult] = []
        attempted = False  # did we actually issue at least one provider query?
        winning_provider: str | None = None

        for provider_name in self._fallback_order:
            provider = self._registry.get_by_name(provider_name)
            if provider is None:
                logger.warning(
                    "_match_line: provider %r not registered — skipping", provider_name
                )
                continue

            prov_results, prov_attempted = await self._try_provider(
                provider, line, preferences, raise_on_provider_error
            )
            if prov_attempted:
                attempted = True
            if prov_results:
                results = prov_results
                winning_provider = provider_name
                break  # first provider with results wins

        if not results:
            # Distinguish between "never attempted" (no MPN, no value/footprint)
            # and "tried but the provider(s) returned nothing".
            line.match_type = "no_match" if attempted else None
            line.matched_provider = None
            line.selected_result_id = None
            db.commit()
            return False

        # Write all ranked candidates
        db_rows: list[PartResultRow] = [
            _to_db_row(r, line.id, rank, line.quantity or 1)
            for rank, r in enumerate(results, start=1)
        ]
        db.add_all(db_rows)
        db.flush()  # populate .id on each row

        # Promote the top-ranked result
        line.match_type = results[0].match_type
        line.matched_provider = winning_provider
        line.selected_result_id = db_rows[0].id

        # Populate part_alternatives with remaining candidates (rank 2+)
        db.query(PartAlternative).filter(
            PartAlternative.bom_line_id == line.id
        ).delete(synchronize_session="fetch")
        for alt_result in results[1:]:
            best_dist = (
                max(alt_result.distributors, key=lambda d: d.stock)
                if alt_result.distributors
                else None
            )
            db.add(PartAlternative(
                bom_line_id=line.id,
                mpn=alt_result.mpn,
                manufacturer=alt_result.manufacturer,
                description=alt_result.description,
                package=alt_result.package,
                distributor=best_dist.distributor if best_dist else None,
                stock=alt_result.stock_total,
                datasheet_url=alt_result.datasheet_url,
                source=alt_result.source_provider,
                match_score=None,
            ))

        db.commit()
        return True

    async def _try_provider(
        self,
        provider: ComponentProvider,
        line: BomLine,
        preferences: MergedPreferences,
        raise_on_provider_error: bool,
    ) -> tuple[list[ProviderResult], bool]:
        """Run the MPN → hyphen-stripped → keyword hierarchy for one provider.

        Returns ``(results, attempted)`` where *attempted* is True if at least
        one query was issued.
        """
        results: list[ProviderResult] = []
        attempted = False

        # 1. Exact MPN
        if line.mpn_raw and line.mpn_raw.strip():
            attempted = True
            mpn = line.mpn_raw.strip()
            try:
                results = await provider.search_by_mpn(
                    mpn,
                    line.quantity or 1,
                    preferences,
                )
            except NotImplementedError:
                results = []
            except Exception:
                if raise_on_provider_error:
                    raise
                results = []

            # 1b. Hyphen-stripped retry
            if not results and "-" in mpn:
                stripped = mpn.replace("-", "")
                try:
                    results = await provider.search_by_mpn(
                        stripped,
                        line.quantity or 1,
                        preferences,
                    )
                except NotImplementedError:
                    results = []
                except Exception:
                    if raise_on_provider_error:
                        raise
                    results = []

        # 1c. Footprint-extracted MPN — if the footprint contains a manufacturer
        #     part number (e.g. JST connector codes), try that as an MPN.
        #     Skip pure package codes (LQFP48, SOIC-8, etc.) that match the
        #     generic MPN regex but are not real manufacturer part numbers.
        if not results and line.footprint:
            footprint_mpn = extract_mpn_from_footprint(line.footprint)
            if footprint_mpn and not _is_package_code(footprint_mpn):
                attempted = True
                try:
                    results = await provider.search_by_mpn(
                        footprint_mpn,
                        line.quantity or 1,
                        preferences,
                    )
                except NotImplementedError:
                    results = []
                except Exception:
                    if raise_on_provider_error:
                        raise
                    results = []
                # Also try hyphen-stripped variant
                if not results and "-" in footprint_mpn:
                    stripped = footprint_mpn.replace("-", "")
                    try:
                        results = await provider.search_by_mpn(
                            stripped,
                            line.quantity or 1,
                            preferences,
                        )
                    except NotImplementedError:
                        results = []
                    except Exception:
                        if raise_on_provider_error:
                            raise
                        results = []

        # 2. Keyword fallback — value + package extracted from footprint
        if not results and line.value and line.footprint:
            package = _extract_package(line.footprint)
            if package:
                attempted = True
                keyword = f"{line.value.strip()} {package}"
                try:
                    results = await provider.search_by_keyword(
                        keyword,
                        line.quantity or 1,
                        preferences,
                    )
                except NotImplementedError:
                    results = []
                except Exception:
                    if raise_on_provider_error:
                        raise
                    results = []

        # 3. Distributor PN — not yet implemented
        # 4. Parametric     — not yet implemented

        return results, attempted


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _best_unit_price(pricing: list[PriceBreak], quantity: int) -> float | None:
    """Return the unit price for the best applicable price break."""
    if not pricing:
        return None
    applicable = [p for p in pricing if p.quantity <= quantity]
    pool = applicable if applicable else pricing
    return min(pool, key=lambda p: p.unit_price).unit_price


# Regex for standard IC package footprints (SOT, SOIC, TSSOP, QFN, DFN, BGA, etc.)
# Matches patterns like: SOT-23, SOT-23-6, TSOT-23-6, SOIC-8, TSSOP-20, QFN-16, DFN-10, BGA-256
_IC_PACKAGE_RE = re.compile(
    r"(?:^|[,;\s_:])"                         # word boundary (prefix)
    r"("
    r"(?:T?)SOT-\d+(?:-\d+)?"                 # SOT-23, SOT-23-6, TSOT-23-6
    r"|(?:T?)SSOP-\d+"                        # SSOP-16, TSSOP-20
    r"|(?:PD|MS|HS)OP-\d+"                    # MSOP-8, SOP-16
    r"|SOIC-\d+"                              # SOIC-8, SOIC-16
    r"|QFN-\d+"                               # QFN-16, QFN-32
    r"|DFN-\d+"                               # DFN-10, DFN-8
    r"|WLCSP-\d+"                             # WLCSP-6
    r"|BGA-\d+"                               # BGA-256
    r"|LQFP-\d+"                              # LQFP-48
    r"|TQFP-\d+"                              # TQFP-32
    r"|VQFN-\d+"                              # VQFN-24
    r")",
    re.IGNORECASE,
)


# Regex for crystal/oscillator metric package sizes (mm): 3225, 2520, 5032, 2016
_CRYSTAL_PKG_RE = re.compile(r"(\d{4})(?:[-_]?4Pin|[Pp]in)?", re.DOTALL)

# Known 4-digit codes that are NOT package sizes
_PKG_BLACKLIST = {"1x06", "1x03", "1x02", "2x05", "2x10", "2x12", "2x20"}


# Regex for manufacturer + series patterns in footprints (e.g., Ohmite LVK12, SeikoEpson SG210)
_FOOTPRINT_MFR_SERIES_RE = re.compile(
    r"""
    (?P<mfr>Ohmite|SeikoEpson|Vishay|Yageo|Murata|TDK|AVX|Kemet|XKB)
    [_\s]*
    (?P<series>[A-Z]?\d{2,6}[A-Z]*\d*)    # optional letter, 2-6 digits, optional suffix
    |
    (?P<mfr2>Ohmite|SeikoEpson|Vishay|Yageo|Murata|TDK|AVX|Kemet)
    [_\s]*
    (?P<series2>[A-Z]{2,5}\d{2,5}[A-Z]*)   # letter-start pattern
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _extract_mfr_series(footprint: str | None) -> tuple[str | None, str | None]:
    """Extract manufacturer and series from footprint string.

    Examples:
        "Resistor_SMD:R_Shunt_Ohmite_LVK12" → ("Ohmite", "LVK12")
        "Oscillator_SMD_SeikoEpson_SG210" → ("SeikoEpson", "SG210")
    """
    if not footprint:
        return None, None
    m = _FOOTPRINT_MFR_SERIES_RE.search(footprint)
    if m:
        # Return from whichever group pair matched
        mfr = m.group("mfr") or m.group("mfr2")
        series = m.group("series") or m.group("series2")
        return mfr, series
    return None, None


def _is_package_code(token: str) -> bool:
    """Return True if token is purely a package identifier, not an MPN."""
    if _IC_PACKAGE_RE.search(token):
        return True
    # 4-digit codes that look like EIA packages (0402, 0805, 1206, 2520, 3225, etc.)
    if re.fullmatch(r"\d{4}", token):
        return True
    return False


def _extract_package(footprint: str) -> str | None:
    """Extract a package identifier from a footprint string.

    Recognises:
      - 4-digit EIA codes (0402, 0805, 1206) via ``_PACKAGE_RE``
      - IC packages: SOT-23, SOT-23-6, TSOT-23-6, SOIC-8, TSSOP-20,
        QFN-16, DFN-10, BGA-256, WLCSP-6, etc.
      - Crystal/oscillator metric sizes: 3225, 2520, 5032, 2016

    Examples:
      - 'R_0402_1005Metric' → '0402'
      - 'C_0805' → '0805'
      - 'Package_TO_SOT_SMD:TSOT-23-6' → 'TSOT-23-6'
      - 'Crystal_SMD_3225-4Pin_3.2x2.5mm' → '3225'
      - 'Oscillator_SMD_SeikoEpson_SG210-4Pin_2.5x2.0mm' → '2520' (from 2.5x2.0 → 2520)
    """
    # First try EIA 4-digit code
    m = _PACKAGE_RE.search(footprint)
    if m:
        code = m.group(1)
        if code not in _PKG_BLACKLIST:
            return code

    # Then try IC package patterns
    m = _IC_PACKAGE_RE.search(footprint)
    if m:
        return m.group(1)

    # Crystal/oscillator metric sizes — look for 3225, 2520, 5032, 2016
    # These appear in crystal footprints like "Crystal_SMD_3225-4Pin_3.2x2.5mm"
    for code in ("3225", "2520", "5032", "2016", "3215"):
        if code in footprint:
            return code

    # Parse decimal-millimetre dimensions (e.g. "2.5x2.0mm" → "2520")
    # Used by oscillator footprints like "Oscillator_SMD_SeikoEpson_SG210-4Pin_2.5x2.0mm"
    dim_match = re.search(r"(\d+)\.(\d+)x(\d+)\.(\d+)mm", footprint)
    if dim_match:
        w1, w2, h1, h2 = dim_match.groups()
        metric_code = f"{int(w1)}{int(w2)}{int(h1)}{int(h2)}"
        return metric_code

    return None


def _to_db_row(
    result: ProviderResult, bom_line_id: int, rank: int, quantity: int
) -> PartResultRow:
    best_dist = (
        max(result.distributors, key=lambda d: d.stock)
        if result.distributors
        else None
    )
    return PartResultRow(
        bom_line_id=bom_line_id,
        rank=rank,
        mpn=result.mpn,
        manufacturer=result.manufacturer,
        description=result.description,
        package=result.package,
        distributor=best_dist.distributor if best_dist else None,
        unit_price=_best_unit_price(result.pricing, quantity),
        stock=result.stock_total,
        lifecycle_status=result.lifecycle_status,
        tech_specs=result.tech_specs,
        datasheet_url=result.datasheet_url,
        image_url=result.image_url,
        source_provider=result.source_provider,
        match_type=result.match_type,
        retrieved_at=result.retrieved_at,
    )
