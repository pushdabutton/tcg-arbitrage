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
from scraper.ebay import scrape_cards as scrape_ebay
from scraper.pricecharting import scrape_cards as scrape_pricecharting
from scraper.tcgplayer import scrape_cards as scrape_tcgplayer
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
        version="0.2.0",
    )

    # Mount static files if the directory exists
    static_dir = settings.BASE_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(router)
    return app


async def run_scrape(
    card_count: int = 5,
    platforms: list[str] | None = None,
) -> None:
    """Run a multi-platform scrape cycle and store results.

    Args:
        card_count: Number of seed cards to scrape.
        platforms: List of platform names. Defaults to all platforms.
    """
    if platforms is None:
        platforms = ["pricecharting", "ebay", "tcgplayer"]

    cards = TOP_50_CARDS[:card_count]
    logger.info(
        "Starting multi-platform scrape of %d cards on %s...",
        len(cards),
        ", ".join(platforms),
    )

    all_price_points: list = []

    # Scrape each platform sequentially (respecting rate limits)
    if "pricecharting" in platforms:
        logger.info("--- Scraping PriceCharting ---")
        pc_points = await scrape_pricecharting(cards)
        all_price_points.extend(pc_points)
        logger.info("PriceCharting returned %d price points", len(pc_points))

    if "ebay" in platforms:
        logger.info("--- Scraping eBay Sold Listings ---")
        ebay_points = await scrape_ebay(cards)
        all_price_points.extend(ebay_points)
        logger.info("eBay returned %d price points", len(ebay_points))

    if "tcgplayer" in platforms:
        logger.info("--- Scraping TCGPlayer ---")
        tcg_points = await scrape_tcgplayer(cards)
        all_price_points.extend(tcg_points)
        logger.info("TCGPlayer returned %d price points", len(tcg_points))

    # Save all price points to DB
    saved = 0
    for pp in all_price_points:
        try:
            save_price_point(settings.DB_PATH, pp)
            saved += 1
        except Exception:
            logger.exception("Failed to save price point")

    logger.info("Saved %d / %d price points", saved, len(all_price_points))

    # Detect cross-platform arbitrage
    opportunities = detect_arbitrage(all_price_points)
    if opportunities:
        store_alerts(opportunities)
        logger.info("Found %d arbitrage opportunities!", len(opportunities))
    else:
        logger.info("No arbitrage opportunities found")

    # Print summary
    print("\n" + "=" * 60)
    print("  MULTI-PLATFORM SCRAPE RESULTS")
    print("=" * 60)
    print(f"  Cards scraped:  {len(cards)}")
    print(f"  Platforms:      {', '.join(platforms)}")
    print(f"  Price points:   {saved}")
    print(f"  Opportunities:  {len(opportunities)}")
    print("=" * 60)

    if all_price_points:
        # Group by card and show cross-platform comparison
        from collections import defaultdict

        by_card: dict[str, list] = defaultdict(list)
        for pp in all_price_points:
            key = f"{pp.card_name} ({pp.set_name})"
            by_card[key].append(pp)

        print("\n--- Cross-Platform Price Comparison ---")
        for card_key, points in sorted(by_card.items()):
            print(f"\n  {card_key}:")
            for pp in sorted(points, key=lambda x: x.platform.value):
                print(f"    {pp.platform.value:15s} = {pp.display_price}")

    if opportunities:
        print("\n--- Arbitrage Opportunities ---")
        for opp in opportunities[:10]:  # Show top 10
            print(
                f"  {opp.card_name} ({opp.set_name}): "
                f"Buy on {opp.buy_platform.value} @ ${opp.buy_price:.2f}, "
                f"Sell on {opp.sell_platform.value} @ ${opp.sell_price:.2f} "
                f"[{opp.display_spread}]"
            )

    print()


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
    parser.add_argument(
        "--platforms",
        nargs="+",
        default=None,
        choices=["pricecharting", "ebay", "tcgplayer"],
        help="Platforms to scrape (default: all)",
    )
    args = parser.parse_args()

    # Initialize database
    init_db(settings.DB_PATH)
    logger.info("Database initialized at %s", settings.DB_PATH)

    if args.scrape_only:
        asyncio.run(
            run_scrape(
                min(args.cards, len(TOP_50_CARDS)),
                platforms=args.platforms,
            )
        )
        return

    if args.scrape:
        asyncio.run(
            run_scrape(
                min(args.cards, len(TOP_50_CARDS)),
                platforms=args.platforms,
            )
        )

    # Start web server
    app = create_app()
    logger.info("Starting server at http://%s:%d", settings.HOST, settings.PORT)
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)


if __name__ == "__main__":
    main()
