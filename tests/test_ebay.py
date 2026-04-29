"""Tests for eBay scraper with realistic mock HTML.

Tests cover:
- Price parsing (various formats including currency prefixes)
- HTML extraction from realistic eBay sold listing markup
- Outlier filtering
- Full scrape_card flow with mocked HTTP
- Error handling (HTTP errors, empty results)
- Caching behavior
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ebay import (
    _extract_prices_from_html,
    _filter_outliers,
    _parse_date,
    _parse_price,
    scrape_card,
)
from scraper.models import Card, Platform


# ---------------------------------------------------------------------------
# Realistic eBay sold-listings HTML fixture
# ---------------------------------------------------------------------------

EBAY_SOLD_HTML = """
<html>
<body>
<div class="srp-results">
  <ul class="srp-results srp-list clearfix">

    <!-- "Shop on eBay" placeholder (should be skipped) -->
    <li class="s-item s-item--large">
      <div class="s-item__title"><span>Shop on eBay</span></div>
      <span class="s-item__price">$0.99</span>
    </li>

    <!-- Real sold listing 1 -->
    <li class="s-item s-item--large">
      <div class="s-item__title">
        <span role="heading">Pokemon Charizard Base Set Holo 4/102 LP</span>
      </div>
      <span class="s-item__price">$325.00</span>
      <span class="s-item__endedDate">Sold  Apr 25, 2026</span>
    </li>

    <!-- Real sold listing 2 -->
    <li class="s-item s-item--large">
      <div class="s-item__title">
        <span role="heading">Charizard 4/102 Base Set Holo Rare Pokemon Card</span>
      </div>
      <span class="s-item__price">$350.00</span>
      <span class="s-item__endedDate">Sold  Apr 24, 2026</span>
    </li>

    <!-- Listing with range price -->
    <li class="s-item s-item--large">
      <div class="s-item__title">
        <span role="heading">Charizard Base Set Near Mint</span>
      </div>
      <span class="s-item__price">$300.00 to $500.00</span>
      <span class="s-item__endedDate">Sold  Apr 23, 2026</span>
    </li>

    <!-- Listing with US currency prefix -->
    <li class="s-item s-item--large">
      <div class="s-item__title">
        <span role="heading">Pokemon Charizard 4/102 Base Set Holo</span>
      </div>
      <span class="s-item__price">US $375.00</span>
      <span class="s-item__endedDate">Sold  Apr 22, 2026</span>
    </li>

    <!-- Listing with comma in price -->
    <li class="s-item s-item--large">
      <div class="s-item__title">
        <span role="heading">PSA 9 Charizard Base Set</span>
      </div>
      <span class="s-item__price">$1,200.00</span>
      <span class="s-item__endedDate">Sold  Apr 21, 2026</span>
    </li>

    <!-- Low price listing (possible outlier) -->
    <li class="s-item s-item--large">
      <div class="s-item__title">
        <span role="heading">Charizard Base Set DAMAGED</span>
      </div>
      <span class="s-item__price">$45.00</span>
      <span class="s-item__endedDate">Sold  Apr 20, 2026</span>
    </li>

  </ul>
</div>
</body>
</html>
"""

EBAY_EMPTY_HTML = """
<html>
<body>
<div class="srp-results">
  <ul class="srp-results srp-list clearfix">
    <li class="s-item s-item--large">
      <div class="s-item__title"><span>Shop on eBay</span></div>
      <span class="s-item__price">$0.99</span>
    </li>
  </ul>
  <div class="srp-controls__count">0 results</div>
</div>
</body>
</html>
"""

EBAY_NO_ITEMS_HTML = """
<html>
<body>
<div class="srp-results">
  <h3>No exact matches found</h3>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Price parsing tests
# ---------------------------------------------------------------------------


class TestParsePrice:
    def test_simple_dollar(self):
        assert _parse_price("$42.50") == 42.50

    def test_no_dollar_sign(self):
        assert _parse_price("42.50") == 42.50

    def test_with_commas(self):
        assert _parse_price("$1,234.56") == 1234.56

    def test_us_prefix(self):
        assert _parse_price("US $375.00") == 375.00

    def test_c_prefix(self):
        assert _parse_price("C $100.00") == 100.00

    def test_empty(self):
        assert _parse_price("") is None

    def test_na(self):
        assert _parse_price("N/A") is None

    def test_zero_returns_none(self):
        assert _parse_price("$0.00") is None

    def test_whole_number(self):
        assert _parse_price("$100") == 100.0

    def test_text_with_price(self):
        assert _parse_price("Price: $99.99") == 99.99


# ---------------------------------------------------------------------------
# Date parsing tests
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_standard_format(self):
        result = _parse_date("Apr 25, 2026")
        assert result is not None
        assert result.month == 4
        assert result.day == 25
        assert result.year == 2026

    def test_sold_prefix(self):
        result = _parse_date("Sold  Apr 25, 2026")
        assert result is not None
        assert result.month == 4

    def test_full_month_name(self):
        result = _parse_date("January 15, 2026")
        assert result is not None
        assert result.month == 1

    def test_invalid(self):
        assert _parse_date("not a date") is None

    def test_empty(self):
        assert _parse_date("") is None


# ---------------------------------------------------------------------------
# HTML extraction tests
# ---------------------------------------------------------------------------


