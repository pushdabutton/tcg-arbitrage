"""Tests for the alerter module -- email alerts via AgentMail."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.models import ArbitrageOpportunity, Platform


def _make_opp(
    card: str = "Charizard",
    set_name: str = "Base Set",
    buy_price: float = 200.0,
    sell_price: float = 400.0,
    buy_platform: Platform = Platform.PRICECHARTING,
    sell_platform: Platform = Platform.EBAY,
) -> ArbitrageOpportunity:
    """Helper to create an ArbitrageOpportunity."""
    return ArbitrageOpportunity(
        card_name=card,
        set_name=set_name,
        buy_platform=buy_platform,
        buy_price=buy_price,
        sell_platform=sell_platform,
        sell_price=sell_price,
        buy_url=f"https://{buy_platform.value}.com/{card.lower()}",
        sell_url=f"https://{sell_platform.value}.com/{card.lower()}",
    )


class TestStoreAlerts:
    """Tests for the store_alerts function."""

    def test_store_alerts_persists(self, tmp_db):
        from engine.alerter import store_alerts
        from engine.database import get_active_alerts

        opps = [_make_opp(), _make_opp(card="Blastoise", buy_price=50, sell_price=100)]
        count = store_alerts(opps, db_path=tmp_db)
        assert count == 2

        alerts = get_active_alerts(tmp_db)
        assert len(alerts) == 2

    def test_store_alerts_empty_list(self, tmp_db):
        from engine.alerter import store_alerts

        count = store_alerts([], db_path=tmp_db)
        assert count == 0


class TestFormatAlertHtml:
    """Tests for HTML email formatting."""

    def test_format_single_alert_html(self):
        from engine.alerter import _format_alert_html

        opp = _make_opp()
        html = _format_alert_html(opp)
        assert "Charizard" in html
        assert "Base Set" in html
        assert "$200.00" in html
        assert "$400.00" in html
        assert "50.0%" in html
        assert "TCG Arbitrage Alert" in html

    def test_format_alert_with_urls(self):
        from engine.alerter import _format_alert_html

        opp = _make_opp()
        html = _format_alert_html(opp)
        assert "View listing" in html

    def test_format_digest_html(self):
        from engine.alerter import _format_digest_html

        opps = [
            _make_opp(card="Charizard", buy_price=200, sell_price=400),
            _make_opp(card="Pikachu", buy_price=5, sell_price=15),
        ]
        html = _format_digest_html(opps)
        assert "TCG Arbitrage Digest" in html
        assert "2 opportunities" in html
        assert "Charizard" in html
        assert "Pikachu" in html


class TestFormatAlertText:
    """Tests for plain-text email formatting."""

    def test_format_text_has_required_fields(self):
        from engine.alerter import _format_alert_text

        opp = _make_opp()
        text = _format_alert_text(opp)
        assert "Charizard" in text
        assert "Base Set" in text
        assert "$200.00" in text
        assert "$400.00" in text
        assert "50.0%" in text
        assert "SPREAD" in text


class TestBuildPlatformUrl:
    """Tests for URL builder."""

    def test_pricecharting_url(self):
        from engine.alerter import _build_platform_url

        url = _build_platform_url("pricecharting", "Charizard", "Base Set")
        assert "pricecharting.com" in url
        assert "Charizard" in url

    def test_tcgplayer_url(self):
        from engine.alerter import _build_platform_url

        url = _build_platform_url("tcgplayer", "Charizard", "Base Set")
        assert "tcgplayer.com" in url

    def test_ebay_url(self):
        from engine.alerter import _build_platform_url

        url = _build_platform_url("ebay", "Charizard", "Base Set")
        assert "ebay.com" in url

    def test_unknown_platform_empty(self):
        from engine.alerter import _build_platform_url

        url = _build_platform_url("unknown_platform", "Card", "Set")
        assert url == ""


class TestSendEmailAlert:
    """Tests for the AgentMail email sending."""

    @pytest.mark.asyncio
    async def test_send_email_no_api_key(self):
        """Without API key, send_email_alert returns False."""
        from engine.alerter import send_email_alert

        with patch("engine.alerter.AGENTMAIL_API_KEY", ""):
            result = await send_email_alert(_make_opp())
            assert result is False

    @pytest.mark.asyncio
    async def test_send_email_success(self):
        """With API key and mocked client, send succeeds."""
        from engine.alerter import send_email_alert

        mock_response = MagicMock()
        mock_response.message_id = "msg_123"

        mock_messages = MagicMock()
        mock_messages.send = MagicMock(return_value=mock_response)

        mock_inboxes = MagicMock()
        mock_inboxes.messages = mock_messages

        mock_client = MagicMock()
        mock_client.inboxes = mock_inboxes

        with patch("engine.alerter.AGENTMAIL_API_KEY", "test_key_123"):
            with patch("agentmail.AgentMail", return_value=mock_client):
                result = await send_email_alert(_make_opp())

        assert result is True
        mock_messages.send.assert_called_once()
        call_kwargs = mock_messages.send.call_args
        assert "Charizard" in call_kwargs.kwargs.get("subject", "")

    @pytest.mark.asyncio
    async def test_send_email_handles_exception(self):
        """API errors are caught and logged."""
        from engine.alerter import send_email_alert

        with patch("engine.alerter.AGENTMAIL_API_KEY", "test_key_123"):
            with patch("agentmail.AgentMail", side_effect=Exception("API error")):
                result = await send_email_alert(_make_opp())
                assert result is False


class TestSendEmailAlerts:
    """Tests for batch email alert sending."""

    @pytest.mark.asyncio
    async def test_no_alerts_below_threshold(self):
        """Opportunities below threshold should not trigger emails."""
        from engine.alerter import send_email_alerts

        opps = [_make_opp(buy_price=90, sell_price=100)]  # 10% spread
        with patch("engine.alerter.AGENTMAIL_API_KEY", "test_key"):
            sent = await send_email_alerts(opps, threshold_percent=30.0)
        assert sent == 0

    @pytest.mark.asyncio
    async def test_no_api_key_returns_zero(self):
        """Without API key, returns 0."""
        from engine.alerter import send_email_alerts

        opps = [_make_opp()]  # 50% spread
        with patch("engine.alerter.AGENTMAIL_API_KEY", ""):
            sent = await send_email_alerts(opps, threshold_percent=30.0)
        assert sent == 0

    @pytest.mark.asyncio
    async def test_digest_sent_for_many_alerts(self):
        """4+ alerts should trigger a digest email."""
        from engine.alerter import send_email_alerts

        opps = [
            _make_opp(card=f"Card{i}", buy_price=100, sell_price=200)
            for i in range(5)
        ]

        mock_response = MagicMock()
        mock_response.message_id = "msg_digest"
        mock_messages = MagicMock()
        mock_messages.send = MagicMock(return_value=mock_response)
        mock_inboxes = MagicMock()
        mock_inboxes.messages = mock_messages
        mock_client = MagicMock()
        mock_client.inboxes = mock_inboxes

        with patch("engine.alerter.AGENTMAIL_API_KEY", "test_key"):
            with patch("agentmail.AgentMail", return_value=mock_client):
                sent = await send_email_alerts(opps, threshold_percent=30.0)

        assert sent == 5  # Digest reports count of all included
