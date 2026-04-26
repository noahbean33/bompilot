"""
AI-assisted BOM matching service.

For BOM lines that the normal MPN/keyword matching cannot resolve (pending,
no_match, or a previous ai_suggested pass), this service:

  1. Classifies each line via Claude Haiku (batch of up to 15 at a time):
       - copper_only  → mark as "no_part_needed" immediately
       - real part    → generate 1–3 keyword search queries

  2. Runs those queries through the provider fallback chain.

  3. Stores provider results as PartAlternative rows so the user can review
     them on the Alternatives page, then sets match_type = "ai_suggested".
     If every query returns empty, sets match_type = "no_match".

New match_type values introduced:
  "no_part_needed"  – copper-only pad/fiducial/artwork; nothing to purchase
  "ai_suggested"    – AI ran queries, ≥1 candidate in part_alternatives; user must confirm

Token usage is recorded in Redis under:
  ai:ai_assist:tokens:input:{YYYY-MM-DD}
  ai:ai_assist:tokens:output:{YYYY-MM-DD}
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.project import BomLine
    from app.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)

# How many BOM lines we send to Claude in a single call.
_BATCH_SIZE = 15

# Redis key templates (daily, so the AI usage page can show today's totals).
_REDIS_INPUT_KEY = "ai:ai_assist:tokens:input:{date}"
_REDIS_OUTPUT_KEY = "ai:ai_assist:tokens:output:{date}"

# match_type values written by this service
MATCH_TYPE_NO_PART_NEEDED = "no_part_needed"
MATCH_TYPE_AI_SUGGESTED = "ai_suggested"

# match_type values that are eligible for an AI Assist pass
ELIGIBLE_MATCH_TYPES: frozenset[str | None] = frozenset([None, "no_match", "ai_suggested"])

# ---------------------------------------------------------------------------
# Claude prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an electronics component expert helping to classify
PCB Bill-of-Materials entries.

For each entry you will receive: value, footprint, and optional description.

Your tasks:
1. Determine if this is "copper only" — a pad, test point, fiducial, mounting
   hole, logo, artwork, or solder jumper that requires NO purchased component.
2. If it is a real component:
   a. Identify the likely manufacturer part number (MPN) if the value OR FOOTPRINT looks like one.
      - Example: "SY8253ADC" is a valid MPN (Silergy buck converter).
      - Example: "SMF5V0A" is a valid MPN (Semitech TVS diode, SOD-123/SMF package).
      - Example: "SG-210STF" is a valid MPN (Epson oscillator).
      - Example: "Conn_01x06" with footprint "JST_SHL_SM06B-SHLS-TF" → MPN is "SM06B-SHLS-TF" (JST connector)
      - Example: "Conn_01x06" with footprint "USB_C_Receptacle_XKB_U262-16XN-4BVC11" → MPN is "U262-16XN-4BVC11"
      - Example: "Crystal_GND24" with footprint "Crystal_SMD_3225-4Pin_3.2x2.5mm" → real crystal
      - Example: "2m/1%" with footprint "R_Shunt_Ohmite_LVK12" → current sense resistor, Ohmite LVK series
      - KiCad connector footprints often embed the real MPN: JST_SHL_SM06B-SHLS-TF → "SM06B-SHLS-TF"
      - If the VALUE is alphanumeric and 5+ chars (no spaces), it IS likely an MPN → include it as first candidate.
      - Include the raw MPN in "mpn_candidates" (up to 3 candidates).
   b. Generate 1–3 short keyword search phrases for distributor search engines.
      - Focus on physical characteristics: type, package, specs.
      - For KiCad connectors (Conn_*): extract MPN from footprint and search it directly.
        Example: Conn_01x06 + JST_SHL_SM06B-SHLS-TF → "SM06B-SHLS-TF JST connector 6-position 1mm"
        Example: USB_C_Receptacle + XKB_U262-16XN-4BVC11 → "U262-16XN-4BVC11 USB-C connector"
      - For TVS diodes: "SMF5V0A TVS diode 5V SOD-123"
      - For crystals: "SMD crystal 3225 4-pin"
      - For oscillators: "SG-210STF oscillator SMD 2.5x2.0mm"
      - For shunt resistors: "Ohmite LVK12 current sense resistor 2mOhm 1%"
      - Good example for R 10k / R_0402: "10k resistor 0402"
      - Good example for SY8253ADC / TSOT-23-6:
        "SY8253ADC synchronous buck converter TSOT-23-6"

Return ONLY a JSON array — no prose, no markdown, no explanation.
One object per input entry, same order as input:
[
  {
    "copper_only": false,
    "mpn_candidates": ["SM06B-SHLS-TF", "SMF5V0A"],
    "search_queries": ["SM06B-SHLS-TF JST connector 6-position 1mm"]
  },
  {"copper_only": true, "mpn_candidates": [], "search_queries": []}
]
""".strip()


