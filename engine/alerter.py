"""Alert system -- stores arbitrage opportunities and sends email notifications.

Uses the AgentMail API to send email alerts when high-spread arbitrage
opportunities are detected across platforms.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from config import settings
from engine.database import save_arbitrage_alert, get_active_alerts
from scraper.models import ArbitrageOpportunity

logger = logging.getLogger(__name__)

# AgentMail configuration
AGENTMAIL_API_KEY = os.environ.get(
    "AGENT_EMAIL_API_KEY",
    "",
)
AGENTMAIL_INBOX = os.environ.get("AGENT_EMAIL", "flux.civ@agentmail.to")
ALERT_RECIPIENT = os.environ.get("TCG_ALERT_EMAIL", "flux.civ@agentmail.to")

# Default threshold for email alerts (can be overridden via config)
EMAIL_ALERT_THRESHOLD_PERCENT = float(
    os.environ.get("TCG_EMAIL_ALERT_THRESHOLD", "30.0")
)


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


def _build_platform_url(platform: str, card_name: str, set_name: str) -> str:
    """Build a search URL for a card on a given platform."""
    query = f"{card_name} {set_name}".replace(" ", "+")
    urls = {
        "pricecharting": f"https://www.pricecharting.com/search-products?q={query}&type=prices",
        "tcgplayer": f"https://www.tcgplayer.com/search/pokemon/product?q={query}",
        "ebay": f"https://www.ebay.com/sch/i.html?_nkw={query}+pokemon+card",
        "cardmarket": f"https://www.cardmarket.com/en/Pokemon/Products/Search?searchString={query}",
    }
    return urls.get(platform, "")


def _format_alert_html(opp: ArbitrageOpportunity) -> str:
    """Format a single opportunity as an HTML email body."""
    buy_url = opp.buy_url or _build_platform_url(
        opp.buy_platform.value, opp.card_name, opp.set_name
    )
    sell_url = opp.sell_url or _build_platform_url(
        opp.sell_platform.value, opp.card_name, opp.set_name
    )

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                max-width: 600px; margin: 0 auto; background: #1a1d27; color: #e1e4ed;
                border-radius: 12px; overflow: hidden;">
        <div style="background: #6366f1; padding: 20px; text-align: center;">
            <h1 style="margin: 0; color: white; font-size: 1.4rem;">
                TCG Arbitrage Alert
            </h1>
            <p style="margin: 4px 0 0; color: rgba(255,255,255,0.8); font-size: 0.9rem;">
                {opp.spread_percent:.1f}% spread detected
            </p>
        </div>
        <div style="padding: 24px;">
            <h2 style="margin: 0 0 4px; color: #e1e4ed; font-size: 1.2rem;">
                {opp.card_name}
            </h2>
            <p style="margin: 0 0 20px; color: #8b8fa3; font-size: 0.9rem;">
                {opp.set_name}
            </p>

            <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                <tr>
                    <td style="padding: 12px; background: #22263a; border-radius: 8px 0 0 0;">
                        <div style="color: #8b8fa3; font-size: 0.75rem; text-transform: uppercase;">Buy On</div>
                        <div style="color: #22c55e; font-size: 1.3rem; font-weight: 700; font-family: monospace;">
                            ${opp.buy_price:.2f}
                        </div>
                        <div style="color: #8b8fa3; font-size: 0.85rem; margin-top: 4px;">
                            {opp.buy_platform.value.title()}
                        </div>
                        <a href="{buy_url}" style="color: #6366f1; font-size: 0.8rem;">
                            View listing
                        </a>
                    </td>
                    <td style="padding: 12px; background: #22263a; border-radius: 0 8px 0 0;">
                        <div style="color: #8b8fa3; font-size: 0.75rem; text-transform: uppercase;">Sell On</div>
                        <div style="color: #ef4444; font-size: 1.3rem; font-weight: 700; font-family: monospace;">
                            ${opp.sell_price:.2f}
                        </div>
                        <div style="color: #8b8fa3; font-size: 0.85rem; margin-top: 4px;">
                            {opp.sell_platform.value.title()}
                        </div>
                        <a href="{sell_url}" style="color: #6366f1; font-size: 0.8rem;">
                            View listing
                        </a>
                    </td>
                </tr>
                <tr>
                    <td colspan="2" style="padding: 12px; background: #2a2e3f; border-radius: 0 0 8px 8px; text-align: center;">
                        <div style="color: #eab308; font-size: 1.1rem; font-weight: 700; font-family: monospace;">
                            Spread: ${opp.spread_usd:.2f} ({opp.spread_percent:.1f}%)
                        </div>
                    </td>
                </tr>
            </table>

            <p style="color: #8b8fa3; font-size: 0.8rem; text-align: center; margin: 0;">
                Detected by TCG Arbitrage Tool | Prices may change rapidly
            </p>
        </div>
    </div>
    """


