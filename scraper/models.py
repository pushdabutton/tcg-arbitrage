"""Data models for TCG price scraping."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Platform(str, Enum):
    """Supported pricing platforms."""

    PRICECHARTING = "pricecharting"
    TCGPLAYER = "tcgplayer"
    EBAY = "ebay"
    CARDMARKET = "cardmarket"


class Condition(str, Enum):
    """Card condition grades."""

    NEAR_MINT = "near_mint"
    LIGHTLY_PLAYED = "lightly_played"
    MODERATELY_PLAYED = "moderately_played"
    HEAVILY_PLAYED = "heavily_played"
    DAMAGED = "damaged"
    UNGRADED = "ungraded"


@dataclass
class Card:
    """A Pokemon card identified by name and set."""

    name: str
    set_name: str
    card_number: str = ""
    # URL-friendly slug used for scraping
    pricecharting_id: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.set_name})"


@dataclass
class PricePoint:
    """A single price observation from one platform."""

    card_name: str
    set_name: str
    platform: Platform
    price_usd: float
    condition: Condition = Condition.UNGRADED
    url: str = ""
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def display_price(self) -> str:
        return f"${self.price_usd:.2f}"


@dataclass
class ArbitrageOpportunity:
    """A detected price difference across platforms."""

    card_name: str
    set_name: str
    buy_platform: Platform
    buy_price: float
    sell_platform: Platform
    sell_price: float
    buy_url: str = ""
    sell_url: str = ""
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def spread_usd(self) -> float:
        return self.sell_price - self.buy_price

    @property
    def spread_percent(self) -> float:
        if self.sell_price == 0:
            return 0.0
        return ((self.sell_price - self.buy_price) / self.sell_price) * 100.0

    @property
    def display_spread(self) -> str:
        return f"${self.spread_usd:.2f} ({self.spread_percent:.1f}%)"
