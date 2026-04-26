from datetime import datetime

from app.providers.base import ComponentProvider
from app.providers.schema import ProviderCapabilities, SkippedProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ComponentProvider] = {}
        self._tiers: dict[str, str] = {}  # "free" | "premium"
        self._active: str | None = None

    def register(self, name: str, provider: ComponentProvider, tier: str = "free") -> None:
        self._providers[name] = provider
        self._tiers[name] = tier

    def set_active(self, name: str) -> None:
        if name not in self._providers:
            raise ValueError(f"Unknown provider: {name}")
        self._active = name

    def get(self) -> ComponentProvider:
        if not self._active:
            raise RuntimeError("No active provider configured")
        return self._providers[self._active]

    def get_by_name(self, name: str) -> ComponentProvider | None:
        """Return the named provider, or None if it is not registered."""
        return self._providers.get(name)

    def all_providers(self) -> dict[str, ComponentProvider]:
        """Return a snapshot of all registered providers keyed by name."""
        return dict(self._providers)

    def capabilities(self) -> ProviderCapabilities:
        return self.get().capabilities()

    def accessible_names(self, plan: str, trial_ends_at: datetime | None = None) -> list[str]:
        """Return provider names accessible for *plan*.

        Paid users (or active trial) can use all registered providers.
        Free users can only use providers with tier ``"free"``.
        """
        from datetime import UTC, datetime as _datetime

        is_trial = trial_ends_at is not None
        if is_trial:
            trial_end = trial_ends_at
            if trial_end.tzinfo is None:
                trial_end = trial_end.replace(tzinfo=UTC)
            is_trial = trial_end > _datetime.now(UTC)
        if plan == "paid" or is_trial:
            return list(self._providers.keys())
        return [name for name, tier in self._tiers.items() if tier == "free"]

    def skipped_providers(self, fallback_order: list[str], plan: str, trial_ends_at: datetime | None = None) -> list[SkippedProvider]:
        """Return providers in *fallback_order* that are inaccessible for *plan*.

        Only includes providers that are actually registered (i.e. have
        credentials configured at startup); unregistered providers are silently
        absent from the order already.
        """
        if plan == "paid":
            return []
        accessible = set(self.accessible_names(plan, trial_ends_at))
        return [
            SkippedProvider(name=name, reason="premium_plan_required")
            for name in fallback_order
            if name not in accessible and self._providers.get(name) is not None
        ]


# Module-level singleton — populated during app startup in main.py
registry = ProviderRegistry()


def get_registry() -> ProviderRegistry:
    """FastAPI dependency that returns the app-level registry singleton."""
    return registry
