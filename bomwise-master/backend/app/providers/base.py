import asyncio
import functools
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from app.providers.schema import ParametricQuery, PartResult, ProviderCapabilities
from app.schemas.preferences import MergedPreferences

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Redis instrumentation helpers
# ---------------------------------------------------------------------------

async def _redis_record(name: str, success: bool, call_time: datetime) -> None:
    """Write provider call metrics to Redis.  Best-effort — silently swallows all errors."""
    try:
        import redis.asyncio as aioredis
        from app.core.database import settings

        client = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=1.0
        )
        date_str = call_time.strftime("%Y-%m-%d")
        ttl = 25 * 3600  # 25-hour TTL so keys expire naturally overnight

        async with client.pipeline(transaction=False) as pipe:
            pipe.set(f"provider:{name}:last_called_at", call_time.isoformat())
            if success:
                pipe.set(f"provider:{name}:last_success_at", call_time.isoformat())
            else:
                ekey = f"provider:{name}:errors:{date_str}"
                pipe.incr(ekey)
                pipe.expire(ekey, ttl)
            ckey = f"provider:{name}:calls:{date_str}"
            pipe.incr(ckey)
            pipe.expire(ckey, ttl)
            await pipe.execute()

        await client.aclose()
    except Exception:
        pass  # Redis unavailable or any error — instrumentation is best-effort


def _make_tracked(method):
    """Wrap an async provider search method with Redis call instrumentation."""

    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        name: str = getattr(self, "PROVIDER_NAME", None) or type(self).__name__.lower()
        call_time = datetime.now(UTC)
        try:
            result = await method(self, *args, **kwargs)
            # Fire-and-forget Redis write — does not add latency to the search
            try:
                asyncio.get_running_loop().create_task(
                    _redis_record(name, True, call_time)
                )
            except RuntimeError:
                pass
            return result
        except NotImplementedError:
            raise  # not a provider error — don't instrument
        except Exception as exc:
            try:
                asyncio.get_running_loop().create_task(
                    _redis_record(name, False, call_time)
                )
            except RuntimeError:
                pass
            try:
                from app.services.provider_error_logger import classify_error, log_provider_error
                error_type, status_code = classify_error(exc)
                asyncio.get_running_loop().create_task(
                    log_provider_error(name, error_type, str(exc), status_code)
                )
            except RuntimeError:
                pass
            raise

    return wrapper


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class ComponentProvider(ABC):
    """All component data providers must subclass this.

    Subclass methods named search_by_mpn / search_by_keyword /
    search_by_distributor_pn / search_parametric are automatically wrapped with
    Redis call instrumentation at class-definition time via __init_subclass__.
    No changes to individual adapters are required.
    """

    # Subclasses should override these class attributes.
    PROVIDER_NAME: str | None = None
    DAILY_LIMIT: int | None = None  # API calls allowed per day; None = unknown

    _INSTRUMENTED_METHODS = (
        "search_by_mpn",
        "search_by_keyword",
        "search_by_distributor_pn",
        "search_parametric",
    )

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        for method_name in ComponentProvider._INSTRUMENTED_METHODS:
            if method_name in cls.__dict__ and callable(cls.__dict__[method_name]):
                setattr(cls, method_name, _make_tracked(cls.__dict__[method_name]))

    @abstractmethod
    async def search_by_mpn(
        self,
        mpn: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        """Exact or near-exact MPN lookup."""

    @abstractmethod
    async def search_by_distributor_pn(
        self,
        distributor: str,
        pn: str,
        quantity: int,
    ) -> list[PartResult]:
        """Lookup by distributor-specific part number."""

    @abstractmethod
    async def search_parametric(
        self,
        params: ParametricQuery,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        """Search by component specifications when no MPN is available."""

    async def search_by_keyword(
        self,
        keyword: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        """Free-text / value+package keyword search.  Optional; providers that
        don't support it raise NotImplementedError."""
        raise NotImplementedError("search_by_keyword not implemented for this provider")

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declare what this provider can and cannot return."""
