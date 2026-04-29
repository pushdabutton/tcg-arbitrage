"""Tests for database operations."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.database import (
    dismiss_alert,
    get_active_alerts,
    get_all_tracked_cards,
    get_cache,
    get_last_scrape_time,
    get_latest_prices,
    get_price_history,
    init_db,
    save_arbitrage_alert,
    save_price_point,
    save_scrape_meta,
    set_cache,
)
from scraper.models import (
    ArbitrageOpportunity,
    Condition,
    Platform,
    PricePoint,
)


def test_init_db_creates_tables(tmp_db):
    """init_db should create all required tables."""
    import sqlite3

    conn = sqlite3.connect(str(tmp_db))
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {t[0] for t in tables}
    conn.close()

    assert "price_points" in table_names
    assert "arbitrage_alerts" in table_names
    assert "scrape_cache" in table_names


def test_save_and_get_price_point(tmp_db):
    """Save a price point and retrieve it."""
    pp = PricePoint(
        card_name="Charizard",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=350.00,
        condition=Condition.UNGRADED,
        url="https://example.com/charizard",
    )
    row_id = save_price_point(tmp_db, pp)
    assert row_id is not None
    assert row_id > 0

    prices = get_latest_prices(tmp_db, "Charizard", "Base Set")
    assert len(prices) == 1
    assert prices[0]["price_usd"] == 350.00
    assert prices[0]["platform"] == "pricecharting"


def test_latest_prices_per_platform(tmp_db):
    """get_latest_prices returns one row per platform+condition (the most recent)."""
    now = datetime.now(timezone.utc)

    # Save two prices for same platform -- only latest should return
    pp1 = PricePoint(
        card_name="Pikachu",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=10.00,
        scraped_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    pp2 = PricePoint(
        card_name="Pikachu",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=12.00,
        scraped_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    pp3 = PricePoint(
        card_name="Pikachu",
        set_name="Base Set",
        platform=Platform.TCGPLAYER,
        price_usd=15.00,
        condition=Condition.NEAR_MINT,
    )

    save_price_point(tmp_db, pp1)
    save_price_point(tmp_db, pp2)
    save_price_point(tmp_db, pp3)

    prices = get_latest_prices(tmp_db, "Pikachu", "Base Set")
    assert len(prices) == 2

    platforms = {p["platform"] for p in prices}
    assert platforms == {"pricecharting", "tcgplayer"}

    pc_price = next(p for p in prices if p["platform"] == "pricecharting")
    assert pc_price["price_usd"] == 12.00  # Latest


def test_latest_prices_excludes_graded_by_default(tmp_db):
    """get_latest_prices with raw_only=True should not return graded slabs."""
    pp_raw = PricePoint(
        card_name="Charizard",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=26.00,
        condition=Condition.UNGRADED,
    )
    pp_psa10 = PricePoint(
        card_name="Charizard",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=1482.00,
        condition=Condition.PSA_10,
    )
    save_price_point(tmp_db, pp_raw)
    save_price_point(tmp_db, pp_psa10)

    # Default (raw_only=True) should exclude PSA 10
    prices = get_latest_prices(tmp_db, "Charizard", "Base Set")
    assert len(prices) == 1
    assert prices[0]["price_usd"] == 26.00

    # raw_only=False should include both
    all_prices = get_latest_prices(tmp_db, "Charizard", "Base Set", raw_only=False)
    assert len(all_prices) == 2


def test_save_and_get_arbitrage_alert(tmp_db):
    """Save an arbitrage alert and retrieve it."""
    opp = ArbitrageOpportunity(
        card_name="Charizard",
        set_name="Base Set",
        buy_platform=Platform.PRICECHARTING,
        buy_price=300.00,
        sell_platform=Platform.TCGPLAYER,
        sell_price=400.00,
        buy_url="https://pc.com/charizard",
        sell_url="https://tcg.com/charizard",
    )
    row_id = save_arbitrage_alert(tmp_db, opp)
    assert row_id > 0

    alerts = get_active_alerts(tmp_db)
    assert len(alerts) == 1
    assert alerts[0]["card_name"] == "Charizard"
    assert alerts[0]["spread_usd"] == 100.00


def test_duplicate_alert_updates_instead_of_inserting(tmp_db):
    """BUG 2: Re-saving same card+platforms should update, not create duplicate."""
    opp1 = ArbitrageOpportunity(
        card_name="Charizard",
        set_name="Base Set",
        buy_platform=Platform.PRICECHARTING,
        buy_price=300.00,
        sell_platform=Platform.TCGPLAYER,
        sell_price=400.00,
    )
    id1 = save_arbitrage_alert(tmp_db, opp1)

    # Save again with updated prices -- should update, not create duplicate
    opp2 = ArbitrageOpportunity(
        card_name="Charizard",
        set_name="Base Set",
        buy_platform=Platform.PRICECHARTING,
        buy_price=310.00,
        sell_platform=Platform.TCGPLAYER,
        sell_price=420.00,
    )
    id2 = save_arbitrage_alert(tmp_db, opp2)

    # Should be same row id (updated, not new)
    assert id2 == id1

    alerts = get_active_alerts(tmp_db)
    assert len(alerts) == 1  # No duplicate!
    assert alerts[0]["buy_price"] == 310.00  # Updated price
    assert alerts[0]["sell_price"] == 420.00


def test_duplicate_alert_different_platforms_creates_new(tmp_db):
    """Different platform pair should create a new alert."""
    opp1 = ArbitrageOpportunity(
        card_name="Charizard",
        set_name="Base Set",
        buy_platform=Platform.PRICECHARTING,
        buy_price=300.00,
        sell_platform=Platform.TCGPLAYER,
        sell_price=400.00,
    )
    opp2 = ArbitrageOpportunity(
        card_name="Charizard",
        set_name="Base Set",
        buy_platform=Platform.TCGPLAYER,
        buy_price=350.00,
        sell_platform=Platform.PRICECHARTING,
        sell_price=500.00,
    )
    save_arbitrage_alert(tmp_db, opp1)
    save_arbitrage_alert(tmp_db, opp2)

    alerts = get_active_alerts(tmp_db)
    assert len(alerts) == 2  # Different direction = different alert


def test_dismissed_alert_allows_new_insert(tmp_db):
    """After dismissing, a new alert for the same card+platforms should insert."""
    opp = ArbitrageOpportunity(
        card_name="Charizard",
        set_name="Base Set",
        buy_platform=Platform.PRICECHARTING,
        buy_price=300.00,
        sell_platform=Platform.TCGPLAYER,
        sell_price=400.00,
    )
    alert_id = save_arbitrage_alert(tmp_db, opp)
    dismiss_alert(tmp_db, alert_id)

    # New alert should insert (dismissed old one doesn't block)
    opp2 = ArbitrageOpportunity(
        card_name="Charizard",
        set_name="Base Set",
        buy_platform=Platform.PRICECHARTING,
        buy_price=310.00,
        sell_platform=Platform.TCGPLAYER,
        sell_price=450.00,
    )
    new_id = save_arbitrage_alert(tmp_db, opp2)
    assert new_id != alert_id

    alerts = get_active_alerts(tmp_db)
    assert len(alerts) == 1
    assert alerts[0]["buy_price"] == 310.00


def test_dismiss_alert(tmp_db):
    """Dismissed alerts should not appear in active alerts."""
    opp = ArbitrageOpportunity(
        card_name="Blastoise",
        set_name="Base Set",
        buy_platform=Platform.PRICECHARTING,
        buy_price=50.00,
        sell_platform=Platform.TCGPLAYER,
        sell_price=70.00,
    )
    alert_id = save_arbitrage_alert(tmp_db, opp)

    assert len(get_active_alerts(tmp_db)) == 1

    result = dismiss_alert(tmp_db, alert_id)
    assert result is True

    assert len(get_active_alerts(tmp_db)) == 0


def test_dismiss_nonexistent_alert(tmp_db):
    """Dismissing a nonexistent alert returns False."""
    result = dismiss_alert(tmp_db, 99999)
    assert result is False


def test_get_all_tracked_cards(tmp_db):
    """get_all_tracked_cards returns distinct card/set pairs."""
    pp1 = PricePoint(
        card_name="Charizard",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=350.00,
    )
    pp2 = PricePoint(
        card_name="Charizard",
        set_name="Base Set",
        platform=Platform.TCGPLAYER,
        price_usd=400.00,
    )
    pp3 = PricePoint(
        card_name="Pikachu",
        set_name="Jungle",
        platform=Platform.PRICECHARTING,
        price_usd=5.00,
    )
    save_price_point(tmp_db, pp1)
    save_price_point(tmp_db, pp2)
    save_price_point(tmp_db, pp3)

    cards = get_all_tracked_cards(tmp_db)
    assert len(cards) == 2
    names = {c["card_name"] for c in cards}
    assert names == {"Charizard", "Pikachu"}


def test_cache_set_and_get(tmp_db):
    """Cache set/get should work within TTL."""
    set_cache(tmp_db, "https://example.com/test", '{"price": 42}')
    result = get_cache(tmp_db, "https://example.com/test", ttl_seconds=3600)
    assert result == '{"price": 42}'


def test_cache_miss(tmp_db):
    """Cache should return None for unknown URL."""
    result = get_cache(tmp_db, "https://example.com/nope", ttl_seconds=3600)
    assert result is None


def test_init_db_creates_scrape_meta_table(tmp_db):
    """init_db should create the scrape_meta table."""
    import sqlite3

    conn = sqlite3.connect(str(tmp_db))
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {t[0] for t in tables}
    conn.close()

    assert "scrape_meta" in table_names


def test_save_and_get_scrape_meta(tmp_db):
    """Save scrape metadata and retrieve last scrape time."""
    row_id = save_scrape_meta(
        tmp_db,
        card_count=10,
        platforms=["pricecharting", "tcgplayer"],
        price_points=20,
    )
    assert row_id > 0

    last = get_last_scrape_time(tmp_db)
    assert last is not None
    assert "T" in last  # ISO format


def test_get_last_scrape_time_none_when_empty(tmp_db):
    """get_last_scrape_time returns None if no scrapes recorded."""
    last = get_last_scrape_time(tmp_db)
    assert last is None


def test_get_last_scrape_time_returns_most_recent(tmp_db):
    """Multiple scrapes: should return the most recent one."""
    save_scrape_meta(tmp_db, card_count=5, platforms=["pricecharting"], price_points=5)
    save_scrape_meta(tmp_db, card_count=10, platforms=["pricecharting", "tcgplayer"], price_points=15)

    last = get_last_scrape_time(tmp_db)
    assert last is not None


def test_get_price_history(tmp_db):
    """get_price_history returns ordered price records."""
    pp1 = PricePoint(
        card_name="Charizard",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=300.0,
        scraped_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    pp2 = PricePoint(
        card_name="Charizard",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=350.0,
        scraped_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    pp3 = PricePoint(
        card_name="Charizard",
        set_name="Base Set",
        platform=Platform.TCGPLAYER,
        price_usd=400.0,
        condition=Condition.NEAR_MINT,
        scraped_at=datetime(2025, 6, 2, tzinfo=timezone.utc),
    )
    save_price_point(tmp_db, pp1)
    save_price_point(tmp_db, pp2)
    save_price_point(tmp_db, pp3)

    history = get_price_history(tmp_db, "Charizard", "Base Set", limit=10)
    assert len(history) == 3
    # Most recent first
    assert history[0]["price_usd"] == 400.0
    assert history[0]["platform"] == "tcgplayer"


def test_get_price_history_excludes_graded_by_default(tmp_db):
    """BUG 9: Sparkline should not mix graded and raw prices."""
    pp_raw = PricePoint(
        card_name="Charizard",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=26.0,
        condition=Condition.UNGRADED,
        scraped_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    pp_psa10 = PricePoint(
        card_name="Charizard",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=1482.0,
        condition=Condition.PSA_10,
        scraped_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )
    pp_psa9 = PricePoint(
        card_name="Charizard",
        set_name="Base Set",
        platform=Platform.PRICECHARTING,
        price_usd=800.0,
        condition=Condition.PSA_9,
        scraped_at=datetime(2025, 1, 3, tzinfo=timezone.utc),
    )
    save_price_point(tmp_db, pp_raw)
    save_price_point(tmp_db, pp_psa10)
    save_price_point(tmp_db, pp_psa9)

    # Default (raw_only=True) should only return the raw card
    history = get_price_history(tmp_db, "Charizard", "Base Set")
    assert len(history) == 1
    assert history[0]["price_usd"] == 26.0

    # raw_only=False returns all
    all_history = get_price_history(
        tmp_db, "Charizard", "Base Set", raw_only=False
    )
    assert len(all_history) == 3


def test_get_price_history_respects_limit(tmp_db):
    """Limit parameter caps results."""
    for i in range(10):
        pp = PricePoint(
            card_name="Pikachu",
            set_name="Base Set",
            platform=Platform.PRICECHARTING,
            price_usd=float(10 + i),
            scraped_at=datetime(2025, 1, i + 1, tzinfo=timezone.utc),
        )
        save_price_point(tmp_db, pp)

    history = get_price_history(tmp_db, "Pikachu", "Base Set", limit=3)
    assert len(history) == 3


def test_get_price_history_empty_card(tmp_db):
    """No data returns empty list."""
    history = get_price_history(tmp_db, "NonExistent", "FakeSet")
    assert history == []
