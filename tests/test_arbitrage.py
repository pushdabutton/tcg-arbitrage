"""Tests for arbitrage detection engine."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.arbitrage import detect_arbitrage
from scraper.models import Platform, PricePoint


def _make_pp(card: str, set_name: str, platform: Platform, price: float) -> PricePoint:
    """Helper to create a PricePoint."""
    return PricePoint(
        card_name=card,
        set_name=set_name,
        platform=platform,
        price_usd=price,
    )


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
        _make_pp("Charizard", "Base Set", Platform.EBAY, 100.0),
    ]
    # 5% spread -- below 20% threshold
    opps = detect_arbitrage(points, threshold_percent=20.0)
    assert len(opps) == 0


def test_arbitrage_detected():
    """Clear 50% spread should produce an opportunity."""
    points = [
        _make_pp("Charizard", "Base Set", Platform.PRICECHARTING, 200.0),
        _make_pp("Charizard", "Base Set", Platform.EBAY, 400.0),
    ]
    opps = detect_arbitrage(points, threshold_percent=20.0)
    assert len(opps) == 1
    opp = opps[0]
    assert opp.buy_platform == Platform.PRICECHARTING
    assert opp.sell_platform == Platform.EBAY
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
        _make_pp("Charizard", "Base Set", Platform.EBAY, 400.0),
        _make_pp("Pikachu", "Base Set", Platform.PRICECHARTING, 9.0),
        _make_pp("Pikachu", "Base Set", Platform.EBAY, 10.0),
    ]
    opps = detect_arbitrage(points, threshold_percent=20.0)
    # Charizard: 50% spread -- yes
    # Pikachu: 10% spread -- no
    assert len(opps) == 1
    assert opps[0].card_name == "Charizard"


def test_arbitrage_three_platforms():
    """Three platforms should generate pairwise comparisons."""
    points = [
        _make_pp("Mewtwo", "Base Set", Platform.PRICECHARTING, 50.0),
        _make_pp("Mewtwo", "Base Set", Platform.EBAY, 100.0),
        _make_pp("Mewtwo", "Base Set", Platform.TCGPLAYER, 80.0),
    ]
    opps = detect_arbitrage(points, threshold_percent=20.0)
    # PC vs eBay: (100-50)/100=50% -- yes
    # PC vs TCG: (80-50)/80=37.5% -- yes
    # TCG vs eBay: (100-80)/100=20% -- yes (exactly at threshold)
    assert len(opps) == 3


def test_arbitrage_sorted_by_spread():
    """Results should be sorted by spread_percent descending."""
    points = [
        _make_pp("A", "Set1", Platform.PRICECHARTING, 50.0),
        _make_pp("A", "Set1", Platform.EBAY, 100.0),
        _make_pp("B", "Set1", Platform.PRICECHARTING, 70.0),
        _make_pp("B", "Set1", Platform.EBAY, 100.0),
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
        _make_pp("Charizard", "Base Set", Platform.EBAY, 400.0),
    ]
    opps = detect_arbitrage(points, threshold_percent=20.0)
    assert len(opps) == 1
    assert opps[0].buy_price == 200.0  # Took the lower price
