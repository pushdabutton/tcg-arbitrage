"""Alert system -- stores arbitrage opportunities and provides notification hooks.

MVP: Stores alerts in SQLite. Email notification is stubbed for future integration.
"""

from __future__ import annotations

import logging
from pathlib import Path

from config import settings
from engine.database import save_arbitrage_alert, get_active_alerts
from scraper.models import ArbitrageOpportunity

logger = logging.getLogger(__name__)


def store_alerts(
    opportunities: list[ArbitrageOpportunity],
    db_path: Path | None = None,
) -> int:
    """Persist arbitrage opportunities to the database.

    Returns the number of alerts stored.
    """
    if db_path is None:
        db_path = settings.DB_PATH

    count = 0
    for opp in opportunities:
        try:
            save_arbitrage_alert(db_path, opp)
            count += 1
        except Exception:
            logger.exception("Failed to store alert for %s", opp.card_name)

    logger.info("Stored %d / %d alerts", count, len(opportunities))
    return count


def get_current_alerts(
    db_path: Path | None = None,
    limit: int = 50,
) -> list[dict]:
    """Retrieve active (undismissed) alerts for the dashboard."""
    if db_path is None:
        db_path = settings.DB_PATH
    return get_active_alerts(db_path, limit=limit)


def send_email_alert(opp: ArbitrageOpportunity) -> bool:
    """Send an email notification for a high-value opportunity.

    Stubbed for MVP -- will integrate with AgentMail later.
    """
    logger.info(
        "[EMAIL STUB] Would send alert: %s %s -- Buy on %s @ $%.2f, Sell on %s @ $%.2f",
        opp.card_name,
        opp.set_name,
        opp.buy_platform.value,
        opp.buy_price,
        opp.sell_platform.value,
        opp.sell_price,
    )
    return False  # Not implemented yet
