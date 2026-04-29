"""TCG Price Arbitrage Alert Tool -- Entry Point.

Run with:
    python main.py              # Start web server
    python main.py --scrape     # Scrape first, then start server
    python main.py --scrape-only # Scrape and exit (no server)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.routes import router
from config import settings
from engine.alerter import store_alerts
from engine.arbitrage import detect_arbitrage
from engine.database import init_db, save_price_point
from scraper.pricecharting import scrape_cards as scrape_pricecharting
from scraper.seed_cards import TOP_50_CARDS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("tcg-arbitrage")


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title="TCG Price Arbitrage Tool",
        description="Pokemon card price comparison across platforms",
        version="0.1.0",
    )

    # Mount static files if the directory exists
    static_dir = settings.BASE_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(router)
    return app


async def run_scrape(card_count: int = 5) -> None:
    """Run a scrape cycle and store results."""
    cards = TOP_50_CARDS[:card_count]
    logger.info("Starting scrape of %d cards...", len(cards))

    # Scrape PriceCharting
    price_points = await scrape_pricecharting(cards)

    # Save all price points
    saved = 0
    for pp in price_points:
        try:
            save_price_point(settings.DB_PATH, pp)
            saved += 1
        except Exception:
            logger.exception("Failed to save price point")

    logger.info("Saved %d / %d price points", saved, len(price_points))

    # Detect arbitrage
    opportunities = detect_arbitrage(price_points)
    if opportunities:
        store_alerts(opportunities)
        logger.info("Found %d arbitrage opportunities!", len(opportunities))
    else:
        logger.info("No arbitrage opportunities found (single-source scrape)")

    # Print summary
    print("\n=== Scrape Results ===")
    print(f"Cards scraped: {len(cards)}")
    print(f"Price points:  {saved}")
    print(f"Opportunities: {len(opportunities)}")

    if price_points:
        print("\n--- Sample Prices ---")
        for pp in price_points[:10]:
            print(f"  {pp.card_name} ({pp.set_name}) = {pp.display_price} [{pp.platform.value}]")


def main():
    parser = argparse.ArgumentParser(description="TCG Price Arbitrage Alert Tool")
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="Scrape prices before starting server",
    )
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="Scrape prices and exit (no server)",
    )
    parser.add_argument(
        "--cards",
        type=int,
        default=5,
        help="Number of cards to scrape (default: 5, max: 50)",
    )
    args = parser.parse_args()

    # Initialize database
    init_db(settings.DB_PATH)
    logger.info("Database initialized at %s", settings.DB_PATH)

    if args.scrape_only:
        asyncio.run(run_scrape(min(args.cards, len(TOP_50_CARDS))))
        return

    if args.scrape:
        asyncio.run(run_scrape(min(args.cards, len(TOP_50_CARDS))))

    # Start web server
    app = create_app()
    logger.info("Starting server at http://%s:%d", settings.HOST, settings.PORT)
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)


if __name__ == "__main__":
    main()
