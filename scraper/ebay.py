"""eBay scraper -- extracts sold/completed listing prices.

Uses eBay's public sold listings page (no API key required for MVP).
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

SOLD_URL = "https://www.ebay.com/sch/i.html"


async def scrape_card(
    client: httpx.AsyncClient,
    card: Card,
) -> list[PricePoint]:
    """Scrape eBay sold listings for a card.

    Returns the median-ish price from recent sold listings.
    """
    query = f"pokemon {card.name} {card.set_name} card"
    params = {
        "_nkw": query,
        "LH_Complete": "1",  # Completed listings
        "LH_Sold": "1",  # Sold only
        "_sop": "13",  # Sort by end date: recent first
    }

    results: list[PricePoint] = []
    now = datetime.now(timezone.utc)
    prices_found: list[float] = []

    try:
        resp = await client.get(SOLD_URL, params=params)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("HTTP %s for eBay search: %s", exc.response.status_code, query)
        return []
    except httpx.RequestError as exc:
        logger.error("Request error for eBay search: %s", exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # eBay sold listings have price in s-item__price spans
    items = soup.find_all("li", class_=re.compile(r"s-item"))

    for item in items[:10]:  # Only look at first 10 results
        price_el = item.find("span", class_="s-item__price")
        if not price_el:
            continue
        price_text = price_el.get_text(strip=True)
        # Handle range prices like "$10.00 to $20.00"
        if " to " in price_text:
            parts = price_text.split(" to ")
            for part in parts:
                val = _parse_price(part)
                if val and val > 0:
                    prices_found.append(val)
        else:
            val = _parse_price(price_text)
            if val and val > 0:
                prices_found.append(val)

    if prices_found:
        # Use median price as representative
        prices_found.sort()
        median = prices_found[len(prices_found) // 2]

        search_url = str(resp.url)

        results.append(
            PricePoint(
                card_name=card.name,
                set_name=card.set_name,
                platform=Platform.EBAY,
                price_usd=round(median, 2),
                condition=Condition.UNGRADED,
                url=search_url,
                scraped_at=now,
            )
        )
    else:
        logger.debug("No eBay sold prices for %s", query)

    return results


def _parse_price(text: str) -> float | None:
    """Extract dollar amount from text."""
    text = text.strip()
    match = re.search(r"\$?([\d,]+\.?\d*)", text.replace(",", ""))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


async def scrape_cards(
    cards: list[Card],
    delay: float | None = None,
) -> list[PricePoint]:
    """Scrape eBay sold prices for multiple cards."""
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
                "[%d/%d] eBay: %s ...", i + 1, len(cards), card.display_name
            )
            results = await scrape_card(client, card)
            all_results.extend(results)
            if i < len(cards) - 1:
                await asyncio.sleep(delay)

    logger.info(
        "eBay: %d price points from %d cards", len(all_results), len(cards)
    )
    return all_results
