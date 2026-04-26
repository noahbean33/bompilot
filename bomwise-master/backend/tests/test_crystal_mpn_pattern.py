"""
Tests for crystal footprint MPN pattern detection (Task 1 fix).

Verifies that _FOOTPRINT_HAS_MPN_RE now matches crystal footprints
like Crystal_SMD_3225-4Pin_3.2x2.5mm.
"""

import pytest
from app.services.matching import _footprint_has_mpn_pattern, is_unmatchable


class TestCrystalFootprintMpnPattern:
    """Tests for _footprint_has_mpn recognizing crystal metric patterns."""

    def test_crystal_3225_4pin(self):
        """Crystal SMD 3225 with 4 pins — should be detected as having MPN pattern."""
        fp = "Crystal_SMD_3225-4Pin_3.2x2.5mm"
        assert _footprint_has_mpn_pattern(fp) is True

    def test_crystal_2520_4pin(self):
        """Crystal SMD 2520 with 4 pins."""
        fp = "Crystal_SMD_2520-4Pin_2.5x2.0mm"
        assert _footprint_has_mpn_pattern(fp) is True

    def test_crystal_5032_4pin(self):
        """Crystal SMD 5032 with 4 pins."""
        fp = "Crystal_SMD_5032-4Pin_5.0x3.2mm"
        assert _footprint_has_mpn_pattern(fp) is True

    def test_crystal_lowercase_pin(self):
        """Lowercase 'pin' should also match."""
        fp = "Crystal_SMD_3225-4pin_3.2x2.5mm"
        assert _footprint_has_mpn_pattern(fp) is True

    def test_oscillator_4pin(self):
        """Oscillator with 4-pin metric size also matches."""
        fp = "Oscillator_SMD_SeikoEpson_SG210-4Pin_2.5x2.0mm"
        assert _footprint_has_mpn_pattern(fp) is True

    def test_generic_passive_no_mpn_pattern(self):
        """Standard passive footprint should NOT match."""
        fp = "R_0402_1005Metric"
        assert _footprint_has_mpn_pattern(fp) is False

    def test_crystal_gnd_no_longer_unmatchable_with_crystal_footprint(self):
        """Crystal_GND24 + crystal footprint → NOT unmatchable (relaxed check)."""
        fp = "Crystal_SMD_3225-4Pin_3.2x2.5mm"
        assert is_unmatchable("Crystal_GND24", fp) is False

    def test_crystal_gnd_unmatchable_without_footprint(self):
        """Crystal_GND24 without footprint → still unmatchable."""
        assert is_unmatchable("Crystal_GND24") is True
        assert is_unmatchable("Crystal_GND24", None) is True

    def test_crystal_gnd_with_non_mpn_footprint(self):
        """Crystal_GND24 with generic footprint → still unmatchable."""
        assert is_unmatchable("Crystal_GND24", "Pad_2mm") is True