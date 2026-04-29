"""eBay scraper -- extracts sold/completed listing prices.

Uses eBay's public sold listings page (no API key required).
Handles modern eBay HTML with robust selectors and anti-bot headers.
"""

from __future__ import annotations

import asyncio
import logging
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from config import settings
from engine.database import get_cache, set_cache
from scraper.models import Card, Condition, Platform, PricePoint

logger = logging.getLogger(__name__)

SOLD_URL = "https://www.ebay.com/sch/i.html"

# eBay-specific headers to reduce bot detection
EBAY_HEADERS = {
    "User-Agent": settings.USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def _parse_price(text: str) -> float | None:
    """Extract dollar amount from text like '$12.34' or 'US $1,234.56'."""
    text = text.strip()
    # Remove currency prefixes like "US " or "C "
    text = re.sub(r"^[A-Z]{1,3}\s*", "", text)
    match = re.search(r"\$?([\d,]+\.?\d*)", text.replace(",", ""))
    if match:
        try:
            val = float(match.group(1))
            return val if val > 0 else None
        except ValueError:
            return None
    return None


def _parse_date(text: str) -> datetime | None:
    """Parse eBay date strings like 'Apr 28, 2026' or 'Sold  Apr 28, 2026'."""
    text = text.strip()
    # Remove "Sold" prefix
    text = re.sub(r"^Sold\s+", "", text, flags=re.IGNORECASE)
    # Try common eBay date formats
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _extract_prices_from_html(html: str) -> list[dict]:
    """Extract sold listing data from eBay search results HTML.

    Returns list of dicts with 'price', 'title', 'date' keys.
    """
    soup = BeautifulSoup(html, "html.parser")
    items_data: list[dict] = []

    # Strategy 1: Modern eBay (2024+) uses s-item class
    items = soup.find_all("li", class_=re.compile(r"s-item"))

    for item in items:
        # Skip the first "shop on eBay" placeholder item
        title_el = item.find("div", class_="s-item__title")
        if title_el:
            title_text = title_el.get_text(strip=True).lower()
            if "shop on ebay" in title_text:
                continue

        # Extract price
        price_el = item.find("span", class_="s-item__price")
        if not price_el:
            continue
        price_text = price_el.get_text(strip=True)

        # Skip "price range" listings (auctions with best offer)
        if " to " in price_text:
            # Take the lower bound for range prices
            parts = price_text.split(" to ")
            price = _parse_price(parts[0])
        else:
            price = _parse_price(price_text)

        if price is None or price <= 0:
            continue

        # Extract date (if available)
        date_el = item.find("span", class_=re.compile(r"s-item__endedDate|s-item__ended-date|POSITIVE"))
        sold_date = None
        if date_el:
            sold_date = _parse_date(date_el.get_text(strip=True))

        # Extract title
        title = ""
        if title_el:
            title = title_el.get_text(strip=True)

        items_data.append({
            "price": price,
            "title": title,
            "date": sold_date,
        })

    # Strategy 2: Try data attribute selectors (newer eBay layout)
    if not items_data:
        results = soup.find_all("div", attrs={"data-viewport": True})
        for result in results:
            price_el = result.find("span", class_=re.compile(r"price|prc"))
            if not price_el:
                continue
            price = _parse_price(price_el.get_text(strip=True))
            if price and price > 0:
                items_data.append({"price": price, "title": "", "date": None})

    return items_data


def _filter_outliers(prices: list[float]) -> list[float]:
    """Remove outlier prices using IQR method.

    Filters out prices that are likely wrong listings (bundles, mispriced, etc).
    """
    if len(prices) < 4:
        return prices

    sorted_p = sorted(prices)
    q1_idx = len(sorted_p) // 4
    q3_idx = (3 * len(sorted_p)) // 4
    q1 = sorted_p[q1_idx]
    q3 = sorted_p[q3_idx]
    iqr = q3 - q1

    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr

    filtered = [p for p in prices if lower_bound <= p <= upper_bound]
    return filtered if filtered else prices  # Fallback to all if filter removes everything


async def scrape_card(
    client: httpx.AsyncClient,
    card: Card,
    use_cache: bool = True,
) -> list[PricePoint]:
    """Scrape eBay sold listings for a card.

    Returns the median price from recent sold listings.
    Caches results for 1 hour to respect rate limits.
    """
    query = f"pokemon {card.name} {card.set_name} card"
    params = {
        "_nkw": query,
        "LH_Complete": "1",  # Completed listings
        "LH_Sold": "1",  # Sold only
        "_sop": "13",  # Sort by end date: recent first
        "_ipg": "60",  # Items per page
    }

    # Build the full URL for caching
    from urllib.parse import urlencode
    cache_url = f"{SOLD_URL}?{urlencode(params)}"

    results: list[PricePoint] = []
    now = datetime.now(timezone.utc)
    html: str | None = None

    # Check cache first
    if use_cache:
        cached = get_cache(settings.DB_PATH, cache_url, settings.CACHE_TTL_SECONDS)
        if cached:
            logger.debug("Using cached eBay results for %s", card.display_name)
            html = cached

    if html is None:
        try:
            resp = await client.get(SOLD_URL, params=params)
            resp.raise_for_status()
            html = resp.text
            # Cache the response
            set_cache(settings.DB_PATH, cache_url, html)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "HTTP %s for eBay search: %s", exc.response.status_code, query
            )
            return []
        except httpx.RequestError as exc:
            logger.error("Request error for eBay search: %s", exc)
            return []

    # Parse the HTML
    items_data = _extract_prices_from_html(html)

    if not items_data:
        logger.debug("No eBay sold listings found for %s", query)
        return []

    # Take first 20 results max
    items_data = items_data[:20]

    # Extract just the prices
    all_prices = [item["price"] for item in items_data]

    # Filter outliers
    filtered_prices = _filter_outliers(all_prices)

    if filtered_prices:
        median_price = round(statistics.median(filtered_prices), 2)

        results.append(
            PricePoint(
                card_name=card.name,
                set_name=card.set_name,
                platform=Platform.EBAY,
                price_usd=median_price,
                condition=Condition.UNGRADED,
                url=cache_url,
                scraped_at=now,
            )
        )
        logger.info(
            "eBay: %s = $%.2f (median of %d listings, %d after outlier filter)",
            card.display_name,
            median_price,
            len(all_prices),
            len(filtered_prices),
        )
    else:
        logger.debug("No valid eBay prices for %s after filtering", query)

    return results


async def scrape_cards(
    cards: list[Card],
    delay: float | None = None,
    use_cache: bool = True,
) -> list[PricePoint]:
    """Scrape eBay sold prices for multiple cards with rate limiting."""
    if delay is None:
        delay = settings.SCRAPE_DELAY_SECONDS

    all_results: list[PricePoint] = []

    async with httpx.AsyncClient(
        headers=EBAY_HEADERS,
        timeout=settings.REQUEST_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for i, card in enumerate(cards):
            logger.info(
                "[%d/%d] eBay: %s ...", i + 1, len(cards), card.display_name
            )
            card_results = await scrape_card(client, card, use_cache=use_cache)
            all_results.extend(card_results)
            if i < len(cards) - 1:
                await asyncio.sleep(delay)

    logger.info(
        "eBay: %d price points from %d cards", len(all_results), len(cards)
    )
    return all_results
