"""Tests for data models."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.models import (
    ArbitrageOpportunity,
    Card,
    Condition,
    Platform,
    PricePoint,
)


def test_card_display_name():
    card = Card(name="Charizard", set_name="Base Set")
    assert card.display_name == "Charizard (Base Set)"


def test_price_point_display_price():
    pp = PricePoint(
        card_name="Pikachu",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=42.50,
    )
    assert pp.display_price == "$42.50"


def test_arbitrage_spread_usd():
    opp = ArbitrageOpportunity(
        card_name="Mewtwo",
        set_name="Base Set",
        buy_platform=Platform.PRICECHARTING,
        buy_price=80.00,
        sell_platform=Platform.EBAY,
        sell_price=120.00,
    )
    assert opp.spread_usd == 40.00


def test_arbitrage_spread_percent():
    opp = ArbitrageOpportunity(
        card_name="Mewtwo",
        set_name="Base Set",
        buy_platform=Platform.PRICECHARTING,
        buy_price=80.00,
        sell_platform=Platform.EBAY,
        sell_price=100.00,
    )
    # (100 - 80) / 100 = 20%
    assert abs(opp.spread_percent - 20.0) < 0.01


def test_arbitrage_spread_zero_sell():
    opp = ArbitrageOpportunity(
        card_name="Mewtwo",
        set_name="Base Set",
        buy_platform=Platform.PRICECHARTING,
        buy_price=80.00,
        sell_platform=Platform.EBAY,
        sell_price=0.00,
    )
    assert opp.spread_percent == 0.0


def test_platform_values():
    assert Platform.PRICECHARTING.value == "pricecharting"
    assert Platform.TCGPLAYER.value == "tcgplayer"
    assert Platform.EBAY.value == "ebay"
    assert Platform.CARDMARKET.value == "cardmarket"


def test_condition_values():
    assert Condition.NEAR_MINT.value == "near_mint"
    assert Condition.UNGRADED.value == "ungraded"
