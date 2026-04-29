"""PriceCharting scraper -- primary data source for MVP.

URL pattern: https://www.pricecharting.com/game/{pricecharting_id}

PriceCharting's price table for Pokemon cards has columns:
    Ungraded | Grade 7 | Grade 8 | Grade 9 | Grade 9.5 | PSA 10

Prices are in td elements with specific IDs:
    used_price     = Ungraded card price
    complete_price = Grade 7 price
    new_price      = Grade 8 price
    graded_price   = Grade 9 price
    box_only_price = Grade 9.5 price
    manual_only_price = PSA 10 price

For video games these IDs mean different things, but for Pokemon cards
they map to grading tiers. We focus on used_price (ungraded) as the
primary comparable price, plus graded_price for graded comparisons.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from config import settings
from scraper.models import Card, Condition, Platform, PricePoint

logger = logging.getLogger(__name__)

BASE_URL = "https://www.pricecharting.com/game"

# Map PriceCharting price element IDs to card conditions.
# For Pokemon cards, PriceCharting reuses their video game price IDs:
#   used_price        -> Ungraded raw card
#   complete_price    -> Grade 7 slab (PSA 7)
#   new_price         -> Grade 8 slab (PSA 8)
#   graded_price      -> Grade 9 slab (PSA 9)
#   box_only_price    -> Grade 9.5 slab (PSA 9.5)
#   manual_only_price -> PSA 10 slab
#
# CRITICAL: Graded slabs are a fundamentally different product from raw cards.
# A PSA 10 Charizard ($1,482) is NOT the same as a raw Charizard ($26).
# We must separate these into distinct condition categories.
PRICE_ID_MAP = {
    "used_price": Condition.UNGRADED,           # Raw ungraded card
    "complete_price": Condition.PSA_7,           # Grade 7 slab
    "new_price": Condition.PSA_8,                # Grade 8 slab
    "graded_price": Condition.PSA_9,             # Grade 9 slab
    "box_only_price": Condition.PSA_9_5,         # Grade 9.5 slab
    "manual_only_price": Condition.PSA_10,       # PSA 10 slab
}


def _parse_price(text: str) -> float | None:
    """Extract a dollar amount from text like '$12.34' or 'N/A'."""
    text = text.strip()
    match = re.search(r"\$?([\d,]+\.?\d*)", text.replace(",", ""))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _map_condition(label: str) -> Condition | None:
    """Map PriceCharting condition labels to our enum.

    Returns None for entries that are not actual card prices.
    Graded slabs get their own PSA_* conditions (not lumped with raw cards).
    """
    label = label.lower().strip()
    if "ungraded" in label:
        return Condition.UNGRADED
    if "psa 10" in label or "gem mint" in label:
        return Condition.PSA_10
    if "grade 9.5" in label or "9.5" in label:
        return Condition.PSA_9_5
    if "grade 9" in label:
        return Condition.PSA_9
    if "grade 8" in label:
        return Condition.PSA_8
    if "grade 7" in label:
        return Condition.PSA_7
    if "grade" in label or "graded" in label or "psa" in label:
        return Condition.PSA_9  # Default graded to PSA 9
    if "1st edition" in label:
        return Condition.NEAR_MINT
    if "complete" in label:
        return Condition.UNGRADED
    if "new" in label or "sealed" in label:
        return Condition.NEAR_MINT
    if "used" in label or "loose" in label:
        return Condition.LIGHTLY_PLAYED
    if "box only" in label or "manual only" in label:
        return None
    return Condition.UNGRADED


async def scrape_card(
    client: httpx.AsyncClient,
    card: Card,
) -> list[PricePoint]:
    """Scrape price data for a single card from PriceCharting.

    Returns a list of PricePoint objects. Focuses on the ungraded price
    as the primary comparable price across platforms.
    """
    if not card.pricecharting_id:
        logger.warning("No pricecharting_id for %s", card.display_name)
        return []

    url = f"{BASE_URL}/{card.pricecharting_id}"
    results: list[PricePoint] = []

    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "HTTP %s for %s: %s", exc.response.status_code, url, exc
        )
        return []
    except httpx.RequestError as exc:
        logger.error("Request error for %s: %s", url, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    now = datetime.now(timezone.utc)

    # Primary strategy: Use specific price element IDs
    # These are the most reliable way to extract prices from PriceCharting
    for price_id, condition in PRICE_ID_MAP.items():
        el = soup.find(id=price_id)
        if el:
            # The price is in a span with class "price js-price" inside the td
            price_span = el.find("span", class_="price")
            if price_span:
                price = _parse_price(price_span.get_text())
            else:
                # Fallback: try the first js-price span (but not the change span)
                price_span = el.find("span", class_="js-price")
                if price_span:
                    price = _parse_price(price_span.get_text())
                else:
                    price = _parse_price(el.get_text())

            if price is not None and price > 0:
                results.append(
                    PricePoint(
                        card_name=card.name,
                        set_name=card.set_name,
                        platform=Platform.PRICECHARTING,
                        price_usd=price,
                        condition=condition,
                        url=url,
                        scraped_at=now,
                    )
                )

    # If we got no results from price IDs, try the table headers approach
    if not results:
        price_table = soup.find("table", id="price_data")
        if price_table:
            # Get headers from thead
            headers = []
            thead = price_table.find("thead")
            if thead:
                header_row = thead.find("tr")
                if header_row:
                    headers = [
                        th.get_text(strip=True)
                        for th in header_row.find_all("th")
                    ]

            # Get prices from first tbody row
            tbody = price_table.find("tbody")
            if tbody:
                data_row = tbody.find("tr")
                if data_row:
                    cells = data_row.find_all("td")
                    for i, cell in enumerate(cells):
                        price_span = cell.find("span", class_="price")
                        if not price_span:
                            price_span = cell.find("span", class_="js-price")
                        if price_span:
                            price = _parse_price(price_span.get_text())
                            if price is not None and price > 0:
                                # Map header to condition
                                label = headers[i] if i < len(headers) else ""
                                condition = _map_condition(label)
                                if condition is not None:
                                    results.append(
                                        PricePoint(
                                            card_name=card.name,
                                            set_name=card.set_name,
                                            platform=Platform.PRICECHARTING,
                                            price_usd=price,
                                            condition=condition,
                                            url=url,
                                            scraped_at=now,
                                        )
                                    )

    if not results:
        logger.warning("No prices found for %s at %s", card.display_name, url)
    else:
        # Log the primary (ungraded) price
        ungraded = next(
            (r for r in results if r.condition == Condition.UNGRADED),
            results[0],
        )
        logger.info(
            "PriceCharting: %s = %s (%s)",
            card.display_name,
            ungraded.display_price,
            ungraded.condition.value,
        )

    return results


async def scrape_cards(
    cards: list[Card],
    delay: float | None = None,
) -> list[PricePoint]:
    """Scrape prices for multiple cards with rate limiting.

    Args:
        cards: List of Card objects to scrape.
        delay: Seconds between requests. Defaults to settings.SCRAPE_DELAY_SECONDS.

    Returns:
        Flat list of all PricePoint results.
    """
    if delay is None:
        delay = settings.SCRAPE_DELAY_SECONDS

    all_results: list[PricePoint] = []

    async with httpx.AsyncClient(
        headers={"User-Agent": settings.USER_AGENT},
        timeout=settings.REQUEST_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for i, card in enumerate(cards):
            logger.info(
                "[%d/%d] PriceCharting: %s ...",
                i + 1,
                len(cards),
                card.display_name,
            )
            card_results = await scrape_card(client, card)
            all_results.extend(card_results)
            if i < len(cards) - 1:
                await asyncio.sleep(delay)

    logger.info(
        "PriceCharting: %d price points from %d cards",
        len(all_results),
        len(cards),
    )
    return all_results
