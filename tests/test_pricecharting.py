"""Tests for PriceCharting scraper parsing logic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.pricecharting import _parse_price, _map_condition
from scraper.models import Condition


class TestParsePrice:
    def test_simple_dollar(self):
        assert _parse_price("$42.50") == 42.50

    def test_no_dollar_sign(self):
        assert _parse_price("42.50") == 42.50

    def test_with_commas(self):
        assert _parse_price("$1,234.56") == 1234.56

    def test_na(self):
        assert _parse_price("N/A") is None

    def test_empty(self):
        assert _parse_price("") is None

    def test_text_with_price(self):
        assert _parse_price("Market Price: $99.99") == 99.99

    def test_zero(self):
        assert _parse_price("$0.00") == 0.0

    def test_whole_number(self):
        assert _parse_price("$100") == 100.0


class TestMapCondition:
    def test_ungraded(self):
        assert _map_condition("Ungraded") == Condition.UNGRADED

    def test_psa_10_grade(self):
        """PSA 10 is a graded slab, not Near Mint raw."""
        assert _map_condition("PSA 10 Grade") == Condition.PSA_10

    def test_first_edition(self):
        assert _map_condition("1st Edition Holo") == Condition.NEAR_MINT

    def test_unknown(self):
        assert _map_condition("something else") == Condition.UNGRADED

    def test_empty(self):
        assert _map_condition("") == Condition.UNGRADED

    def test_box_only_returns_none(self):
        assert _map_condition("Box Only") is None

    def test_manual_only_returns_none(self):
        assert _map_condition("Manual Only") is None

    def test_complete(self):
        assert _map_condition("Complete") == Condition.UNGRADED

    def test_new(self):
        assert _map_condition("New/Sealed") == Condition.NEAR_MINT

    def test_used(self):
        assert _map_condition("Used") == Condition.LIGHTLY_PLAYED

    def test_grade_7(self):
        """Grade 7 is a graded slab, gets PSA_7."""
        assert _map_condition("Grade 7") == Condition.PSA_7

    def test_grade_8(self):
        """Grade 8 is a graded slab, gets PSA_8."""
        assert _map_condition("Grade 8") == Condition.PSA_8

    def test_grade_9(self):
        """Grade 9 is a graded slab, gets PSA_9."""
        assert _map_condition("Grade 9") == Condition.PSA_9

    def test_grade_9_5(self):
        """Grade 9.5 is a graded slab, gets PSA_9_5."""
        assert _map_condition("Grade 9.5") == Condition.PSA_9_5

    def test_generic_graded_defaults_psa9(self):
        """Generic 'graded' label defaults to PSA_9."""
        assert _map_condition("Graded Card") == Condition.PSA_9

    def test_gem_mint_is_psa10(self):
        """Gem Mint label maps to PSA 10."""
        assert _map_condition("Gem Mint") == Condition.PSA_10


class TestConditionModel:
    """Tests for Condition enum properties."""

    def test_graded_conditions_are_graded(self):
        assert Condition.PSA_10.is_graded is True
        assert Condition.PSA_9_5.is_graded is True
        assert Condition.PSA_9.is_graded is True
        assert Condition.PSA_8.is_graded is True
        assert Condition.PSA_7.is_graded is True

    def test_raw_conditions_are_raw(self):
        assert Condition.UNGRADED.is_raw is True
        assert Condition.NEAR_MINT.is_raw is True
        assert Condition.LIGHTLY_PLAYED.is_raw is True

    def test_graded_not_raw(self):
        assert Condition.PSA_10.is_raw is False

    def test_raw_not_graded(self):
        assert Condition.UNGRADED.is_graded is False

    def test_display_labels(self):
        assert Condition.UNGRADED.display_label == "Raw"
        assert Condition.NEAR_MINT.display_label == "NM"
        assert Condition.PSA_10.display_label == "PSA10"
        assert Condition.PSA_9_5.display_label == "PSA9.5"
