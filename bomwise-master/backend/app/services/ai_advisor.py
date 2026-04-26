"""
AI Advisor — Parts Explainer service.

Compares selected part alternatives and explains differences using Claude Haiku.
Returns a recommendation on which part to choose based on analysis.

Features:
- Redis cache for repeated MPN comparisons (TTL 7 days)
- Token usage tracking (separate from AI Assist)
- Monthly query counter per user
- Works for both free and paid users (separate limits)

Token usage recorded in Redis under:
  ai:ai_advisor:tokens:input:{YYYY-MM-DD}
  ai:ai_advisor:tokens:output:{YYYY-MM-DD}

Monthly query counter:
  ai:advisor:{user_id}:queries:{YYYY-MM}

Explanation cache:
  ai:advisor:cache:{hash_of_sorted_mpns}
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text as sql_text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.project import BomLine

logger = logging.getLogger(__name__)

# Redis key templates
_REDIS_INPUT_KEY = "ai:ai_advisor:tokens:input:{date}"
_REDIS_OUTPUT_KEY = "ai:ai_advisor:tokens:output:{date}"
_REDIS_QUERY_KEY = "ai:advisor:{user_id}:queries:{month}"
_REDIS_CACHE_KEY = "ai:advisor:cache:{mpns_hash}"
_CACHE_TTL = 7 * 24 * 3600  # 7 days

# ---------------------------------------------------------------------------
# Claude prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an electronics procurement expert helping engineers
choose between alternative components.

You will receive:
1. A list of MPNs (manufacturer part numbers) the user is considering
2. Context about the BOM line (value, footprint, description, quantity)

Your task:
1. Explain the key differences between these parts in plain language
2. Highlight any differences in: package, specifications, price, stock, reel quantity
3. Recommend the best option with clear reasoning
4. Keep it concise — engineers want facts, not fluff

Return ONLY a JSON object with these keys:
{
  "explanation": "Clear comparison of the parts...",
  "recommendation": "The recommended MPN",
  "reasoning": "Why this part is the best choice..."
}

No markdown, no extra text. Just the JSON object.
""".strip()


def _build_user_message(mpns: list[str], line: "BomLine") -> str:
    """Build the user message with MPNs and BOM line context."""
    context = {
        "mpns": mpns,
        "bom_line": {
            "reference": line.reference or "N/A",
            "value": line.value or "",
            "footprint": line.footprint or "",
            "description": line.description or "",
            "quantity": line.quantity,
            "mpn_raw": line.mpn_raw or "",
        },
    }
    return json.dumps(context, ensure_ascii=False)


def _parse_claude_response(text: str) -> dict:
    """Extract JSON from Claude response, stripping markdown fences."""
    text = text.strip()
    text = text.strip("`")
    if text.startswith("json"):
        text = text[4:].strip()
    return json.loads(text)


def _get_cache_key(mpns: list[str]) -> str:
    """Generate a deterministic cache key from sorted MPNs."""
    sorted_mpns = sorted(mpns)
    hash_input = "|".join(sorted_mpns)
    mpns_hash = hashlib.md5(hash_input.encode()).hexdigest()
    return _REDIS_CACHE_KEY.format(mpns_hash=mpns_hash)


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

def _get_hash(mpns: list[str]) -> str:
    """Generate deterministic MD5 hash from sorted MPNs."""
    sorted_mpns = sorted(mpns)
    return hashlib.md5("|".join(sorted_mpns).encode()).hexdigest()


