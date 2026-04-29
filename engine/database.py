"""SQLite database operations for TCG Arbitrage."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from scraper.models import ArbitrageOpportunity, Platform, PricePoint, Condition


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    """Create tables if they do not exist."""
    conn = get_connection(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS price_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_name TEXT NOT NULL,
                set_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                price_usd REAL NOT NULL,
                condition TEXT DEFAULT 'ungraded',
                url TEXT DEFAULT '',
                scraped_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_price_card
                ON price_points(card_name, set_name);
            CREATE INDEX IF NOT EXISTS idx_price_platform
                ON price_points(platform);
            CREATE INDEX IF NOT EXISTS idx_price_scraped
                ON price_points(scraped_at);

            CREATE TABLE IF NOT EXISTS arbitrage_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_name TEXT NOT NULL,
                set_name TEXT NOT NULL,
                buy_platform TEXT NOT NULL,
                buy_price REAL NOT NULL,
                sell_platform TEXT NOT NULL,
                sell_price REAL NOT NULL,
                spread_usd REAL NOT NULL,
                spread_percent REAL NOT NULL,
                buy_url TEXT DEFAULT '',
                sell_url TEXT DEFAULT '',
                detected_at TEXT NOT NULL,
                dismissed INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_alert_card
                ON arbitrage_alerts(card_name, set_name);
            CREATE INDEX IF NOT EXISTS idx_alert_dismissed
                ON arbitrage_alerts(dismissed);

            CREATE TABLE IF NOT EXISTS scrape_cache (
                url TEXT PRIMARY KEY,
                response_body TEXT NOT NULL,
                cached_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scrape_meta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                card_count INTEGER NOT NULL,
                platforms TEXT NOT NULL,
                price_points INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_scrape_meta_started
                ON scrape_meta(started_at);
        """)
        conn.commit()
    finally:
        conn.close()


def save_price_point(db_path: Path, pp: PricePoint) -> int:
    """Insert a price point, return its row id."""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO price_points
               (card_name, set_name, platform, price_usd, condition, url, scraped_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                pp.card_name,
                pp.set_name,
                pp.platform.value,
                pp.price_usd,
                pp.condition.value,
                pp.url,
                pp.scraped_at.isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def save_arbitrage_alert(db_path: Path, opp: ArbitrageOpportunity) -> int:
    """Insert an arbitrage alert, return its row id."""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO arbitrage_alerts
               (card_name, set_name, buy_platform, buy_price,
                sell_platform, sell_price, spread_usd, spread_percent,
                buy_url, sell_url, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                opp.card_name,
                opp.set_name,
                opp.buy_platform.value,
                opp.buy_price,
                opp.sell_platform.value,
                opp.sell_price,
                opp.spread_usd,
                opp.spread_percent,
                opp.buy_url,
                opp.sell_url,
                opp.detected_at.isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def get_latest_prices(db_path: Path, card_name: str, set_name: str) -> list[dict]:
    """Get the most recent price from each platform for a card."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT p.*
               FROM price_points p
               INNER JOIN (
                   SELECT platform, MAX(scraped_at) as max_scraped
                   FROM price_points
                   WHERE card_name = ? AND set_name = ?
                   GROUP BY platform
               ) latest
               ON p.platform = latest.platform
                  AND p.scraped_at = latest.max_scraped
               WHERE p.card_name = ? AND p.set_name = ?""",
            (card_name, set_name, card_name, set_name),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_active_alerts(db_path: Path, limit: int = 50) -> list[dict]:
    """Get recent undismissed arbitrage alerts."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT * FROM arbitrage_alerts
               WHERE dismissed = 0
               ORDER BY spread_percent DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_tracked_cards(db_path: Path) -> list[dict]:
    """Get distinct card_name/set_name pairs that have price data."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT DISTINCT card_name, set_name
               FROM price_points
               ORDER BY card_name"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_cache(db_path: Path, url: str, ttl_seconds: int) -> str | None:
    """Return cached response body if still valid, else None."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT response_body, cached_at FROM scrape_cache WHERE url = ?",
            (url,),
        ).fetchone()
        if row is None:
            return None
        cached_at = datetime.fromisoformat(row["cached_at"])
        now = datetime.now(timezone.utc)
        age = (now - cached_at).total_seconds()
        if age > ttl_seconds:
            conn.execute("DELETE FROM scrape_cache WHERE url = ?", (url,))
            conn.commit()
            return None
        return row["response_body"]
    finally:
        conn.close()


def set_cache(db_path: Path, url: str, body: str) -> None:
    """Store or update a cached response."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO scrape_cache (url, response_body, cached_at)
               VALUES (?, ?, ?)""",
            (url, body, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def dismiss_alert(db_path: Path, alert_id: int) -> bool:
    """Mark an alert as dismissed. Return True if found."""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "UPDATE arbitrage_alerts SET dismissed = 1 WHERE id = ?",
            (alert_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def save_scrape_meta(
    db_path: Path,
    card_count: int,
    platforms: list[str],
    price_points: int,
) -> int:
    """Record metadata about a scrape run."""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO scrape_meta (started_at, card_count, platforms, price_points)
               VALUES (?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                card_count,
                json.dumps(platforms),
                price_points,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def get_last_scrape_time(db_path: Path) -> str | None:
    """Get the timestamp of the most recent scrape, or None if never scraped."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT started_at FROM scrape_meta ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return row["started_at"]
    finally:
        conn.close()


def get_price_history(
    db_path: Path,
    card_name: str,
    set_name: str,
    limit: int = 20,
) -> list[dict]:
    """Get price history for a card across all platforms, most recent first.

    Returns list of dicts with platform, price_usd, scraped_at.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT platform, price_usd, scraped_at
               FROM price_points
               WHERE card_name = ? AND set_name = ?
               ORDER BY scraped_at DESC
               LIMIT ?""",
            (card_name, set_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
