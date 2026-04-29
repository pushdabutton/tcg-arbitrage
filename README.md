# TCG Price Arbitrage Alert Tool

Find cross-platform Pokemon card price differences automatically. Scrapes prices from multiple trading card marketplaces, detects arbitrage opportunities, and serves a real-time dashboard.

## Features

- **Multi-platform price scraping** -- PriceCharting, TCGPlayer, eBay sold listings
- **Arbitrage detection engine** -- flags opportunities where the same card is priced significantly lower on one platform vs another
- **Web dashboard** -- dark-themed, mobile-responsive UI with sortable tables, sparkline charts, and live scrape controls
- **Daemon mode** -- runs on a schedule with automatic re-scraping every 2 hours
- **Email alerts** -- sends formatted alerts (via AgentMail) when high-spread opportunities are found
- **50 seed cards** -- top-traded Pokemon cards from Base Set through Scarlet & Violet

## Quick Start

```bash
# Clone
git clone https://github.com/pushdabutton/tcg-arbitrage.git
cd tcg-arbitrage

# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
mkdir -p data

# Run server only (no scraping)
python main.py

# Scrape 10 cards from PriceCharting + TCGPlayer, then start server
python main.py --scrape --cards 10 --platforms pricecharting tcgplayer

# Daemon mode: scrape all 50 cards, start server, auto-rescrape every 2h
python main.py --daemon --cards 50 --platforms pricecharting tcgplayer
```

Open `http://localhost:8777` to view the dashboard.

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--scrape` | off | Scrape before starting server |
| `--scrape-only` | off | Scrape and exit (no server) |
| `--daemon` | off | Scrape + server + auto-rescrape loop |
| `--cards N` | 5 | Number of seed cards to scrape (max 50) |
| `--platforms` | all | Space-separated: `pricecharting tcgplayer ebay` |
| `--host` | 0.0.0.0 | Server bind address |
| `--port` | 8777 | Server port |
| `--interval` | 7200 | Daemon rescrape interval (seconds) |
| `--alert-threshold` | 30.0 | Min spread % for email alerts |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Web dashboard |
| GET | `/api/health` | Health check |
| GET | `/api/alerts` | Current arbitrage alerts |
| GET | `/api/cards` | All tracked cards with prices |
| GET | `/api/cards/{name}/{set}/prices` | Prices for a specific card |
| GET | `/api/cards/{name}/{set}/history` | Price history for a card |
| GET | `/api/last-scrape` | Last scrape timestamp |
| POST | `/api/scrape?count=N&platforms=X` | Trigger manual scrape |
| POST | `/api/alerts/{id}/dismiss` | Dismiss an alert |

## Architecture

```
tcg-arbitrage/
  main.py              # Entry point, CLI, daemon loop
  config.py            # Settings (env-configurable via TCG_ prefix)
  requirements.txt
  scraper/
    models.py          # PricePoint, Platform, CardInfo dataclasses
    seed_cards.py      # 50 top Pokemon cards
    pricecharting.py   # PriceCharting scraper
    tcgplayer.py       # TCGPlayer internal API scraper
    ebay.py            # eBay sold listings scraper
    cardmarket.py      # Cardmarket (EU) - stub
  engine/
    arbitrage.py       # Cross-platform spread detection
    alerter.py         # Alert storage + email notifications
    database.py        # SQLite with price history, caching, metadata
  api/
    routes.py          # FastAPI endpoints + Jinja2 dashboard
  templates/
    dashboard.html     # Dark-themed responsive dashboard
  tests/               # 129 tests (pytest)
  data/                # SQLite database (gitignored)
```

## Tests

```bash
pytest tests/ -v
```

129 tests covering models, database, arbitrage engine, API routes, and all three scrapers.

## Tech Stack

- **Python 3.12+**
- **FastAPI** + Uvicorn
- **httpx** for async HTTP
- **BeautifulSoup4** for HTML parsing
- **SQLite** (via aiosqlite) for price storage
- **Jinja2** for dashboard templates
- **AgentMail** for email alerts (optional)

## Configuration

All settings can be overridden via environment variables with a `TCG_` prefix:

```bash
export TCG_SCRAPE_DELAY_SECONDS=3.0
export TCG_ARBITRAGE_THRESHOLD_PERCENT=15.0
export TCG_PORT=9000
```

For email alerts, set `AGENT_EMAIL_API_KEY` in your environment or `.env` file.

## License

MIT
