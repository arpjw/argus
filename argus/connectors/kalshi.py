import base64
import logging
import time
from dataclasses import asdict
from datetime import datetime

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from argus import config
from argus.connectors.types import DataSnapshot, KalshiMarket

logger = logging.getLogger(__name__)

KALSHI_MARKETS_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"

KALSHI_TICKERS: list[str] = [
    "FED-25DEC",
    "CPI-25DEC",
    "INFL-25",
    "RECESSION-25",
    "UNEMP-25DEC",
]


def sign_request(method: str, path: str) -> dict:
    timestamp = str(int(time.time() * 1000))
    message = (timestamp + method.upper() + path).encode()
    private_key = serialization.load_pem_private_key(
        config.KALSHI_PRIVATE_KEY.encode(), password=None
    )
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": config.KALSHI_API_KEY,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
    }


def _parse_market(raw: dict) -> KalshiMarket | None:
    try:
        return KalshiMarket(
            ticker=raw["ticker"],
            title=raw.get("title", raw.get("subtitle", raw["ticker"])),
            yes_price=float(raw.get("yes_ask", raw.get("last_price", 0))) / 100,
            no_price=float(raw.get("no_ask", 0)) / 100,
            timestamp=datetime.utcnow(),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("Could not parse Kalshi market %s: %s", raw.get("ticker"), exc)
        return None


async def fetch_snapshot() -> DataSnapshot:
    now = datetime.utcnow()
    tickers = getattr(config, "KALSHI_TICKERS", KALSHI_TICKERS)
    markets: list[dict] = []

    if not config.KALSHI_API_KEY or not config.KALSHI_PRIVATE_KEY:
        logger.warning("KALSHI_API_KEY or KALSHI_PRIVATE_KEY not set; returning empty snapshot")
        return DataSnapshot(
            source="kalshi",
            timestamp=now,
            payload={"markets": [], "error": "KALSHI credentials not configured"},
        )

    path = "/trade-api/v2/markets"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for ticker in tickers:
                try:
                    resp = await client.get(
                        KALSHI_MARKETS_URL,
                        params={"tickers": ticker},
                        headers=sign_request("GET", path),
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    for raw_market in data.get("markets", []):
                        market = _parse_market(raw_market)
                        if market:
                            d = asdict(market)
                            d["timestamp"] = market.timestamp.isoformat()
                            markets.append(d)
                except Exception as exc:
                    logger.warning("Failed to fetch Kalshi market %s: %s", ticker, exc)
    except Exception as exc:
        logger.error("Kalshi connector error: %s", exc)
        return DataSnapshot(
            source="kalshi",
            timestamp=now,
            payload={"markets": markets, "error": str(exc)},
        )

    return DataSnapshot(source="kalshi", timestamp=now, payload={"markets": markets})
