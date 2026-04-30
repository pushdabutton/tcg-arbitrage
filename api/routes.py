"""FastAPI routes for the TCG Arbitrage dashboard."""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
import uuid
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
    get_last_scrape_time,
    get_latest_prices,
    get_price_history,
    save_price_point,
    save_scrape_meta,
)
from scraper.models import Platform, PricePoint
from scraper.pricecharting import scrape_cards as scrape_pricecharting
from scraper.tcgplayer import scrape_cards as scrape_tcgplayer
from scraper.seed_cards import TOP_50_CARDS

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.BASE_DIR / "templates"))

# Map of platform name -> scrape function
# eBay is excluded: server-side requests are blocked (403/503).
# Re-enable when a proxy/browser-automation solution is available.
PLATFORM_SCRAPERS = {
    "pricecharting": scrape_pricecharting,
    "tcgplayer": scrape_tcgplayer,
}

# In-memory job status tracker for async scraping (BUG 6)
_scrape_jobs: dict[str, dict] = {}

# Max cards to show in the dashboard card grid (OOM prevention)
DASHBOARD_CARD_LIMIT = 20


# ---- HTML Pages ----


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard showing arbitrage opportunities."""
    from shared_state import initial_scrape_status

    alerts = get_current_alerts()
    cards = get_all_tracked_cards(settings.DB_PATH)
    last_scrape = get_last_scrape_time(settings.DB_PATH)

    # Determine if the initial scrape is still running (no data yet)
    scrape_in_progress = initial_scrape_status.get("in_progress", False)
    scrape_message = initial_scrape_status.get("message", "")

    # Limit cards displayed to prevent OOM on large datasets
    display_cards = cards[:DASHBOARD_CARD_LIMIT]

    # Enrich cards with latest prices for the dashboard
    enriched_cards = []
    for card in display_cards:
        prices = get_latest_prices(
            settings.DB_PATH, card["card_name"], card["set_name"]
        )
        history = get_price_history(
            settings.DB_PATH, card["card_name"], card["set_name"], limit=10
        )
        enriched_cards.append(
            {
                "card_name": card["card_name"],
                "set_name": card["set_name"],
                "prices": prices,
                "history": history,
            }
        )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "alerts": alerts,
            "cards": enriched_cards,
            "total_cards": len(cards),
            "total_alerts": len(alerts),
            "last_scrape": last_scrape,
            "scrape_in_progress": scrape_in_progress,
            "scrape_message": scrape_message,
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


@router.get("/api/cards/{card_name}/{set_name}/history")
async def api_card_history(card_name: str, set_name: str, limit: int = 20):
    """Get price history for a specific card."""
    history = get_price_history(settings.DB_PATH, card_name, set_name, limit=limit)
    if not history:
        raise HTTPException(status_code=404, detail="No price history for this card")
    return {
        "card_name": card_name,
        "set_name": set_name,
        "history": history,
        "count": len(history),
    }


@router.get("/api/last-scrape")
async def api_last_scrape():
    """Get the timestamp of the last scrape."""
    last = get_last_scrape_time(settings.DB_PATH)
    return {"last_scrape": last}


def _run_scrape_job(
    job_id: str,
    cards_to_scrape: list,
    platforms: list[str],
) -> None:
    """Run scrape in a background thread to avoid timeout (BUG 6).

    Processes cards one at a time and saves to DB immediately to reduce
    memory usage (OOM fix).
    """
    try:
        _scrape_jobs[job_id]["status"] = "running"
        _scrape_jobs[job_id]["message"] = f"Scraping {len(cards_to_scrape)} cards..."

        all_price_points: list[PricePoint] = []
        saved = 0
        platform_results: dict[str, int] = {}

        for platform_name in platforms:
            scraper = PLATFORM_SCRAPERS[platform_name]
            try:
                # Run the async scraper in this thread's event loop
                points = asyncio.run(scraper(cards_to_scrape))
                platform_results[platform_name] = len(points)

                # Save to DB immediately and release memory
                for pp in points:
                    try:
                        save_price_point(settings.DB_PATH, pp)
                        saved += 1
                    except Exception:
                        logger.exception("Failed to save price point")

                all_price_points.extend(points)
                logger.info("%s: %d price points", platform_name, len(points))

                # Update job progress
                progress = int(
                    (platforms.index(platform_name) + 1) / len(platforms) * 80
                )
                _scrape_jobs[job_id]["progress"] = progress
                _scrape_jobs[job_id]["message"] = (
                    f"Scraped {platform_name} ({len(points)} prices)..."
                )

            except Exception:
                logger.exception("Error scraping %s", platform_name)
                platform_results[platform_name] = 0

            # Free memory after each platform
            gc.collect()

        # Record scrape metadata
        save_scrape_meta(
            settings.DB_PATH,
            card_count=len(cards_to_scrape),
            platforms=platforms,
            price_points=saved,
        )

        _scrape_jobs[job_id]["progress"] = 90
        _scrape_jobs[job_id]["message"] = "Detecting arbitrage..."

        # Detect cross-platform arbitrage
        opportunities = detect_arbitrage(all_price_points)
        alert_count = store_alerts(opportunities)

        # Mark complete
        _scrape_jobs[job_id].update({
            "status": "complete",
            "progress": 100,
            "message": f"Complete: {saved} prices, {len(opportunities)} opportunities",
            "price_points_saved": saved,
            "arbitrage_opportunities": len(opportunities),
            "alerts_stored": alert_count,
            "platform_results": platform_results,
            "cards_scraped": len(cards_to_scrape),
            "platforms_scraped": platforms,
        })

        # Final memory cleanup
        del all_price_points
        gc.collect()

    except Exception as exc:
        logger.exception("Scrape job %s failed", job_id)
        _scrape_jobs[job_id].update({
            "status": "error",
            "message": str(exc),
        })


@router.post("/api/scrape")
async def api_trigger_scrape(
    count: int = 10,
    platforms: Optional[list[str]] = Query(default=None),
):
    """Trigger a multi-platform scrape of the first N seed cards.

    Returns immediately with a job_id. Poll /api/scrape/status/{job_id}
    for completion (BUG 6: prevents timeout for large scrapes).

    Args:
        count: Number of cards to scrape (default 10, max 50).
        platforms: List of platforms (default: all). Options: pricecharting, tcgplayer.
    """
    count = min(count, len(TOP_50_CARDS))
    cards_to_scrape = TOP_50_CARDS[:count]

    # Default to all active platforms
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
        "Triggered async scrape: %d cards on %s",
        count,
        ", ".join(platforms),
    )

    # Create job and run in background thread
    job_id = str(uuid.uuid4())[:8]
    _scrape_jobs[job_id] = {
        "status": "starting",
        "progress": 0,
        "message": "Starting scrape...",
    }

    thread = threading.Thread(
        target=_run_scrape_job,
        args=(job_id, cards_to_scrape, platforms),
        daemon=True,
        name=f"scrape-{job_id}",
    )
    thread.start()

    return {
        "status": "accepted",
        "job_id": job_id,
        "cards": count,
        "platforms": platforms,
    }


@router.get("/api/scrape/status/{job_id}")
async def api_scrape_status(job_id: str):
    """Check the status of an async scrape job."""
    job = _scrape_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response = {
        "job_id": job_id,
        "status": job.get("status", "unknown"),
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
    }

    # Include results if complete
    if job.get("status") == "complete":
        response.update({
            "price_points_saved": job.get("price_points_saved", 0),
            "arbitrage_opportunities": job.get("arbitrage_opportunities", 0),
            "alerts_stored": job.get("alerts_stored", 0),
            "platform_results": job.get("platform_results", {}),
            "cards_scraped": job.get("cards_scraped", 0),
            "platforms_scraped": job.get("platforms_scraped", []),
        })
        # Clean up completed job after returning results
        # (keep for a short while in case of retries)

    return response


@router.get("/api/health")
async def api_health():
    """Health check endpoint."""
    last_scrape = get_last_scrape_time(settings.DB_PATH)
    return {
        "status": "ok",
        "service": "tcg-arbitrage",
        "version": "0.5.0",
        "platforms": list(PLATFORM_SCRAPERS.keys()),
        "last_scrape": last_scrape,
    }


@router.get("/api/initial-scrape-status")
async def api_initial_scrape_status():
    """Check if the initial background scrape is still running.

    Used by the dashboard to auto-refresh once data is available.
    """
    from shared_state import initial_scrape_status

    return {
        "in_progress": initial_scrape_status.get("in_progress", False),
        "completed": initial_scrape_status.get("completed", False),
        "message": initial_scrape_status.get("message", ""),
    }
