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

    def test_graded(self):
        assert _map_condition("PSA 10 Grade") == Condition.NEAR_MINT

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
        assert _map_condition("Grade 7") == Condition.NEAR_MINT

    def test_grade_9(self):
        assert _map_condition("Grade 9") == Condition.NEAR_MINT