def _build_user_message(lines: list[BomLine]) -> str:
    entries = []
    for line in lines:
        entries.append({
            "ref": line.reference or f"id:{line.id}",
            "value": line.value or "",
            "footprint": line.footprint or "",
            "description": line.description or "",
        })
    return json.dumps(entries, ensure_ascii=False)


def _parse_claude_response(text: str) -> list[dict]:
    """Extract the JSON array from Claude's response, stripping any markdown fences."""
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ``` fences if present
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Redis helpers (fire-and-forget, best-effort — identical pattern to nl_query)
# ---------------------------------------------------------------------------

async def _track_tokens(input_tokens: int, output_tokens: int) -> None:
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1.0)
        async with client:
            await client.incrby(_REDIS_INPUT_KEY.format(date=today), input_tokens)
            await client.incrby(_REDIS_OUTPUT_KEY.format(date=today), output_tokens)
    except Exception as exc:
        logger.debug("ai_matching: token tracking failed (Redis unavailable?): %s", exc)


async def _get_lines_used_this_month(user_id: int) -> int:
    """Return how many AI Assist lines this user has consumed this month."""
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings
        month = datetime.now(UTC).strftime("%Y-%m")
        key = f"ai:assist:{user_id}:lines:{month}"
        client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1.0)
        async with client:
            raw = await client.get(key)
        return int(raw) if raw else 0
    except Exception:
        return 0


async def _increment_lines_used(user_id: int, count: int) -> None:
    """Atomically increment the monthly line counter for user_id by count."""
    if count <= 0:
        return
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings
        month = datetime.now(UTC).strftime("%Y-%m")
        key = f"ai:assist:{user_id}:lines:{month}"
        client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1.0)
        async with client:
            await client.incrby(key, count)
            # Auto-expire after 35 days so stale keys clean themselves up
            await client.expire(key, 35 * 24 * 3600)
    except Exception as exc:
        logger.warning("ai_matching: failed to increment line counter for user %d: %s", user_id, exc)


# ---------------------------------------------------------------------------
# Budget helpers
# ---------------------------------------------------------------------------

async def get_budget_state(user_id: int, limit: int | None) -> dict:
    """Return a budget summary dict for the given user and effective limit."""
    used = await _get_lines_used_this_month(user_id)
    if limit is None:
        remaining = None
    else:
        remaining = max(0, limit - used)
    now = datetime.now(UTC)
    # resets_at = first day of next month 00:00 UTC
    if now.month == 12:
        resets_at = datetime(now.year + 1, 1, 1, tzinfo=UTC).isoformat()
    else:
        resets_at = datetime(now.year, now.month + 1, 1, tzinfo=UTC).isoformat()
    return {
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "resets_at": resets_at,
        "unlimited": limit is None,
    }


# ---------------------------------------------------------------------------
# Core AI classification
# ---------------------------------------------------------------------------

async def _classify_batch(lines: list[BomLine]) -> list[dict]:
    """Call Claude Haiku for one batch of lines.  Returns one dict per line."""
    try:
        import anthropic as _anthropic
    except ImportError:
        logger.warning("ai_matching: anthropic package not installed — skipping AI classification")
        return [{"copper_only": False, "search_queries": []} for _ in lines]

    from app.core.database import settings
    if not settings.anthropic_api_key:
        logger.info("ai_matching: ANTHROPIC_API_KEY not set — skipping AI classification")
        return [{"copper_only": False, "search_queries": []} for _ in lines]

    client = _anthropic.Anthropic(api_key=settings.anthropic_api_key)
    user_message = _build_user_message(lines)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        logger.error("ai_matching: Claude API call failed: %s", exc)
        return [{"copper_only": False, "search_queries": []} for _ in lines]

    # Track tokens (fire-and-forget)
    import asyncio
    asyncio.ensure_future(
        _track_tokens(response.usage.input_tokens, response.usage.output_tokens)
    )

    raw_text = response.content[0].text if response.content else "[]"
    try:
        parsed = _parse_claude_response(raw_text)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("ai_matching: failed to parse Claude response: %s | raw=%r", exc, raw_text[:200])
        return [{"copper_only": False, "search_queries": []} for _ in lines]

    # Pad/truncate to match input length in case Claude drops entries
    result: list[dict] = []
    for i, line in enumerate(lines):
        if i < len(parsed) and isinstance(parsed[i], dict):
            entry = parsed[i]
        else:
            entry = {"copper_only": False, "mpn_candidates": [], "search_queries": []}
        result.append({
            "copper_only": bool(entry.get("copper_only", False)),
            "mpn_candidates": [str(m) for m in entry.get("mpn_candidates", []) if m][:2],
            "search_queries": [str(q) for q in entry.get("search_queries", []) if q][:3],
        })
    return result


# ---------------------------------------------------------------------------
# Provider search helpers
# ---------------------------------------------------------------------------

# MPN suffixes that denote tape/reel/packaging variants — strip before search.
_MPN_SUFFIX_RE = re.compile(r"(?:R[LK]?|T[RRS]?|(?:DK|CT|ND|TR|DKR|RL|PA))$", re.IGNORECASE)

# Detect if a bare value string looks like an MPN:
# - 5+ chars, no spaces
# - contains at least one digit and at least one letter
# - common MPN patterns: leading letters, mixed digits, optional hyphen/suffix
_MPN_DETECTOR_RE = re.compile(r"^[A-Za-z]{1,5}[\dA-Za-z-]{3,20}$")


def _looks_like_mpn(value: str | None) -> str | None:
    """Return value if it looks like a bare MPN, else None."""
    if not value:
        return None
    v = value.strip()
    if not v or " " in v:
        return None
    if _MPN_DETECTOR_RE.match(v):
        # Must contain at least one digit and one letter
        has_digit = any(c.isdigit() for c in v)
        has_alpha = any(c.isalpha() for c in v)
        if has_digit and has_alpha:
            return v
    return None


def _normalise_mpn(mpn: str) -> str:
    """Strip packaging/tape-reel suffixes from an MPN for broader matching.

    Examples: SY8253ADCR → SY8253ADC,  LM358DR2G → LM358D,  TPS54331DR → TPS54331
    """
    return _MPN_SUFFIX_RE.sub("", mpn).strip()


async def _search_queries(
    queries: list[str],
    registry: "ProviderRegistry",
    prefs=None,
    mpn_hints: list[str] | None = None,
    footprint: str | None = None,
    value: str | None = None,
) -> list:
    """Run each query through the provider fallback chain; return first non-empty result list.

    If *mpn_hints* are provided (cleaned MPN candidates from Claude), we try
    ``search_by_mpn`` first on those before falling back to keyword searches.

    If *footprint* and *value* are provided and all other strategies fail, we
    try a manufacturer+series keyword search extracted from the footprint.
    """
    from app.schemas.preferences import MergedPreferences
    from app.services.matching import resolve_fallback_order

    if prefs is None:
        prefs = MergedPreferences()
    fallback_order = resolve_fallback_order(prefs.preferred_distributors or None)

    # --- Strategy 1: Exact MPN lookup (highest confidence) ---
    if mpn_hints:
        seen_mpns: set[str] = set()
        for candidate in mpn_hints:
            mpn = _normalise_mpn(candidate).upper().strip().rstrip(",")
            if not mpn or mpn in seen_mpns:
                continue
            seen_mpns.add(mpn)
            for provider_name in fallback_order:
                provider = registry.get_by_name(provider_name)
                if provider is None:
                    continue
                try:
                    results = await provider.search_by_mpn(mpn, 1, prefs)
                    if results:
                        logger.info("ai_matching: MPN lookup %r → %d results via %s", mpn, len(results), provider_name)
                        return results
                except NotImplementedError:
                    continue
                except Exception as exc:
                    logger.debug("ai_matching: provider %r MPN error for %r: %s", provider_name, mpn, exc)
                    continue

            # Also try hyphen-stripped variant
            if "-" in mpn:
                stripped = mpn.replace("-", "")
                for provider_name in fallback_order:
                    provider = registry.get_by_name(provider_name)
                    if provider is None:
                        continue
                    try:
                        results = await provider.search_by_mpn(stripped, 1, prefs)
                        if results:
                            logger.info("ai_matching: MPN lookup %r (hyphen-stripped) → %d results via %s", stripped, len(results), provider_name)
                            return results
                    except NotImplementedError:
                        continue
                    except Exception:
                        continue

    # --- Strategy 2: Keyword search ---
    for query in queries:
        if not query.strip():
            continue
        for provider_name in fallback_order:
            provider = registry.get_by_name(provider_name)
            if provider is None:
                continue
            try:
                results = await provider.search_by_keyword(query, 1, prefs)
                if results:
                    logger.info("ai_matching: keyword %r → %d results via %s", query, len(results), provider_name)
                    return results
            except NotImplementedError:
                continue
            except Exception as exc:
                logger.debug("ai_matching: provider %r keyword error for %r: %s", provider_name, query, exc)
                continue

    # --- Strategy 3: Manufacturer+series extracted from footprint ---
    if footprint:
        from app.services.matching import _extract_mfr_series

        mfr, series = _extract_mfr_series(footprint)
        if series:
            query = f"{mfr} {series}"
            if value:
                query += f" {value}"
            logger.debug("ai_matching: mfr+series fallback keyword=%r for footprint=%r", query, footprint)
            for provider_name in fallback_order:
                provider = registry.get_by_name(provider_name)
                if provider is None:
                    continue
                try:
                    results = await provider.search_by_keyword(query, 1, prefs)
                    if results:
                        logger.info("ai_matching: mfr+series keyword %r → %d results via %s", query, len(results), provider_name)
                        return results
                except NotImplementedError:
                    continue
                except Exception:
                    continue

    logger.info("ai_matching: no results for queries=%r mpn_hints=%r", queries, mpn_hints)
    return []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def ai_assist_project(
    db: Session,
    project_id: int,
    registry: ProviderRegistry,
    user_id: int,
    budget_limit: int | None,
) -> dict:
    """Run AI Assist on all eligible pending lines in a project.

    Returns a summary dict:
      {
        processed: int,    – lines sent to AI
        no_part_needed: int,
        ai_suggested: int,
        no_match: int,
        skipped_budget: int, – lines not processed because budget was exhausted
        budget: {used, limit, remaining, resets_at, unlimited},
      }
    """
    from sqlalchemy import or_

    from app.models.part_alternatives import PartAlternative
    from app.models.project import BomLine
    from app.schemas.preferences import MergedPreferences

    # ------------------------------------------------------------------
    # 1. Fetch eligible lines (and project preferences for provider order)
    # ------------------------------------------------------------------
    prefs = MergedPreferences()

    _non_null_types = [t for t in ELIGIBLE_MATCH_TYPES if t is not None]
    all_eligible: list[BomLine] = (
        db.query(BomLine)
        .filter(
            BomLine.project_id == project_id,
            BomLine.locked == False,   # noqa: E712
            BomLine.dnp == False,      # noqa: E712
            or_(
                BomLine.match_type.is_(None),
                BomLine.match_type.in_(_non_null_types),
            ),
        )
        .all()
    )

    # ------------------------------------------------------------------
    # 2. Apply budget cap
    # ------------------------------------------------------------------
    used_before = await _get_lines_used_this_month(user_id)
    if budget_limit is not None:
        remaining_budget = max(0, budget_limit - used_before)
        lines_to_process = all_eligible[:remaining_budget]
        skipped_budget = len(all_eligible) - len(lines_to_process)
    else:
        lines_to_process = all_eligible
        skipped_budget = 0

    counts = {"no_part_needed": 0, "ai_suggested": 0, "no_match": 0}

    # ------------------------------------------------------------------
    # 3. Process in batches
    # ------------------------------------------------------------------
    for batch_start in range(0, len(lines_to_process), _BATCH_SIZE):
        batch = lines_to_process[batch_start: batch_start + _BATCH_SIZE]
        classifications = await _classify_batch(batch)

        for line, cls in zip(batch, classifications):
            # Clear existing alternatives from any previous AI pass
            db.query(PartAlternative).filter(
                PartAlternative.bom_line_id == line.id,
                PartAlternative.source == "ai_assist",
            ).delete(synchronize_session="fetch")

            if cls["copper_only"]:
                line.match_type = MATCH_TYPE_NO_PART_NEEDED
                line.matched_provider = None
                line.selected_result_id = None
                counts["no_part_needed"] += 1
                logger.debug("ai_assist: line %d (%r) → no_part_needed", line.id, line.reference)
                continue

            # Fix 2: Pre-seed MPN candidates from bare value if it looks like an MPN.
            # This catches cases where Claude doesn't include the value as an MPN candidate
            # but the value clearly is one (e.g., SMF5V0A, SG-210STF).
            mpn_hints = list(cls.get("mpn_candidates", []))
            bare_value_mpn = _looks_like_mpn(line.value)
            if bare_value_mpn and bare_value_mpn not in mpn_hints:
                mpn_hints.insert(0, bare_value_mpn)
                logger.debug("ai_assist: pre-seeded MPN hint %r from value for line %d", bare_value_mpn, line.id)

            # Run provider keyword searches (pass MPN candidates for exact lookup first)
            results = await _search_queries(
                cls["search_queries"],
                registry,
                prefs,
                mpn_hints=mpn_hints,
                footprint=line.footprint,
                value=line.value,
            )

            # Fix 5: Value-as-keyword fallback — if all strategies failed and the
            # line has a meaningful value, try one last keyword search using just
            # the value. This catches parts Claude misclassifies or generates poor
            # queries for.
            if not results and line.value and line.value.strip():
                val = line.value.strip()
                logger.debug("ai_assist: fallback keyword search with value=%r for line %d", val, line.id)
                from app.services.matching import resolve_fallback_order
                fallback_order = resolve_fallback_order(prefs.preferred_distributors or None)
                for provider_name in fallback_order:
                    provider = registry.get_by_name(provider_name)
                    if provider is None:
                        continue
                    try:
                        results = await provider.search_by_keyword(val, 1, prefs)
                        if results:
                            logger.info("ai_matching: value-as-keyword %r → %d results via %s", val, len(results), provider_name)
                            break
                    except Exception:
                        continue

            if results:
                for result in results[:5]:  # store up to 5 candidates
                    db.add(PartAlternative(
                        bom_line_id=line.id,
                        mpn=result.mpn,
                        manufacturer=result.manufacturer or "",
                        description=result.description,
                        datasheet_url=result.datasheet_url,
                        source="ai_assist",
                        match_score=None,
                    ))
                line.match_type = MATCH_TYPE_AI_SUGGESTED
                line.matched_provider = None
                counts["ai_suggested"] += 1
                logger.debug(
                    "ai_assist: line %d (%r) → ai_suggested (%d candidates)",
                    line.id, line.reference, len(results[:5]),
                )
            else:
                line.match_type = "no_match"
                counts["no_match"] += 1
                logger.debug("ai_assist: line %d (%r) → no_match (no provider results)", line.id, line.reference)

        db.commit()

    # ------------------------------------------------------------------
    # 4. Update budget counter
    # ------------------------------------------------------------------
    processed = len(lines_to_process)
    await _increment_lines_used(user_id, processed)

    budget = await get_budget_state(user_id, budget_limit)

    return {
        "processed": processed,
        "skipped_budget": skipped_budget,
        **counts,
        "budget": budget,
    }
