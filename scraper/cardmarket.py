"""Cardmarket (EU) scraper -- European pricing data.

Cardmarket has structured product pages for Pokemon singles.
Prices are in EUR; we convert to USD with a fixed rate for MVP.
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

# Approximate EUR->USD rate (MVP; replace with live rate later)
EUR_TO_USD = 1.08

SEARCH_URL = "https://www.cardmarket.com/en/Pokemon/Products/Search"


async def scrape_card(
    client: httpx.AsyncClient,
    card: Card,
) -> list[PricePoint]:
    """Scrape Cardmarket search for a card's trend price."""
    query = f"{card.name} {card.set_name}"
    params = {"searchString": query}

    results: list[PricePoint] = []
    now = datetime.now(timezone.utc)

    try:
        resp = await client.get(SEARCH_URL, params=params)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "HTTP %s for Cardmarket search: %s", exc.response.status_code, query
        )
        return []
    except httpx.RequestError as exc:
        logger.error("Request error for Cardmarket: %s", exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Cardmarket shows results in a table with trend prices
    rows = soup.find_all("div", class_=re.compile(r"col-price|price-container"))
    if not rows:
        # Try alternate: look for any EUR price in results
        rows = soup.find_all(string=re.compile(r"\d+[.,]\d{2}\s*€"))

    for price_text in rows[:3]:
        text = price_text.get_text() if hasattr(price_text, "get_text") else str(price_text)
        eur_price = _parse_eur_price(text)
        if eur_price and eur_price > 0:
            usd_price = round(eur_price * EUR_TO_USD, 2)

            results.append(
                PricePoint(
                    card_name=card.name,
                    set_name=card.set_name,
                    platform=Platform.CARDMARKET,
                    price_usd=usd_price,
                    condition=Condition.NEAR_MINT,
                    url=str(resp.url),
                    scraped_at=now,
                )
            )
            break  # Take only first match

    if not results:
        logger.debug("No Cardmarket prices for %s", query)

    return results


def _parse_eur_price(text: str) -> float | None:
    """Extract a EUR amount from text like '12,34 EUR' or '12.34€'."""
    text = text.strip()
    # Handle European decimal format: 12,34
    match = re.search(r"([\d.]+[,.]?\d*)\s*€|EUR\s*([\d.]+[,.]?\d*)", text)
    if match:
        val = match.group(1) or match.group(2)
        if val:
            # Normalize: replace comma decimal separator
            val = val.replace(".", "").replace(",", ".") if "," in val else val
            try:
                return float(val)
            except ValueError:
                return None
    return None


async def scrape_cards(
    cards: list[Card],
    delay: float | None = None,
) -> list[PricePoint]:
    """Scrape Cardmarket prices for multiple cards."""
    if delay is None:
        delay = settings.SCRAPE_DELAY_SECONDS

    all_results: list[PricePoint] = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": settings.USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=settings.REQUEST_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for i, card in enumerate(cards):
            logger.info(
                "[%d/%d] Cardmarket: %s ...", i + 1, len(cards), card.display_name
            )
            results = await scrape_card(client, card)
            all_results.extend(results)
            if i < len(cards) - 1:
                await asyncio.sleep(delay)

    logger.info(
        "Cardmarket: %d price points from %d cards", len(all_results), len(cards)
    )
    return all_results
