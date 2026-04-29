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
    """Card condition grades.

    Raw card conditions: UNGRADED, NEAR_MINT, LIGHTLY_PLAYED, etc.
    Graded slab conditions: PSA_10, PSA_9_5, PSA_9, PSA_8, PSA_7.
    These are fundamentally different products and must never be compared.
    """

    # Raw card conditions
    NEAR_MINT = "near_mint"
    LIGHTLY_PLAYED = "lightly_played"
    MODERATELY_PLAYED = "moderately_played"
    HEAVILY_PLAYED = "heavily_played"
    DAMAGED = "damaged"
    UNGRADED = "ungraded"

    # Graded slab conditions (different product category)
    PSA_10 = "psa_10"
    PSA_9_5 = "psa_9_5"
    PSA_9 = "psa_9"
    PSA_8 = "psa_8"
    PSA_7 = "psa_7"

    @property
    def is_graded(self) -> bool:
        """Return True if this condition represents a graded slab."""
        return self in (
            Condition.PSA_10,
            Condition.PSA_9_5,
            Condition.PSA_9,
            Condition.PSA_8,
            Condition.PSA_7,
        )

    @property
    def is_raw(self) -> bool:
        """Return True if this condition represents a raw (ungraded) card."""
        return not self.is_graded

    @property
    def display_label(self) -> str:
        """Short label for display in the UI."""
        labels = {
            "ungraded": "Raw",
            "near_mint": "NM",
            "lightly_played": "LP",
            "moderately_played": "MP",
            "heavily_played": "HP",
            "damaged": "DMG",
            "psa_10": "PSA10",
            "psa_9_5": "PSA9.5",
            "psa_9": "PSA9",
            "psa_8": "PSA8",
            "psa_7": "PSA7",
        }
        return labels.get(self.value, self.value)


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
