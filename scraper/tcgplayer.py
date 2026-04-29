"""TCGPlayer scraper -- secondary data source.

TCGPlayer closed their API but public product pages are still accessible.
We use search to find cards and extract market/low prices.
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

SEARCH_URL = "https://www.tcgplayer.com/search/pokemon/product"


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


async def scrape_card(
    client: httpx.AsyncClient,
    card: Card,
) -> list[PricePoint]:
    """Scrape TCGPlayer search results for a card.

    Returns PricePoint list (may be empty if page structure changed).
    """
    query = f"{card.name} {card.set_name}"
    params = {
        "q": query,
        "view": "grid",
    }

    results: list[PricePoint] = []
    now = datetime.now(timezone.utc)

    try:
        resp = await client.get(SEARCH_URL, params=params)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("HTTP %s for TCGPlayer search: %s", exc.response.status_code, query)
        return []
    except httpx.RequestError as exc:
        logger.error("Request error for TCGPlayer search: %s", exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # TCGPlayer renders search results with JS, so we may get limited data
    # from the initial HTML. Look for price elements in the first result card.
    product_cards = soup.find_all("div", class_=re.compile(r"search-result"))
    if not product_cards:
        # Try alternate selectors
        product_cards = soup.find_all("div", attrs={"data-testid": re.compile(r"product")})

    if not product_cards:
        logger.debug("No TCGPlayer results for %s (JS-rendered page)", query)
        return []

    # Take the first matching result
    first = product_cards[0]

    # Look for market price and low price
    for price_el in first.find_all(string=re.compile(r"\$\d")):
        price = _parse_price(str(price_el))
        if price and price > 0:
            # Try to determine if this is market or low
            parent_text = ""
            if price_el.parent:
                parent_text = price_el.parent.get_text(strip=True).lower()

            product_link = first.find("a", href=True)
            url = ""
            if product_link:
                href = product_link["href"]
                if href.startswith("/"):
                    url = f"https://www.tcgplayer.com{href}"
                else:
                    url = href

            results.append(
                PricePoint(
                    card_name=card.name,
                    set_name=card.set_name,
                    platform=Platform.TCGPLAYER,
                    price_usd=price,
                    condition=Condition.NEAR_MINT,
                    url=url,
                    scraped_at=now,
                )
            )
            break  # Take only the first price to avoid duplicates

    if not results:
        logger.debug("No prices extracted from TCGPlayer for %s", query)

    return results


async def scrape_cards(
    cards: list[Card],
    delay: float | None = None,
) -> list[PricePoint]:
    """Scrape prices for multiple cards with rate limiting."""
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
                "[%d/%d] TCGPlayer: %s ...", i + 1, len(cards), card.display_name
            )
            results = await scrape_card(client, card)
            all_results.extend(results)
            if i < len(cards) - 1:
                await asyncio.sleep(delay)

    logger.info(
        "TCGPlayer: %d price points from %d cards", len(all_results), len(cards)
    )
    return all_results