async def _get_cached_explanation(mpns: list[str]) -> dict | None:
    """Check Redis cache for a previous explanation of these MPNs."""
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings

        key = _get_cache_key(mpns)
        client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1.0)
        async with client:
            raw = await client.get(key)
        await client.aclose()
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.debug("ai_advisor: cache lookup failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# DB cache helpers (persistent layer)
# ---------------------------------------------------------------------------

def _get_cached_explanation_db(db: "Session", mpns: list[str]) -> dict | None:
    """Check DB for a previous explanation of these MPNs."""
    try:
        from app.models.ai_advisor_cache import AiAdvisorCache
        from datetime import UTC, datetime

        mpn_hash = _get_hash(mpns)
        row = db.query(AiAdvisorCache).filter(AiAdvisorCache.mpn_hash == mpn_hash).first()
        if row:
            # Update access stats
            row.last_accessed = datetime.now(UTC)
            row.access_count = (row.access_count or 0) + 1
            db.commit()
            return {
                "explanation": row.explanation or "",
                "recommendation": row.recommendation or "",
                "reasoning": row.reasoning or "",
                "input_tokens": row.input_tokens or 0,
                "output_tokens": row.output_tokens or 0,
            }
    except Exception as exc:
        logger.debug("ai_advisor: DB cache lookup failed: %s", exc)
        db.rollback()
    return None


def _save_explanation_db(
    db: "Session",
    mpns: list[str],
    line: "BomLine",
    result: dict,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Persist explanation to DB for long-term retention."""
    try:
        from app.models.ai_advisor_cache import AiAdvisorCache
        from datetime import UTC, datetime

        mpn_hash = _get_hash(mpns)
        bom_context = {
            "reference": line.reference or "N/A",
            "value": line.value or "",
            "footprint": line.footprint or "",
            "description": line.description or "",
            "quantity": line.quantity,
            "mpn_raw": line.mpn_raw or "",
        }
        existing = db.query(AiAdvisorCache).filter(AiAdvisorCache.mpn_hash == mpn_hash).first()
        if existing:
            existing.explanation = result.get("explanation", "")
            existing.recommendation = result.get("recommendation", "")
            existing.reasoning = result.get("reasoning", "")
            existing.input_tokens = input_tokens
            existing.output_tokens = output_tokens
            existing.last_accessed = datetime.now(UTC)
            existing.access_count = (existing.access_count or 0) + 1
        else:
            entry = AiAdvisorCache(
                mpn_hash=mpn_hash,
                mpns=sorted(mpns),
                bom_context=bom_context,
                explanation=result.get("explanation", ""),
                recommendation=result.get("recommendation", ""),
                reasoning=result.get("reasoning", ""),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            db.add(entry)
        db.commit()
    except Exception as exc:
        logger.debug("ai_advisor: DB cache save failed: %s", exc)
        db.rollback()


async def _cache_explanation(mpns: list[str], result: dict) -> None:
    """Store explanation in Redis cache."""
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings

        key = _get_cache_key(mpns)
        client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1.0)
        async with client:
            await client.setex(key, _CACHE_TTL, json.dumps(result))
        await client.aclose()
    except Exception as exc:
        logger.debug("ai_advisor: cache store failed: %s", exc)


async def _track_tokens(input_tokens: int, output_tokens: int) -> None:
    """Track token usage in Redis (fire-and-forget)."""
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1.0)
        async with client:
            await client.incrby(_REDIS_INPUT_KEY.format(date=today), input_tokens)
            await client.incrby(_REDIS_OUTPUT_KEY.format(date=today), output_tokens)
        await client.aclose()
    except Exception as exc:
        logger.debug("ai_advisor: token tracking failed: %s", exc)


async def _get_queries_used_this_month(user_id: int) -> int:
    """Return how many AI Advisor queries this user has consumed this month."""
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings

        month = datetime.now(UTC).strftime("%Y-%m")
        key = _REDIS_QUERY_KEY.format(user_id=user_id, month=month)
        client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1.0)
        async with client:
            raw = await client.get(key)
        await client.aclose()
        return int(raw) if raw else 0
    except Exception:
        return 0


async def _increment_queries_used(user_id: int) -> None:
    """Atomically increment the monthly query counter for user_id."""
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings

        month = datetime.now(UTC).strftime("%Y-%m")
        key = _REDIS_QUERY_KEY.format(user_id=user_id, month=month)
        client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1.0)
        async with client:
            await client.incrby(key, 1)
            await client.expire(key, 35 * 24 * 3600)  # 35 day expiry
        await client.aclose()
    except Exception as exc:
        logger.warning("ai_advisor: failed to increment query counter for user %d: %s", user_id, exc)


async def get_budget_state(user_id: int, limit: int | None) -> dict:
    """Return a budget summary dict for the given user and effective limit."""
    used = await _get_queries_used_this_month(user_id)
    if limit is None:
        remaining = None
    else:
        remaining = max(0, limit - used)
    now = datetime.now(UTC)
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
# Core AI explanation
# ---------------------------------------------------------------------------

async def _call_claude(mpns: list[str], line: "BomLine") -> dict:
    """Call Claude Haiku to compare parts. Returns explanation dict."""
    try:
        import anthropic as _anthropic
    except ImportError:
        logger.warning("ai_advisor: anthropic package not installed — skipping AI analysis")
        return {
            "explanation": "AI service unavailable. Please try again later.",
            "recommendation": "",
            "reasoning": "",
            "_input_tokens": 0,
            "_output_tokens": 0,
        }

    from app.core.database import settings

    if not settings.anthropic_api_key:
        logger.info("ai_advisor: ANTHROPIC_API_KEY not set — skipping AI analysis")
        return {
            "explanation": "AI service not configured. Please contact support.",
            "recommendation": "",
            "reasoning": "",
            "_input_tokens": 0,
            "_output_tokens": 0,
        }

    client = _anthropic.Anthropic(api_key=settings.anthropic_api_key)
    user_message = _build_user_message(mpns, line)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        logger.error("ai_advisor: Claude API call failed: %s", exc)
        return {
            "explanation": "AI analysis failed. Please try again.",
            "recommendation": "",
            "reasoning": "",
            "_input_tokens": 0,
            "_output_tokens": 0,
        }

    # Track tokens (fire-and-forget)
    import asyncio

    asyncio.ensure_future(
        _track_tokens(response.usage.input_tokens, response.usage.output_tokens)
    )

    raw_text = response.content[0].text if response.content else "{}"
    try:
        parsed = _parse_claude_response(raw_text)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("ai_advisor: failed to parse Claude response: %s | raw=%r", exc, raw_text[:200])
        return {
            "explanation": "Could not analyze parts. Please try again.",
            "recommendation": "",
            "reasoning": "",
            "_input_tokens": 0,
            "_output_tokens": 0,
        }

    return {
        "explanation": parsed.get("explanation", ""),
        "recommendation": parsed.get("recommendation", ""),
        "reasoning": parsed.get("reasoning", ""),
        "_input_tokens": response.usage.input_tokens,
        "_output_tokens": response.usage.output_tokens,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def explain_parts(
    db: Session,
    mpns: list[str],
    line: "BomLine",
    user_id: int,
    budget_limit: int | None,
) -> dict:
    """Run AI Advisor on selected parts.

    3-TIER CACHE: Redis (fast) → DB (persistent) → Claude API (expensive)

    Returns a summary dict:
      {
        explanation: str,
        recommendation: str,
        reasoning: str,
        cached: bool,
        budget: {used, limit, remaining, resets_at, unlimited},
      }
    """
    # Check budget
    used = await _get_queries_used_this_month(user_id)
    if budget_limit is not None and used >= budget_limit:
        return {
            "explanation": "Monthly AI Advisor quota exceeded. Try again next month or contact support to increase your limit.",
            "recommendation": "",
            "reasoning": "",
            "cached": False,
            "budget": await get_budget_state(user_id, budget_limit),
            "quota_exceeded": True,
        }

    # TIER 1: Check Redis cache (fastest)
    cached = await _get_cached_explanation(mpns)
    if cached is not None:
        await _increment_queries_used(user_id)
        return {
            **cached,
            "cached": True,
            "budget": await get_budget_state(user_id, budget_limit),
            "quota_exceeded": False,
        }

    # TIER 2: Check DB cache (persistent)
    db_cached = _get_cached_explanation_db(db, mpns)
    if db_cached is not None:
        # Repopulate Redis cache for next time
        await _cache_explanation(mpns, db_cached)
        await _increment_queries_used(user_id)
        return {
            **db_cached,
            "cached": True,
            "budget": await get_budget_state(user_id, budget_limit),
            "quota_exceeded": False,
        }

    # TIER 3: Call Claude API (expensive)
    result = await _call_claude(mpns, line)
    input_tokens = result.pop("_input_tokens", 0)
    output_tokens = result.pop("_output_tokens", 0)

    # Save to DB for persistence
    _save_explanation_db(db, mpns, line, result, input_tokens, output_tokens)

    # Save to Redis for fast lookup
    await _cache_explanation(mpns, result)

    # Increment query counter
    await _increment_queries_used(user_id)

    return {
        **result,
        "cached": False,
        "budget": await get_budget_state(user_id, budget_limit),
        "quota_exceeded": False,
    }
