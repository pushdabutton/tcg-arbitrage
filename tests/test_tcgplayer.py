"""Tests for TCGPlayer scraper (API-based).

Tests cover:
- Best match selection logic
- API result processing
- Full scrape_card flow with mocked HTTP
- Error handling (HTTP errors, malformed JSON, empty results)
- Caching behavior
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.tcgplayer import (
    _build_product_url,
    _build_search_payload,
    _extract_best_match,
    _process_api_results,
    scrape_card,
)
from scraper.models import Card, Platform


# ---------------------------------------------------------------------------
# Realistic API response fixtures
# ---------------------------------------------------------------------------

TCGP_API_RESULTS = [
    {
        "productId": 42382.0,
        "productName": "Charizard",
        "setName": "Base Set",
        "setUrlName": "Base Set",
        "rarityName": "Holo Rare",
        "marketPrice": 555.88,
        "lowestPrice": 185.0,
        "lowestPriceWithShipping": 190.0,
        "totalListings": 113.0,
        "productLineName": "Pokemon",
        "productLineUrlName": "Pokemon",
        "productUrlName": "Charizard",
        "foilOnly": True,
        "sealed": False,
    },
    {
        "productId": 106999.0,
        "productName": "Charizard",
        "setName": "Base Set (Shadowless)",
        "setUrlName": "Base Set Shadowless",
        "rarityName": "Holo Rare",
        "marketPrice": 10000.0,
        "lowestPrice": 965.9,
        "totalListings": 23.0,
        "productLineName": "Pokemon",
    },
    {
        "productId": 42479.0,
        "productName": "Charizard",
        "setName": "Base Set 2",
        "setUrlName": "Base Set 2",
        "rarityName": "Holo Rare",
        "marketPrice": 386.81,
        "lowestPrice": 175.5,
        "totalListings": 59.0,
        "productLineName": "Pokemon",
    },
]

TCGP_API_RESPONSE = {
    "errors": [],
    "results": [
        {
            "aggregations": {},
            "results": TCGP_API_RESULTS,
            "algorithm": "sales_synonym_v2",
            "searchType": "product",
            "totalResults": 7,
            "resultId": "abc123",
        }
    ],
}

TCGP_API_EMPTY_RESPONSE = {
    "errors": [],
    "results": [
        {
            "aggregations": {},
            "results": [],
            "algorithm": "sales_synonym_v2",
            "searchType": "product",
            "totalResults": 0,
        }
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def charizard_card():
    return Card(
        name="Charizard",
        set_name="Base Set",
        pricecharting_id="pokemon-base-set/charizard-4",
    )


@pytest.fixture
def pikachu_card():
    return Card(
        name="Pikachu",
        set_name="Base Set",
        pricecharting_id="pokemon-base-set/pikachu-58",
    )


# ---------------------------------------------------------------------------
# Search payload tests
# ---------------------------------------------------------------------------


class TestBuildSearchPayload:
    def test_payload_structure(self):
        payload = _build_search_payload(size=5)
        assert payload["algorithm"] == "sales_synonym_v2"
        assert payload["size"] == 5
        assert payload["from"] == 0
        assert "pokemon" in payload["filters"]["term"]["productLineName"]

    def test_custom_size(self):
        payload = _build_search_payload(size=10)
        assert payload["size"] == 10


# ---------------------------------------------------------------------------
# Product URL building tests
# ---------------------------------------------------------------------------


class TestBuildProductUrl:
    def test_basic_url(self):
        url = _build_product_url("Charizard", "Base Set", 42382)
        assert "42382" in url
        assert "tcgplayer.com" in url
        assert "charizard" in url.lower()

    def test_url_slug_sanitization(self):
        url = _build_product_url("Charizard EX", "Fire Red & Leaf Green", 12345)
        assert "&" not in url.split("/")[-1]  # Special chars removed from slug


# ---------------------------------------------------------------------------
# Best match selection tests
# ---------------------------------------------------------------------------


class TestExtractBestMatch:
    def test_exact_name_and_set_match(self, charizard_card):
        best = _extract_best_match(TCGP_API_RESULTS, charizard_card)
        assert best is not None
        assert best["productId"] == 42382.0
        assert best["setName"] == "Base Set"

    def test_prefers_exact_set_over_partial(self):
        card = Card(name="Charizard", set_name="Base Set 2")
        best = _extract_best_match(TCGP_API_RESULTS, card)
        assert best is not None
        assert best["setName"] == "Base Set 2"

    def test_no_match_returns_none(self):
        card = Card(name="Zapdos", set_name="Fossil")
        best = _extract_best_match(TCGP_API_RESULTS, card)
        assert best is None

    def test_skips_results_without_price(self):
        results = [
            {
                "productName": "Charizard",
                "setName": "Base Set",
                "marketPrice": None,
                "lowestPrice": None,
            },
        ]
        card = Card(name="Charizard", set_name="Base Set")
        best = _extract_best_match(results, card)
        assert best is None

    def test_partial_name_match(self):
        card = Card(name="Charizard", set_name="Base Set (Shadowless)")
        best = _extract_best_match(TCGP_API_RESULTS, card)
        assert best is not None
        # Should match "Base Set (Shadowless)"
        assert best["setName"] == "Base Set (Shadowless)"

    def test_empty_results(self, charizard_card):
        best = _extract_best_match([], charizard_card)
        assert best is None


# ---------------------------------------------------------------------------
# API result processing tests
# ---------------------------------------------------------------------------


class TestProcessApiResults:
    def test_produces_price_point(self, charizard_card):
        now = datetime.now(timezone.utc)
        points = _process_api_results(TCGP_API_RESULTS, charizard_card, now)
        assert len(points) == 1
        pp = points[0]
        assert pp.platform == Platform.TCGPLAYER
        assert pp.card_name == "Charizard"
        assert pp.set_name == "Base Set"
        assert pp.price_usd == 555.88  # Market price
        assert "tcgplayer.com" in pp.url

    def test_uses_lowest_price_when_no_market_price(self):
        results = [
            {
                "productName": "Pikachu",
                "setName": "Base Set",
                "marketPrice": 0,
                "lowestPrice": 15.50,
                "totalListings": 42,
                "setUrlName": "Base Set",
                "productId": 99999,
            },
        ]
        card = Card(name="Pikachu", set_name="Base Set")
        now = datetime.now(timezone.utc)
        points = _process_api_results(results, card, now)
        assert len(points) == 1
        assert points[0].price_usd == 15.50

    def test_empty_results_returns_empty(self, charizard_card):
        now = datetime.now(timezone.utc)
        points = _process_api_results([], charizard_card, now)
        assert len(points) == 0

    def test_no_matching_card_returns_empty(self, pikachu_card):
        now = datetime.now(timezone.utc)
        # TCGP_API_RESULTS has only Charizard entries
        points = _process_api_results(TCGP_API_RESULTS, pikachu_card, now)
        assert len(points) == 0


# ---------------------------------------------------------------------------
# Full scrape_card flow (mocked HTTP)
# ---------------------------------------------------------------------------


class TestScrapeCard:
    @pytest.mark.asyncio
    async def test_scrape_returns_price_from_api(self, charizard_card):
        """Full flow with mocked API response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=TCGP_API_RESPONSE)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("scraper.tcgplayer.get_cache", return_value=None), \
             patch("scraper.tcgplayer.set_cache"):
            results = await scrape_card(mock_client, charizard_card, use_cache=False)

        assert len(results) == 1
        pp = results[0]
        assert pp.platform == Platform.TCGPLAYER
        assert pp.card_name == "Charizard"
        assert pp.price_usd == 555.88

    @pytest.mark.asyncio
    async def test_scrape_empty_api_results(self, charizard_card):
        """Should return empty list when API returns no results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=TCGP_API_EMPTY_RESPONSE)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("scraper.tcgplayer.get_cache", return_value=None), \
             patch("scraper.tcgplayer.set_cache"):
            results = await scrape_card(mock_client, charizard_card, use_cache=False)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_scrape_handles_http_error(self, charizard_card):
        """Should return empty list on HTTP errors."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 429
        exc = httpx.HTTPStatusError(
            "Too Many Requests",
            request=MagicMock(),
            response=mock_response,
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=exc)

        with patch("scraper.tcgplayer.get_cache", return_value=None):
            results = await scrape_card(mock_client, charizard_card, use_cache=False)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_scrape_handles_connection_error(self, charizard_card):
        """Should return empty list on connection errors."""
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.RequestError("timeout", request=MagicMock())
        )

        with patch("scraper.tcgplayer.get_cache", return_value=None):
            results = await scrape_card(mock_client, charizard_card, use_cache=False)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_scrape_handles_invalid_json(self, charizard_card):
        """Should handle malformed JSON response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(side_effect=json.JSONDecodeError("", "", 0))

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("scraper.tcgplayer.get_cache", return_value=None):
            results = await scrape_card(mock_client, charizard_card, use_cache=False)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_scrape_uses_cache(self, charizard_card):
        """Should use cached API results when available."""
        mock_client = AsyncMock()
        cached_data = json.dumps(TCGP_API_RESULTS)

        with patch("scraper.tcgplayer.get_cache", return_value=cached_data), \
             patch("scraper.tcgplayer.set_cache"):
            results = await scrape_card(mock_client, charizard_card, use_cache=True)

        # Should NOT have made an HTTP request
        mock_client.post.assert_not_called()
        # But should still have results from cache
        assert len(results) == 1
        assert results[0].price_usd == 555.88

    @pytest.mark.asyncio
    async def test_scrape_caches_response(self, charizard_card):
        """Should cache API results after successful fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=TCGP_API_RESPONSE)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("scraper.tcgplayer.get_cache", return_value=None) as mock_get, \
             patch("scraper.tcgplayer.set_cache") as mock_set:
            results = await scrape_card(mock_client, charizard_card, use_cache=True)

        # Should have called set_cache with the API results
        mock_set.assert_called_once()
        cache_key = mock_set.call_args[0][1]
        assert "tcgplayer_api" in cache_key

    @pytest.mark.asyncio
    async def test_handles_unexpected_response_structure(self, charizard_card):
        """Should handle unexpected API response gracefully."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"unexpected": "format"})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("scraper.tcgplayer.get_cache", return_value=None), \
             patch("scraper.tcgplayer.set_cache"):
            results = await scrape_card(mock_client, charizard_card, use_cache=False)

        assert len(results) == 0
