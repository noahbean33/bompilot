"""
Tests for PreferencesService.get_effective_preferences.

All DB interactions are mocked — no live database calls.
Scenarios covered:
  1. No overrides       – user has defaults, project has no row → system defaults win
  2. User overrides     – user sets custom values, no project row
  3. Project currency   – project sets currency only, user has defaults
  4. Project distrib.   – project sets distributors only, user has defaults
  5. Full overrides     – project sets both, user also has custom values
  6. Partial project    – project sets currency only, user has custom distributors
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.preferences import PreferencesService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user_prefs(currency: str = "USD", distributors: list | None = None):
    prefs = MagicMock()
    prefs.preferred_currency = currency
    prefs.preferred_distributors = distributors if distributors is not None else []
    return prefs


def _make_project_prefs(currency: str | None = None, distributors: list | None = None):
    prefs = MagicMock()
    prefs.preferred_currency = currency
    prefs.preferred_distributors = distributors
    return prefs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetEffectivePreferences:
    def _call(self, db, user_prefs, project_prefs):
        """Patch the two inner service calls and invoke get_effective_preferences."""
        with (
            patch.object(
                PreferencesService, "get_user_preferences", return_value=user_prefs
            ),
            patch.object(
                PreferencesService, "get_project_preferences", return_value=project_prefs
            ),
        ):
            return PreferencesService.get_effective_preferences(
                db=db, user_id=1, project_id=99
            )

    def test_no_overrides_returns_user_defaults(self):
        """User has system defaults, no project row → result matches system defaults."""
        db = MagicMock()
        result = self._call(db, _make_user_prefs(), project_prefs=None)

        assert result["preferred_currency"] == "USD"
        assert result["preferred_distributors"] == []

    def test_user_overrides_applied(self):
        """User custom values surface when no project row exists."""
        db = MagicMock()
        result = self._call(
            db,
            _make_user_prefs(currency="EUR", distributors=["DigiKey", "Mouser"]),
            project_prefs=None,
        )

        assert result["preferred_currency"] == "EUR"
        assert result["preferred_distributors"] == ["DigiKey", "Mouser"]

    def test_project_overrides_currency_only(self):
        """Project sets currency; distributors fall back to user defaults."""
        db = MagicMock()
        result = self._call(
            db,
            _make_user_prefs(),
            _make_project_prefs(currency="GBP"),
        )

        assert result["preferred_currency"] == "GBP"
        assert result["preferred_distributors"] == []

    def test_project_overrides_distributors_only(self):
        """Project sets distributors; currency falls back to user defaults."""
        db = MagicMock()
        result = self._call(
            db,
            _make_user_prefs(),
            _make_project_prefs(distributors=["Arrow"]),
        )

        assert result["preferred_currency"] == "USD"
        assert result["preferred_distributors"] == ["Arrow"]

    def test_full_project_overrides_win_over_user(self):
        """Project sets both fields; both user values are superseded."""
        db = MagicMock()
        result = self._call(
            db,
            _make_user_prefs(currency="EUR", distributors=["DigiKey"]),
            _make_project_prefs(currency="JPY", distributors=["Mouser", "Arrow"]),
        )

        assert result["preferred_currency"] == "JPY"
        assert result["preferred_distributors"] == ["Mouser", "Arrow"]

    def test_partial_project_override_currency_user_distributors_kept(self):
        """Project sets currency only; user's distributor list is preserved."""
        db = MagicMock()
        result = self._call(
            db,
            _make_user_prefs(currency="EUR", distributors=["DigiKey"]),
            _make_project_prefs(currency="CAD"),
        )

        assert result["preferred_currency"] == "CAD"
        assert result["preferred_distributors"] == ["DigiKey"]

    def test_partial_project_override_distributors_user_currency_kept(self):
        """Project sets distributors only; user's currency is preserved."""
        db = MagicMock()
        result = self._call(
            db,
            _make_user_prefs(currency="EUR", distributors=["DigiKey"]),
            _make_project_prefs(distributors=["RS Components"]),
        )

        assert result["preferred_currency"] == "EUR"
        assert result["preferred_distributors"] == ["RS Components"]

    def test_result_is_independent_copy(self):
        """Mutating the returned dict does not affect the preferences objects."""
        db = MagicMock()
        user_prefs = _make_user_prefs(distributors=["DigiKey"])
        result = self._call(db, user_prefs, project_prefs=None)

        result["preferred_distributors"].append("Mouser")

        assert user_prefs.preferred_distributors == ["DigiKey"]
