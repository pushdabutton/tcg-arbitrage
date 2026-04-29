"""TCGPlayer scraper -- uses TCGPlayer's internal search API.

TCGPlayer's website is fully client-rendered (React), so HTML scraping
returns no useful data. Instead, we use their marketplace search API
(mp-search-api.tcgplayer.com) which is the same API their frontend calls.

This returns structured JSON with marketPrice, lowestPrice, productName,
setName, and totalListings for each card.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus

import httpx

from config import settings
from engine.database import get_cache, set_cache
from scraper.models import Card, Condition, Platform, PricePoint

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://mp-search-api.tcgplayer.com/v1/search/request"

# Headers that mimic the TCGPlayer frontend's API requests
TCGP_API_HEADERS = {
    "User-Agent": settings.USER_AGENT,
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.tcgplayer.com",
    "Referer": "https://www.tcgplayer.com/",
}


def _build_search_payload(size: int = 5) -> dict:
    """Build the search request payload matching TCGPlayer's frontend format."""
    return {
        "algorithm": "sales_synonym_v2",
        "from": 0,
        "size": size,
        "filters": {
            "term": {"productLineName": ["pokemon"]},
            "range": {},
            "match": {},
        },
        "listingSearch": {
            "filters": {
                "term": {},
                "range": {},
                "exclude": {"channelExclusion": 0},
            }
        },
        "context": {
            "cart": {},
            "shippingCountry": "US",
            "userProfile": {},
        },
        "settings": {"useFuzzySearch": True, "didYouMean": {}},
        "sort": {},
    }


def _build_product_url(product_name: str, set_url_name: str, product_id: float) -> str:
    """Build TCGPlayer product page URL from API data."""
    # TCGPlayer product URL pattern: /product/{id}/pokemon-{set}-{name}
    slug = f"{set_url_name}-{product_name}".lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    return f"https://www.tcgplayer.com/product/{int(product_id)}/pokemon-{slug}"


def _extract_best_match(
    results: list[dict],
    card: Card,
) -> dict | None:
    """Find the best matching product from search results.

    Matches by card name and set name. Prefers exact matches.
    """
    card_name_lower = card.name.lower().strip()
    set_name_lower = card.set_name.lower().strip()

    scored: list[tuple[int, dict]] = []

    for result in results:
        product_name = (result.get("productName") or "").lower().strip()
        set_name = (result.get("setName") or "").lower().strip()

        # Skip if no market price
        if not result.get("marketPrice") and not result.get("lowestPrice"):
            continue

        name_score = 0
        set_score = 0

        # Exact name match
        if product_name == card_name_lower:
            name_score = 10
        elif card_name_lower in product_name:
            name_score = 5

        # Exact set match
        if set_name == set_name_lower:
            set_score = 10
        elif set_name_lower in set_name:
            set_score = 5

        # Require at least a name match to consider this result
        if name_score > 0 and (name_score + set_score) > 0:
            scored.append((name_score + set_score, result))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


async def scrape_card(
    client: httpx.AsyncClient,
    card: Card,
    use_cache: bool = True,
) -> list[PricePoint]:
    """Scrape TCGPlayer price data for a card via their search API.

    Returns PricePoint list (typically 1 entry with market price, or empty).
    """
    query = f"{card.name} {card.set_name}"
    cache_key = f"tcgplayer_api:{query}"

    results: list[PricePoint] = []
    now = datetime.now(timezone.utc)

    # Check cache first
    if use_cache:
        cached = get_cache(settings.DB_PATH, cache_key, settings.CACHE_TTL_SECONDS)
        if cached:
            logger.debug("Using cached TCGPlayer API results for %s", card.display_name)
            try:
                api_results = json.loads(cached)
                return _process_api_results(api_results, card, now)
            except (json.JSONDecodeError, KeyError):
                logger.debug("Cache parse error, fetching fresh")

    # Make API request
    search_url = f"{SEARCH_API_URL}?q={quote_plus(query)}&isList=false"
    payload = _build_search_payload(size=5)

    try:
        resp = await client.post(search_url, json=payload)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "HTTP %s for TCGPlayer API search: %s",
            exc.response.status_code,
            query,
        )
        return []
    except httpx.RequestError as exc:
        logger.error("Request error for TCGPlayer API: %s", exc)
        return []

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        logger.error("Failed to parse TCGPlayer API JSON for %s", query)
        return []

    # Extract the search results
    try:
        result_sets = data.get("results", [])
        if not result_sets:
            logger.debug("No result sets from TCGPlayer API for %s", query)
            return []

        api_results = result_sets[0].get("results", [])
    except (IndexError, KeyError, TypeError):
        logger.debug("Unexpected TCGPlayer API response structure for %s", query)
        return []

    # Cache the raw results
    try:
        set_cache(settings.DB_PATH, cache_key, json.dumps(api_results))
    except Exception:
        logger.debug("Failed to cache TCGPlayer API results")

    return _process_api_results(api_results, card, now)


def _process_api_results(
    api_results: list[dict],
    card: Card,
    now: datetime,
) -> list[PricePoint]:
    """Process TCGPlayer API results into PricePoints."""
    results: list[PricePoint] = []

    best_match = _extract_best_match(api_results, card)
    if not best_match:
        logger.debug("No matching TCGPlayer result for %s", card.display_name)
        return []

    market_price = best_match.get("marketPrice")
    lowest_price = best_match.get("lowestPrice")
    product_name = best_match.get("productName", card.name)
    set_name = best_match.get("setName", card.set_name)
    set_url = best_match.get("setUrlName", "")
    product_id = best_match.get("productId", 0)
    total_listings = best_match.get("totalListings", 0)

    # Build product URL
    url = _build_product_url(product_name, set_url, product_id)

    # Use market price if available, otherwise lowest price
    price = market_price if market_price and market_price > 0 else lowest_price

    if price and price > 0:
        results.append(
            PricePoint(
                card_name=card.name,
                set_name=card.set_name,
                platform=Platform.TCGPLAYER,
                price_usd=round(price, 2),
                condition=Condition.NEAR_MINT,
                url=url,
                scraped_at=now,
            )
        )
        logger.info(
            "TCGPlayer: %s = $%.2f (market) / $%.2f (low) [%d listings]",
            card.display_name,
            market_price or 0,
            lowest_price or 0,
            int(total_listings),
        )
    else:
        logger.debug("No valid price for %s from TCGPlayer API", card.display_name)

    return results


async def scrape_cards(
    cards: list[Card],
    delay: float | None = None,
    use_cache: bool = True,
) -> list[PricePoint]:
    """Scrape prices for multiple cards via TCGPlayer API with rate limiting."""
    if delay is None:
        delay = settings.SCRAPE_DELAY_SECONDS

    all_results: list[PricePoint] = []

    async with httpx.AsyncClient(
        headers=TCGP_API_HEADERS,
        timeout=settings.REQUEST_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for i, card in enumerate(cards):
            logger.info(
                "[%d/%d] TCGPlayer: %s ...", i + 1, len(cards), card.display_name
            )
            card_results = await scrape_card(client, card, use_cache=use_cache)
            all_results.extend(card_results)
            if i < len(cards) - 1:
                await asyncio.sleep(delay)

    logger.info(
        "TCGPlayer: %d price points from %d cards", len(all_results), len(cards)
    )
    return all_results