def _format_digest_html(opportunities: list[ArbitrageOpportunity]) -> str:
    """Format multiple opportunities into a digest email."""
    rows = ""
    for opp in sorted(opportunities, key=lambda o: o.spread_percent, reverse=True):
        buy_url = opp.buy_url or _build_platform_url(
            opp.buy_platform.value, opp.card_name, opp.set_name
        )
        sell_url = opp.sell_url or _build_platform_url(
            opp.sell_platform.value, opp.card_name, opp.set_name
        )
        rows += f"""
        <tr>
            <td style="padding: 10px 12px; border-bottom: 1px solid #2a2e3f;">
                <strong>{opp.card_name}</strong><br>
                <span style="color: #8b8fa3; font-size: 0.85rem;">{opp.set_name}</span>
            </td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #2a2e3f;">
                <span style="color: #22c55e; font-weight: 600; font-family: monospace;">${opp.buy_price:.2f}</span><br>
                <a href="{buy_url}" style="color: #8b8fa3; font-size: 0.8rem;">{opp.buy_platform.value.title()}</a>
            </td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #2a2e3f;">
                <span style="color: #ef4444; font-weight: 600; font-family: monospace;">${opp.sell_price:.2f}</span><br>
                <a href="{sell_url}" style="color: #8b8fa3; font-size: 0.8rem;">{opp.sell_platform.value.title()}</a>
            </td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #2a2e3f; text-align: center;">
                <span style="color: #eab308; font-weight: 700; font-family: monospace;">{opp.spread_percent:.1f}%</span><br>
                <span style="color: #8b8fa3; font-size: 0.85rem;">${opp.spread_usd:.2f}</span>
            </td>
        </tr>
        """

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                max-width: 700px; margin: 0 auto; background: #1a1d27; color: #e1e4ed;
                border-radius: 12px; overflow: hidden;">
        <div style="background: #6366f1; padding: 20px; text-align: center;">
            <h1 style="margin: 0; color: white; font-size: 1.4rem;">
                TCG Arbitrage Digest
            </h1>
            <p style="margin: 4px 0 0; color: rgba(255,255,255,0.8); font-size: 0.9rem;">
                {len(opportunities)} opportunities found
            </p>
        </div>
        <div style="padding: 16px;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="color: #8b8fa3; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;">
                        <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #2a2e3f;">Card</th>
                        <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #2a2e3f;">Buy</th>
                        <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #2a2e3f;">Sell</th>
                        <th style="padding: 8px 12px; text-align: center; border-bottom: 2px solid #2a2e3f;">Spread</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
            <p style="color: #8b8fa3; font-size: 0.8rem; text-align: center; margin: 16px 0 0;">
                TCG Arbitrage Tool | Prices may change rapidly | Act quickly
            </p>
        </div>
    </div>
    """


def _format_alert_text(opp: ArbitrageOpportunity) -> str:
    """Format a plain-text version of an alert."""
    buy_url = opp.buy_url or _build_platform_url(
        opp.buy_platform.value, opp.card_name, opp.set_name
    )
    sell_url = opp.sell_url or _build_platform_url(
        opp.sell_platform.value, opp.card_name, opp.set_name
    )

    return (
        f"TCG ARBITRAGE ALERT\n"
        f"{'=' * 40}\n\n"
        f"Card: {opp.card_name} ({opp.set_name})\n\n"
        f"BUY on {opp.buy_platform.value.title()}: ${opp.buy_price:.2f}\n"
        f"  {buy_url}\n\n"
        f"SELL on {opp.sell_platform.value.title()}: ${opp.sell_price:.2f}\n"
        f"  {sell_url}\n\n"
        f"SPREAD: ${opp.spread_usd:.2f} ({opp.spread_percent:.1f}%)\n\n"
        f"---\n"
        f"TCG Arbitrage Tool | Prices may change rapidly"
    )


async def send_email_alert(opp: ArbitrageOpportunity) -> bool:
    """Send an email notification for a single high-value opportunity.

    Uses the AgentMail API to send from flux.civ@agentmail.to.

    Returns True if sent successfully, False otherwise.
    """
    if not AGENTMAIL_API_KEY:
        logger.warning(
            "AGENT_EMAIL_API_KEY not set -- skipping email alert for %s",
            opp.card_name,
        )
        return False

    try:
        from agentmail import AgentMail

        client = AgentMail(api_key=AGENTMAIL_API_KEY)

        subject = (
            f"[TCG Alert] {opp.card_name} ({opp.set_name}) "
            f"-- {opp.spread_percent:.0f}% spread"
        )

        response = client.inboxes.messages.send(
            inbox_id=AGENTMAIL_INBOX,
            to=ALERT_RECIPIENT,
            subject=subject,
            text=_format_alert_text(opp),
            html=_format_alert_html(opp),
        )

        logger.info(
            "Email alert sent for %s (%s) -- message_id: %s",
            opp.card_name,
            opp.set_name,
            getattr(response, "message_id", "unknown"),
        )
        return True

    except Exception:
        logger.exception("Failed to send email alert for %s", opp.card_name)
        return False


async def send_email_alerts(
    opportunities: list[ArbitrageOpportunity],
    threshold_percent: float | None = None,
) -> int:
    """Send email alerts for opportunities exceeding the threshold.

    For 4+ opportunities, sends a single digest email instead of individual ones.

    Args:
        opportunities: List of detected arbitrage opportunities.
        threshold_percent: Minimum spread % to alert on. Defaults to EMAIL_ALERT_THRESHOLD_PERCENT.

    Returns:
        Number of alerts sent.
    """
    if threshold_percent is None:
        threshold_percent = EMAIL_ALERT_THRESHOLD_PERCENT

    # Filter to only high-spread opportunities
    alertable = [
        opp for opp in opportunities
        if opp.spread_percent >= threshold_percent
    ]

    if not alertable:
        logger.info("No opportunities above %.0f%% threshold", threshold_percent)
        return 0

    if not AGENTMAIL_API_KEY:
        logger.warning(
            "AGENT_EMAIL_API_KEY not set -- would send %d alerts",
            len(alertable),
        )
        return 0

    # For many alerts, send a digest instead of individual emails
    if len(alertable) >= 4:
        return await _send_digest_email(alertable)

    # Send individual alerts
    sent = 0
    for opp in alertable:
        if await send_email_alert(opp):
            sent += 1

    return sent


async def _send_digest_email(opportunities: list[ArbitrageOpportunity]) -> int:
    """Send a single digest email containing all opportunities."""
    try:
        from agentmail import AgentMail

        client = AgentMail(api_key=AGENTMAIL_API_KEY)

        top_spread = max(opp.spread_percent for opp in opportunities)
        subject = (
            f"[TCG Digest] {len(opportunities)} arbitrage opportunities "
            f"(up to {top_spread:.0f}% spread)"
        )

        # Plain text fallback
        text_lines = [
            f"TCG ARBITRAGE DIGEST -- {len(opportunities)} Opportunities\n",
            "=" * 50,
            "",
        ]
        for opp in sorted(opportunities, key=lambda o: o.spread_percent, reverse=True):
            text_lines.append(
                f"  {opp.card_name} ({opp.set_name}): "
                f"Buy {opp.buy_platform.value} ${opp.buy_price:.2f} -> "
                f"Sell {opp.sell_platform.value} ${opp.sell_price:.2f} "
                f"[{opp.spread_percent:.1f}%]"
            )
        text_lines.append("")
        text_lines.append("---")
        text_lines.append("TCG Arbitrage Tool")

        response = client.inboxes.messages.send(
            inbox_id=AGENTMAIL_INBOX,
            to=ALERT_RECIPIENT,
            subject=subject,
            text="\n".join(text_lines),
            html=_format_digest_html(opportunities),
        )

        logger.info(
            "Digest email sent with %d opportunities -- message_id: %s",
            len(opportunities),
            getattr(response, "message_id", "unknown"),
        )
        return len(opportunities)

    except Exception:
        logger.exception("Failed to send digest email")
        return 0
