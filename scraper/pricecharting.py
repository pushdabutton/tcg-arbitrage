"""PriceCharting scraper -- primary data source for MVP.

URL pattern: https://www.pricecharting.com/game/{pricecharting_id}
The page contains a structured price table with conditions and prices.
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


def _map_condition(label: str) -> Condition:
    """Map PriceCharting condition labels to our enum."""
    label = label.lower().strip()
    if "ungraded" in label:
        return Condition.UNGRADED
    if "grade" in label or "graded" in label or "psa" in label:
        return Condition.NEAR_MINT  # graded cards are ~NM equivalent
    if "1st edition" in label:
        return Condition.NEAR_MINT
    # Default
    return Condition.UNGRADED


async def scrape_card(
    client: httpx.AsyncClient,
    card: Card,
) -> list[PricePoint]:
    """Scrape price data for a single card from PriceCharting.

    Returns a list of PricePoint objects (one per condition/variant found).
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

    # PriceCharting stores prices in a table with id="price_data"
    # or in individual price boxes with class "price"
    # Try the structured price table first
    price_table = soup.find("table", id="price_data")
    if price_table:
        for row in price_table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True)
                price_text = cells[1].get_text(strip=True)
                price = _parse_price(price_text)
                if price is not None and price > 0:
                    results.append(
                        PricePoint(
                            card_name=card.name,
                            set_name=card.set_name,
                            platform=Platform.PRICECHARTING,
                            price_usd=price,
                            condition=_map_condition(label),
                            url=url,
                            scraped_at=now,
                        )
                    )

    # Also try the js-price spans used on some pages
    if not results:
        price_spans = soup.find_all("span", class_="js-price")
        for span in price_spans:
            price = _parse_price(span.get_text())
            if price is not None and price > 0:
                # Try to find the label from parent or sibling
                parent_dt = span.find_parent("dt") or span.find_parent("div")
                label = ""
                if parent_dt:
                    prev = parent_dt.find_previous_sibling()
                    if prev:
                        label = prev.get_text(strip=True)

                results.append(
                    PricePoint(
                        card_name=card.name,
                        set_name=card.set_name,
                        platform=Platform.PRICECHARTING,
                        price_usd=price,
                        condition=_map_condition(label),
                        url=url,
                        scraped_at=now,
                    )
                )

    # Fallback: look for the main price display
    if not results:
        # Many pages show price in <span id="used_price"> or <span id="complete_price">
        for price_id in ("used_price", "complete_price", "new_price", "graded_price"):
            el = soup.find(id=price_id)
            if el:
                price = _parse_price(el.get_text())
                if price is not None and price > 0:
                    cond = Condition.UNGRADED
                    if "graded" in price_id:
                        cond = Condition.NEAR_MINT
                    results.append(
                        PricePoint(
                            card_name=card.name,
                            set_name=card.set_name,
                            platform=Platform.PRICECHARTING,
                            price_usd=price,
                            condition=cond,
                            url=url,
                            scraped_at=now,
                        )
                    )

    if not results:
        logger.warning("No prices found for %s at %s", card.display_name, url)

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
                "[%d/%d] Scraping %s ...", i + 1, len(cards), card.display_name
            )
            results = await scrape_card(client, card)
            all_results.extend(results)
            if i < len(cards) - 1:
                await asyncio.sleep(delay)

    logger.info(
        "Scraped %d price points from %d cards", len(all_results), len(cards)
    )
    return all_results
