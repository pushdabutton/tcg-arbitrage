"""FastAPI routes for the TCG Arbitrage dashboard."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from config import settings
from engine.alerter import get_current_alerts, store_alerts
from engine.arbitrage import detect_arbitrage
from engine.database import (
    dismiss_alert,
    get_all_tracked_cards,
    get_latest_prices,
    save_price_point,
)
from scraper.models import Platform, PricePoint
from scraper.ebay import scrape_cards as scrape_ebay
from scraper.pricecharting import scrape_cards as scrape_pricecharting
from scraper.tcgplayer import scrape_cards as scrape_tcgplayer
from scraper.seed_cards import TOP_50_CARDS

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.BASE_DIR / "templates"))

# Map of platform name -> scrape function
PLATFORM_SCRAPERS = {
    "pricecharting": scrape_pricecharting,
    "ebay": scrape_ebay,
    "tcgplayer": scrape_tcgplayer,
}


# ---- HTML Pages ----


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard showing arbitrage opportunities."""
    alerts = get_current_alerts()
    cards = get_all_tracked_cards(settings.DB_PATH)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "alerts": alerts,
            "cards": cards,
            "total_cards": len(cards),
            "total_alerts": len(alerts),
        },
    )


# ---- API Endpoints ----


@router.get("/api/alerts")
async def api_alerts(limit: int = 50):
    """Get active arbitrage alerts as JSON."""
    alerts = get_current_alerts(limit=limit)
    return {"alerts": alerts, "count": len(alerts)}


@router.post("/api/alerts/{alert_id}/dismiss")
async def api_dismiss_alert(alert_id: int):
    """Dismiss an alert by id."""
    ok = dismiss_alert(settings.DB_PATH, alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "dismissed", "id": alert_id}


@router.get("/api/cards")
async def api_cards():
    """List all tracked cards with their latest prices."""
    cards = get_all_tracked_cards(settings.DB_PATH)
    enriched = []
    for card in cards:
        prices = get_latest_prices(
            settings.DB_PATH, card["card_name"], card["set_name"]
        )
        enriched.append(
            {
                "card_name": card["card_name"],
                "set_name": card["set_name"],
                "prices": prices,
            }
        )
    return {"cards": enriched, "count": len(enriched)}


@router.get("/api/cards/{card_name}/{set_name}/prices")
async def api_card_prices(card_name: str, set_name: str):
    """Get latest prices for a specific card across all platforms."""
    prices = get_latest_prices(settings.DB_PATH, card_name, set_name)
    if not prices:
        raise HTTPException(status_code=404, detail="No price data for this card")
    return {"card_name": card_name, "set_name": set_name, "prices": prices}


@router.post("/api/scrape")
async def api_trigger_scrape(
    count: int = 5,
    platforms: Optional[list[str]] = Query(default=None),
):
    """Manually trigger a multi-platform scrape of the first N seed cards.

    Args:
        count: Number of cards to scrape (default 5, max 50).
        platforms: List of platforms (default: all). Options: pricecharting, ebay, tcgplayer.
    """
    count = min(count, len(TOP_50_CARDS))
    cards_to_scrape = TOP_50_CARDS[:count]

    # Default to all platforms
    if platforms is None:
        platforms = list(PLATFORM_SCRAPERS.keys())

    # Validate platforms
    invalid = [p for p in platforms if p not in PLATFORM_SCRAPERS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown platforms: {invalid}. Valid: {list(PLATFORM_SCRAPERS.keys())}",
        )

    logger.info(
        "Triggered multi-platform scrape: %d cards on %s",
        count,
        ", ".join(platforms),
    )

    # Scrape each platform
    all_price_points: list[PricePoint] = []
    platform_results: dict[str, int] = {}

    for platform_name in platforms:
        scraper = PLATFORM_SCRAPERS[platform_name]
        try:
            points = await scraper(cards_to_scrape)
            all_price_points.extend(points)
            platform_results[platform_name] = len(points)
            logger.info("%s: %d price points", platform_name, len(points))
        except Exception:
            logger.exception("Error scraping %s", platform_name)
            platform_results[platform_name] = 0

    # Save to DB
    saved = 0
    for pp in all_price_points:
        try:
            save_price_point(settings.DB_PATH, pp)
            saved += 1
        except Exception:
            logger.exception("Failed to save price point")

    # Detect cross-platform arbitrage
    opportunities = detect_arbitrage(all_price_points)
    alert_count = store_alerts(opportunities)

    return {
        "status": "complete",
        "cards_scraped": count,
        "platforms_scraped": platforms,
        "platform_results": platform_results,
        "price_points_saved": saved,
        "arbitrage_opportunities": len(opportunities),
        "alerts_stored": alert_count,
    }


@router.get("/api/health")
async def api_health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "tcg-arbitrage",
        "version": "0.2.0",
        "platforms": list(PLATFORM_SCRAPERS.keys()),
    }
