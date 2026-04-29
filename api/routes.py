"""FastAPI routes for the TCG Arbitrage dashboard."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
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
from scraper.pricecharting import scrape_cards as scrape_pricecharting
from scraper.seed_cards import TOP_50_CARDS

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.BASE_DIR / "templates"))


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
async def api_trigger_scrape(count: int = 5):
    """Manually trigger a scrape of the first N seed cards.

    Default: 5 cards (for quick testing). Max: 50.
    """
    count = min(count, len(TOP_50_CARDS))
    cards_to_scrape = TOP_50_CARDS[:count]

    logger.info("Triggered manual scrape of %d cards", count)

    # Scrape PriceCharting (primary source)
    price_points = await scrape_pricecharting(cards_to_scrape)

    # Save to DB
    saved = 0
    for pp in price_points:
        try:
            save_price_point(settings.DB_PATH, pp)
            saved += 1
        except Exception:
            logger.exception("Failed to save price point")

    # Detect arbitrage from all stored data
    # (In MVP we detect from the just-scraped data; multi-source comes later)
    opportunities = detect_arbitrage(price_points)
    alert_count = store_alerts(opportunities)

    return {
        "status": "complete",
        "cards_scraped": count,
        "price_points_saved": saved,
        "arbitrage_opportunities": len(opportunities),
        "alerts_stored": alert_count,
    }


@router.get("/api/health")
async def api_health():
    """Health check endpoint."""
    return {"status": "ok", "service": "tcg-arbitrage"}