class TestExtractPricesFromHtml:
    def test_extracts_real_listings(self):
        items = _extract_prices_from_html(EBAY_SOLD_HTML)
        # Should skip "Shop on eBay" placeholder
        # Should have: $325, $350, $300 (range lower), $375, $1200, $45
        assert len(items) == 6

    def test_skips_shop_on_ebay(self):
        items = _extract_prices_from_html(EBAY_SOLD_HTML)
        titles = [item.get("title", "").lower() for item in items]
        assert not any("shop on ebay" in t for t in titles)

    def test_extracts_correct_prices(self):
        items = _extract_prices_from_html(EBAY_SOLD_HTML)
        prices = [item["price"] for item in items]
        assert 325.0 in prices
        assert 350.0 in prices
        assert 375.0 in prices
        assert 1200.0 in prices
        assert 45.0 in prices

    def test_handles_range_prices(self):
        items = _extract_prices_from_html(EBAY_SOLD_HTML)
        # Range price "$300.00 to $500.00" should take the lower bound
        prices = [item["price"] for item in items]
        assert 300.0 in prices

    def test_extracts_dates(self):
        items = _extract_prices_from_html(EBAY_SOLD_HTML)
        dates = [item["date"] for item in items if item["date"] is not None]
        assert len(dates) >= 3

    def test_empty_results(self):
        items = _extract_prices_from_html(EBAY_EMPTY_HTML)
        assert len(items) == 0

    def test_no_listings_at_all(self):
        items = _extract_prices_from_html(EBAY_NO_ITEMS_HTML)
        assert len(items) == 0

    def test_malformed_html(self):
        items = _extract_prices_from_html("<html><body>garbage</body></html>")
        assert len(items) == 0


# ---------------------------------------------------------------------------
# Outlier filtering tests
# ---------------------------------------------------------------------------


class TestFilterOutliers:
    def test_no_filtering_with_few_items(self):
        prices = [100.0, 200.0, 300.0]
        result = _filter_outliers(prices)
        assert result == prices

    def test_removes_outliers(self):
        # Normal prices around $300-400, one extreme outlier at $5000
        prices = [300.0, 320.0, 350.0, 340.0, 325.0, 5000.0]
        result = _filter_outliers(prices)
        assert 5000.0 not in result
        assert len(result) < len(prices)

    def test_removes_low_outliers(self):
        # Normal prices around $300-400, one extreme low at $5
        prices = [300.0, 320.0, 350.0, 340.0, 325.0, 5.0]
        result = _filter_outliers(prices)
        assert 5.0 not in result

    def test_all_same_price(self):
        prices = [100.0, 100.0, 100.0, 100.0, 100.0]
        result = _filter_outliers(prices)
        assert len(result) == 5

    def test_returns_all_if_filter_removes_everything(self):
        # Edge case: all prices are outliers relative to each other
        prices = [1.0, 1000.0, 2000.0, 3000.0]
        result = _filter_outliers(prices)
        # Should return something, not empty
        assert len(result) > 0

    def test_empty_input(self):
        assert _filter_outliers([]) == []


# ---------------------------------------------------------------------------
# Full scrape_card flow (mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_card():
    return Card(
        name="Charizard",
        set_name="Base Set",
        pricecharting_id="pokemon-base-set/charizard-4",
    )


class TestScrapeCard:
    @pytest.mark.asyncio
    async def test_scrape_returns_price_point(self, sample_card):
        """Full scrape_card flow with mocked response returning real HTML."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = EBAY_SOLD_HTML
        mock_response.url = "https://www.ebay.com/sch/i.html?_nkw=test"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        # Patch cache functions to avoid DB access
        with patch("scraper.ebay.get_cache", return_value=None), \
             patch("scraper.ebay.set_cache"):
            results = await scrape_card(mock_client, sample_card, use_cache=False)

        assert len(results) == 1
        pp = results[0]
        assert pp.platform == Platform.EBAY
        assert pp.card_name == "Charizard"
        assert pp.set_name == "Base Set"
        assert pp.price_usd > 0
        # Median of [45, 300, 325, 350, 375, 1200] after outlier filter
        # With outliers removed (45 and 1200), median of [300, 325, 350, 375] = ~337.5
        assert 200 < pp.price_usd < 500

    @pytest.mark.asyncio
    async def test_scrape_returns_empty_on_no_results(self, sample_card):
        """Should return empty list when no listings found."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = EBAY_EMPTY_HTML
        mock_response.url = "https://www.ebay.com/sch/i.html?_nkw=test"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("scraper.ebay.get_cache", return_value=None), \
             patch("scraper.ebay.set_cache"):
            results = await scrape_card(mock_client, sample_card, use_cache=False)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_scrape_handles_http_error(self, sample_card):
        """Should return empty list on HTTP errors."""
        import httpx

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 429
        exc = httpx.HTTPStatusError(
            "Too Many Requests",
            request=MagicMock(),
            response=mock_response,
        )
        mock_client.get = AsyncMock(side_effect=exc)

        with patch("scraper.ebay.get_cache", return_value=None):
            results = await scrape_card(mock_client, sample_card, use_cache=False)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_scrape_handles_request_error(self, sample_card):
        """Should return empty list on connection errors."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.RequestError("Connection refused", request=MagicMock())
        )

        with patch("scraper.ebay.get_cache", return_value=None):
            results = await scrape_card(mock_client, sample_card, use_cache=False)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_scrape_uses_cache(self, sample_card):
        """Should use cached HTML when available."""
        mock_client = AsyncMock()

        with patch("scraper.ebay.get_cache", return_value=EBAY_SOLD_HTML), \
             patch("scraper.ebay.set_cache"):
            results = await scrape_card(mock_client, sample_card, use_cache=True)

        # Should NOT have made an HTTP request
        mock_client.get.assert_not_called()
        # But should still have results from cached HTML
        assert len(results) == 1
        assert results[0].platform == Platform.EBAY
