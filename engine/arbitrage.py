"""Arbitrage detection engine.

Compares prices across platforms and flags opportunities where the same card
has a significant price difference (configurable threshold, default 20%).

CRITICAL: Only compares like-for-like conditions. A PSA 10 graded slab is a
fundamentally different product from a raw/ungraded card and must never be
compared against it. Prices are grouped by (card, set, condition_group)
before cross-platform comparison.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations

from config import settings
from scraper.models import ArbitrageOpportunity, Condition, Platform, PricePoint

logger = logging.getLogger(__name__)


def _condition_group(condition: Condition) -> str:
    """Map a condition to its comparison group.

    Raw cards (Ungraded, NM, LP, MP, HP, Damaged) compare with each other.
    Each graded slab tier only compares within its own tier.

    Returns a string key for grouping.
    """
    if condition.is_graded:
        return condition.value  # Each grade is its own group
    return "raw"  # All raw conditions compare together


def detect_arbitrage(
    price_points: list[PricePoint],
    threshold_percent: float | None = None,
) -> list[ArbitrageOpportunity]:
    """Find arbitrage opportunities across platforms.

    Groups price points by (card, set, condition_group), then compares
    every platform pair within each group. Only compares like-for-like:
    raw vs raw, PSA 10 vs PSA 10, etc.

    An opportunity exists when the price on platform A is at least
    `threshold_percent`% lower than on platform B.

    Args:
        price_points: All collected price data.
        threshold_percent: Minimum spread to flag. Defaults to settings value.

    Returns:
        List of ArbitrageOpportunity sorted by spread_percent descending.
    """
    if threshold_percent is None:
        threshold_percent = settings.ARBITRAGE_THRESHOLD_PERCENT

    # Group by (card_name, set_name, condition_group) -> list of price points
    groups: dict[tuple[str, str, str], list[PricePoint]] = defaultdict(list)
    for pp in price_points:
        cg = _condition_group(pp.condition)
        key = (pp.card_name, pp.set_name, cg)
        groups[key].append(pp)

    opportunities: list[ArbitrageOpportunity] = []

    for (card_name, set_name, cond_group), points in groups.items():
        # Get best (lowest) price per platform within this condition group
        best_by_platform: dict[Platform, PricePoint] = {}
        for pp in points:
            existing = best_by_platform.get(pp.platform)
            if existing is None or pp.price_usd < existing.price_usd:
                best_by_platform[pp.platform] = pp

        if len(best_by_platform) < 2:
            continue  # Need at least 2 platforms to compare

        # Compare every pair
        for plat_a, plat_b in combinations(best_by_platform.keys(), 2):
            pp_a = best_by_platform[plat_a]
            pp_b = best_by_platform[plat_b]

            # Check A cheaper than B (buy A, sell B)
            if pp_b.price_usd > 0:
                spread_pct = ((pp_b.price_usd - pp_a.price_usd) / pp_b.price_usd) * 100
                if spread_pct >= threshold_percent:
                    opp = ArbitrageOpportunity(
                        card_name=card_name,
                        set_name=set_name,
                        buy_platform=plat_a,
                        buy_price=pp_a.price_usd,
                        sell_platform=plat_b,
                        sell_price=pp_b.price_usd,
                        buy_url=pp_a.url,
                        sell_url=pp_b.url,
                    )
                    opportunities.append(opp)
                    logger.info(
                        "ARBITRAGE: %s (%s) [%s] -- Buy on %s @ $%.2f, Sell on %s @ $%.2f [%.1f%%]",
                        card_name,
                        set_name,
                        cond_group,
                        plat_a.value,
                        pp_a.price_usd,
                        plat_b.value,
                        pp_b.price_usd,
                        spread_pct,
                    )

            # Check B cheaper than A (buy B, sell A)
            if pp_a.price_usd > 0:
                spread_pct = ((pp_a.price_usd - pp_b.price_usd) / pp_a.price_usd) * 100
                if spread_pct >= threshold_percent:
                    opp = ArbitrageOpportunity(
                        card_name=card_name,
                        set_name=set_name,
                        buy_platform=plat_b,
                        buy_price=pp_b.price_usd,
                        sell_platform=plat_a,
                        sell_price=pp_a.price_usd,
                        buy_url=pp_b.url,
                        sell_url=pp_a.url,
                    )
                    opportunities.append(opp)
                    logger.info(
                        "ARBITRAGE: %s (%s) [%s] -- Buy on %s @ $%.2f, Sell on %s @ $%.2f [%.1f%%]",
                        card_name,
                        set_name,
                        cond_group,
                        plat_b.value,
                        pp_b.price_usd,
                        plat_a.value,
                        pp_a.price_usd,
                        spread_pct,
                    )

    # Sort by largest spread first
    opportunities.sort(key=lambda o: o.spread_percent, reverse=True)

    logger.info(
        "Found %d arbitrage opportunities from %d card/condition groups across %d platforms",
        len(opportunities),
        len(groups),
        len({pp.platform for pp in price_points}),
    )

    return opportunities
