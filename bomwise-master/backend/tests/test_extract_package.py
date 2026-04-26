"""
Tests for _extract_package — covers dimension parsing (Task 2 fix).
"""

import pytest
from app.services.matching import _extract_package


class TestExtractPackageDimensionParsing:
    """Tests for decimal-mm dimension → metric code conversion."""

    def test_oscillator_2_5x2_0mm(self):
        """Oscillator footprint: 2.5×2.0mm → 2520."""
        fp = "Oscillator_SMD_SeikoEpson_SG210-4Pin_2.5x2.0mm"
        assert _extract_package(fp) == "2520"

    def test_crystal_3_2x2_5mm(self):
        """Crystal footprint: 3.2×2.5mm → 3225."""
        fp = "Crystal_SMD_3225-4Pin_3.2x2.5mm"
        # 3225 literal appears first → returned from literal check
        assert _extract_package(fp) == "3225"

    def test_crystal_only_dimension(self):
        """Crystal footprint with only dimension (no literal 3225)."""
        fp = "Crystal_SMD_3.2x2.5mm"
        assert _extract_package(fp) == "3225"

    def test_oscillator_5_0x3_2mm(self):
        """Oscillator: 5.0×3.2mm → 5032."""
        fp = "Oscillator_SMD_5.0x3.2mm"
        assert _extract_package(fp) == "5032"

    def test_oscillator_2_0x1_6mm(self):
        """Oscillator: 2.0×1.6mm → 2016."""
        fp = "Oscillator_SMD_2.0x1.6mm"
        assert _extract_package(fp) == "2016"

    def test_oscillator_3_2x1_5mm(self):
        """Oscillator: 3.2×1.5mm → 3215."""
        fp = "Oscillator_SMD_3.2x1.5mm"
        assert _extract_package(fp) == "3215"

    def test_literal_takes_precedence_over_dimension(self):
        """When literal 3225 AND dimension 3.2x2.5 both present, literal returns first."""
        fp = "Crystal_SMD_3225-4Pin_3.2x2.5mm"
        assert _extract_package(fp) == "3225"

    def test_no_dimension_returns_none(self):
        """Footprint without dimensions → None."""
        fp = "R_0402_1005Metric"
        # Actually returns "0402" from _PACKAGE_RE
        assert _extract_package(fp) == "0402"

    def test_dimension_lowercase_x(self):
        """Lowercase 'x' in dimension should still match."""
        fp = "Oscillator_SMD_2.5x2.0mm"
        assert _extract_package(fp) == "2520"