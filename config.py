"""Configuration for TCG Arbitrage Alert Tool."""

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load .env from home directory (contains AGENT_EMAIL_API_KEY etc.)
load_dotenv(Path.home() / ".env")
load_dotenv()  # Also check local .env


class Settings(BaseSettings):
    """Application settings loaded from environment or defaults."""

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent
    DB_PATH: Path = Path(__file__).resolve().parent / "data" / "cards.db"

    # Scraping
    SCRAPE_DELAY_SECONDS: float = 2.0  # Minimum delay between requests
    CACHE_TTL_SECONDS: int = 3600  # 1 hour cache
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    REQUEST_TIMEOUT: float = 15.0

    # Arbitrage
    ARBITRAGE_THRESHOLD_PERCENT: float = 20.0  # Flag when price diff >= 20%
    EMAIL_ALERT_THRESHOLD_PERCENT: float = 30.0  # Send email when diff >= 30%

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8777

    # Daemon
    DAEMON_INTERVAL_SECONDS: int = 7200  # 2 hours between auto-scrapes

    model_config = {"env_prefix": "TCG_"}


settings = Settings()
