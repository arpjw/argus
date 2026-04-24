import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_ENABLED: bool = os.getenv("TELEGRAM_ENABLED", "false").lower() in ("1", "true", "yes")
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
KALSHI_API_KEY: str = os.getenv("KALSHI_API_KEY", "")
KALSHI_PRIVATE_KEY: str = os.getenv("KALSHI_PRIVATE_KEY", "")
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")
UNUSUAL_WHALES_API_KEY: str = os.getenv("UNUSUAL_WHALES_API_KEY", "")
NORGATE_DATA_PATH: str = os.getenv("NORGATE_DATA_PATH", "")
ARGUS_API_KEY: str = os.getenv("ARGUS_API_KEY", "")

SIGMA_THRESHOLD: float = float(os.getenv("SIGMA_THRESHOLD", "2.0"))
CORR_THRESHOLD: float = float(os.getenv("CORR_THRESHOLD", "0.3"))
KALSHI_GAP_THRESHOLD: float = float(os.getenv("KALSHI_GAP_THRESHOLD", "0.05"))
HEARTBEAT_INTERVAL: int = int(os.getenv("HEARTBEAT_INTERVAL", "900"))
NEWS_POLL_INTERVAL: int = int(os.getenv("NEWS_POLL_INTERVAL", "60"))

DB_PATH: str = os.getenv("DB_PATH", "./data/argus.db")

INSTRUMENTS: list[str] = [
    "ES", "NQ", "RTY", "YM",
    "CL", "NG",
    "GC", "SI",
    "ZB", "ZN",
    "ZC", "ZS", "ZW",
    "6E", "6J", "6B", "6A",
    "HG", "VX", "BTC",
]
