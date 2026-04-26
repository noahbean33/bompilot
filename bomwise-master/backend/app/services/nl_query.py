"""
Natural-language BOM query service.

Translates a plain-English user query into a structured filter expression
using Claude Haiku. The filter is applied client-side; this module only
produces the expression and tracks token usage in Redis.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

try:
    import anthropic  # noqa: F401 — imported here so tests can patch app.services.nl_query.anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

from app.core.database import settings  # noqa: E402 — module-level so tests can patch app.services.nl_query.settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BOM schema — hardcoded field descriptions sent to Claude
# ---------------------------------------------------------------------------

BOM_SCHEMA = """
Available BOM fields and their types:
- reference      (string)  : Component reference designator, e.g. "C1", "R12", "U3"
- value          (string)  : Component value, e.g. "100nF", "10kΩ", "STM32F4"
- footprint      (string)  : PCB footprint name
- mpn_raw        (string)  : Raw MPN from the original BOM CSV (may be empty)
- quantity       (integer) : Quantity required
- matched_mpn    (string)  : MPN resolved by the matching service (null if unmatched)
- manufacturer   (string)  : Manufacturer name from the matched part (null if unmatched)
- description    (string)  : Part description
- stock          (integer) : Available stock at the distributor (null if unmatched)
- unit_price     (float)   : Unit price in the project currency (null if unmatched)
- distributor    (string)  : Distributor name for the matched part (null if unmatched)
- match_type     (string)  : How the part was matched: "mpn", "keyword", or null
- category       (string)  : Inferred from reference prefix: "capacitor" (C), "resistor" (R),
                             "ic" (U), "inductor" (L), "diode" (D), "transistor" (Q),
                             "connector" (J), "crystal" (Y)
- notes          (string)  : User notes (null if empty)
- locked         (boolean) : Whether the matched part is locked
- matched_provider (string): Provider that supplied the match (null if unmatched)
""".strip()

# ---------------------------------------------------------------------------
# Few-shot examples embedded in the prompt
# ---------------------------------------------------------------------------

FEW_SHOT_EXAMPLES = """
Examples:

User: "parts with no MPN"
Response: {"filters":[{"field":"matched_mpn","op":"is_null","value":null}],"highlight_only":false,"explanation":"Parts with no matched MPN"}

User: "caps under 10 cents"
Response: {"filters":[{"field":"category","op":"eq","value":"capacitor"},{"field":"unit_price","op":"lt","value":0.10}],"highlight_only":false,"explanation":"Capacitors with unit price below $0.10"}

User: "anything from Mouser"
Response: {"filters":[{"field":"distributor","op":"eq","value":"Mouser"}],"highlight_only":false,"explanation":"Parts sourced from Mouser"}

User: "unmatched parts"
Response: {"filters":[{"field":"matched_mpn","op":"is_null","value":null}],"highlight_only":false,"explanation":"Parts that have not been matched yet"}

User: "are there any resistors?"
Response: {"filters":[{"field":"category","op":"eq","value":"resistor"}],"highlight_only":true,"explanation":"Highlighting all resistors in the BOM"}

User: "show me which ICs cost more than $5"
Response: {"filters":[{"field":"category","op":"eq","value":"ic"},{"field":"unit_price","op":"gt","value":5.0}],"highlight_only":true,"explanation":"Highlighting ICs with unit price above $5"}

User: "locked parts"
Response: {"filters":[{"field":"locked","op":"eq","value":true}],"highlight_only":false,"explanation":"Parts that are locked"}
""".strip()

# ---------------------------------------------------------------------------
# Non-filter pre-check (avoids burning tokens on general questions)
# ---------------------------------------------------------------------------

_GENERAL_QUESTION_PATTERNS = [
    r"\bwhat is\b",
    r"\bwhat are\b",
    r"\bhow does\b",
    r"\bexplain\b",
    r"\bdescribe\b",
    r"\btell me about\b",
    r"\bwhy\b",
    r"\bwhen was\b",
    r"\bwho made\b",
    r"\bwhat does .* mean\b",
    r"\bdefine\b",
]

_GENERAL_QUESTION_RE = re.compile(
    "|".join(_GENERAL_QUESTION_PATTERNS), re.IGNORECASE
)

_EMPTY_RESULT = {
    "filters": [],
    "highlight_only": False,
    "explanation": "Could not interpret as a BOM filter. Try phrases like 'show parts with low stock'.",
}


def _looks_like_general_question(query: str) -> bool:
    return bool(_GENERAL_QUESTION_RE.search(query))


# ---------------------------------------------------------------------------
# Redis token tracking (best-effort)
# ---------------------------------------------------------------------------

async def _track_tokens(input_tokens: int, output_tokens: int) -> None:
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=1.0
        )
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        ttl = 25 * 3600
        async with client.pipeline(transaction=False) as pipe:
            ikey = f"ai:nl_query:tokens:input:{date_str}"
            okey = f"ai:nl_query:tokens:output:{date_str}"
            pipe.incrby(ikey, input_tokens)
            pipe.expire(ikey, ttl)
            pipe.incrby(okey, output_tokens)
            pipe.expire(okey, ttl)
            await pipe.execute()
        await client.aclose()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_nl_query(query: str) -> dict:
    """
    Translate a plain-English BOM query into a filter expression dict.

    Returns a dict with keys: filters, highlight_only, explanation.
    Never raises — returns the empty-result sentinel on any failure.
    """
    query = query.strip()[:500]

    if not query:
        return _EMPTY_RESULT.copy()

    if _looks_like_general_question(query):
        return _EMPTY_RESULT.copy()

    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set — NL query returning empty result")
        return _EMPTY_RESULT.copy()

    if anthropic is None:
        logger.warning("anthropic package not installed — NL query returning empty result")
        return _EMPTY_RESULT.copy()

    prompt = f"""{BOM_SCHEMA}

{FEW_SHOT_EXAMPLES}

Supported operators: eq, neq, lt, lte, gt, gte, contains, not_contains, is_null, is_not_null.

Rules:
- Return ONLY valid JSON. No markdown, no explanation outside the JSON.
- Set highlight_only=true for exploratory queries ("are there any…?", "show me which…", "how many…").
- Set highlight_only=false for filtering queries ("show only…", "hide…", "filter to…").
- If the query cannot be mapped to a BOM filter at all, return: {json.dumps(_EMPTY_RESULT)}

User query: {query}
Response:"""

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        # Track token usage (fire-and-forget)
        import asyncio
        usage = message.usage
        try:
            asyncio.get_running_loop().create_task(
                _track_tokens(usage.input_tokens, usage.output_tokens)
            )
        except RuntimeError:
            pass

        raw_text = message.content[0].text.strip()

        # Strip markdown code fences if Claude added them
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text)
            raw_text = re.sub(r"\n?```$", "", raw_text)

        parsed = json.loads(raw_text)

        # Validate minimal structure
        if not isinstance(parsed.get("filters"), list):
            return _EMPTY_RESULT.copy()

        return {
            "filters": parsed.get("filters", []),
            "highlight_only": bool(parsed.get("highlight_only", False)),
            "explanation": str(parsed.get("explanation", "")),
        }

    except Exception as exc:
        logger.warning("NL query failed: %s", exc)
        return _EMPTY_RESULT.copy()
