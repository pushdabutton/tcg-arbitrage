"""Tests for arbitrage detection engine."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.arbitrage import detect_arbitrage, _condition_group
from scraper.models import Condition, Platform, PricePoint


def _make_pp(
    card: str,
    set_name: str,
    platform: Platform,
    price: float,
    condition: Condition = Condition.UNGRADED,
) -> PricePoint:
    """Helper to create a PricePoint."""
    return PricePoint(
        card_name=card,
        set_name=set_name,
        platform=platform,
        price_usd=price,
        condition=condition,
    )


class TestConditionGrouping:
    """Verify that condition groups separate raw from graded correctly."""

    def test_raw_conditions_same_group(self):
        """Ungraded, NM, LP should all be in 'raw' group."""
        assert _condition_group(Condition.UNGRADED) == "raw"
        assert _condition_group(Condition.NEAR_MINT) == "raw"
        assert _condition_group(Condition.LIGHTLY_PLAYED) == "raw"
        assert _condition_group(Condition.MODERATELY_PLAYED) == "raw"

    def test_graded_slabs_separate_groups(self):
        """Each PSA grade is its own group."""
        assert _condition_group(Condition.PSA_10) == "psa_10"
        assert _condition_group(Condition.PSA_9_5) == "psa_9_5"
        assert _condition_group(Condition.PSA_9) == "psa_9"
        assert _condition_group(Condition.PSA_8) == "psa_8"
        assert _condition_group(Condition.PSA_7) == "psa_7"

    def test_graded_not_in_raw_group(self):
        """PSA grades should NOT be in the 'raw' group."""
        assert _condition_group(Condition.PSA_10) != "raw"


class TestNoFalseArbitrageFromConditionMismatch:
    """BUG 1: Prevent false arbitrage from comparing graded slabs to raw cards."""

    def test_psa10_vs_raw_no_arbitrage(self):
        """A PSA 10 slab at $1,482 vs raw at $26 should NOT be flagged."""
        points = [
            _make_pp("Charizard", "Base Set", Platform.PRICECHARTING, 26.0,
                     condition=Condition.UNGRADED),
            _make_pp("Charizard", "Base Set", Platform.PRICECHARTING, 1482.0,
                     condition=Condition.PSA_10),
            _make_pp("Charizard", "Base Set", Platform.TCGPLAYER, 30.0,
                     condition=Condition.NEAR_MINT),
        ]
        opps = detect_arbitrage(points, threshold_percent=20.0)
        # Should NOT flag $26 vs $1482 as arbitrage
        for opp in opps:
            assert not (opp.buy_price < 50 and opp.sell_price > 1000), (
                f"False arbitrage detected: buy ${opp.buy_price} vs sell ${opp.sell_price}"
            )

    def test_same_grade_across_platforms_detected(self):
        """Same grade on different platforms should still detect arbitrage."""
        points = [
            _make_pp("Charizard", "Base Set", Platform.PRICECHARTING, 200.0,
                     condition=Condition.UNGRADED),
            _make_pp("Charizard", "Base Set", Platform.TCGPLAYER, 400.0,
                     condition=Condition.UNGRADED),
        ]
        opps = detect_arbitrage(points, threshold_percent=20.0)
        assert len(opps) == 1
        assert opps[0].buy_price == 200.0
        assert opps[0].sell_price == 400.0

    def test_raw_nm_vs_raw_ungraded_same_group(self):
        """NM and Ungraded are both 'raw' and can be compared."""
        points = [
            _make_pp("Pikachu", "Base Set", Platform.PRICECHARTING, 10.0,
                     condition=Condition.UNGRADED),
            _make_pp("Pikachu", "Base Set", Platform.TCGPLAYER, 20.0,
                     condition=Condition.NEAR_MINT),
        ]
        opps = detect_arbitrage(points, threshold_percent=20.0)
        assert len(opps) == 1


def test_no_arbitrage_single_platform():
    """Single platform cannot produce arbitrage."""
    points = [
        _make_pp("Charizard", "Base Set", Platform.PRICECHARTING, 300.0),
    ]
    opps = detect_arbitrage(points, threshold_percent=20.0)
    assert len(opps) == 0


def test_no_arbitrage_small_spread():
    """Spread below threshold should not trigger."""
    points = [
        _make_pp("Charizard", "Base Set", Platform.PRICECHARTING, 95.0),
        _make_pp("Charizard", "Base Set", Platform.TCGPLAYER, 100.0),
    ]
    # 5% spread -- below 20% threshold
    opps = detect_arbitrage(points, threshold_percent=20.0)
    assert len(opps) == 0


def test_arbitrage_detected():
    """Clear 50% spread should produce an opportunity."""
    points = [
        _make_pp("Charizard", "Base Set", Platform.PRICECHARTING, 200.0),
        _make_pp("Charizard", "Base Set", Platform.TCGPLAYER, 400.0),
    ]
    opps = detect_arbitrage(points, threshold_percent=20.0)
    assert len(opps) == 1
    opp = opps[0]
    assert opp.buy_platform == Platform.PRICECHARTING
    assert opp.sell_platform == Platform.TCGPLAYER
    assert opp.buy_price == 200.0
    assert opp.sell_price == 400.0


def test_arbitrage_bidirectional():
    """Only the direction with a positive spread should be flagged."""
    points = [
        _make_pp("Pikachu", "Base Set", Platform.PRICECHARTING, 10.0),
        _make_pp("Pikachu", "Base Set", Platform.TCGPLAYER, 15.0),
    ]
    # Spread: (15-10)/15 = 33.3% -- buy PC, sell TCG
    # Reverse: (10-15)/10 = -50% -- negative, so not flagged
    opps = detect_arbitrage(points, threshold_percent=20.0)
    assert len(opps) == 1
    assert opps[0].buy_platform == Platform.PRICECHARTING
    assert opps[0].sell_platform == Platform.TCGPLAYER


def test_arbitrage_multiple_cards():
    """Multiple cards should be independently evaluated."""
    points = [
        _make_pp("Charizard", "Base Set", Platform.PRICECHARTING, 200.0),
        _make_pp("Charizard", "Base Set", Platform.TCGPLAYER, 400.0),
        _make_pp("Pikachu", "Base Set", Platform.PRICECHARTING, 9.0),
        _make_pp("Pikachu", "Base Set", Platform.TCGPLAYER, 10.0),
    ]
    opps = detect_arbitrage(points, threshold_percent=20.0)
    # Charizard: 50% spread -- yes
    # Pikachu: 10% spread -- no
    assert len(opps) == 1
    assert opps[0].card_name == "Charizard"


def test_arbitrage_two_platforms():
    """Two platforms with significant spread should generate one opportunity."""
    points = [
        _make_pp("Mewtwo", "Base Set", Platform.PRICECHARTING, 50.0),
        _make_pp("Mewtwo", "Base Set", Platform.TCGPLAYER, 80.0),
    ]
    opps = detect_arbitrage(points, threshold_percent=20.0)
    # PC vs TCG: (80-50)/80=37.5% -- yes
    assert len(opps) == 1


def test_arbitrage_sorted_by_spread():
    """Results should be sorted by spread_percent descending."""
    points = [
        _make_pp("A", "Set1", Platform.PRICECHARTING, 50.0),
        _make_pp("A", "Set1", Platform.TCGPLAYER, 100.0),
        _make_pp("B", "Set1", Platform.PRICECHARTING, 70.0),
        _make_pp("B", "Set1", Platform.TCGPLAYER, 100.0),
    ]
    opps = detect_arbitrage(points, threshold_percent=20.0)
    assert len(opps) == 2
    # A: 50% spread should come first
    assert opps[0].card_name == "A"
    assert opps[1].card_name == "B"


def test_arbitrage_takes_best_price_per_platform():
    """When multiple prices exist for a platform, use the lowest."""
    points = [
        _make_pp("Charizard", "Base Set", Platform.PRICECHARTING, 200.0),
        _make_pp("Charizard", "Base Set", Platform.PRICECHARTING, 250.0),  # higher
        _make_pp("Charizard", "Base Set", Platform.TCGPLAYER, 400.0),
    ]
    opps = detect_arbitrage(points, threshold_percent=20.0)
    assert len(opps) == 1
    assert opps[0].buy_price == 200.0  # Took the lower price
