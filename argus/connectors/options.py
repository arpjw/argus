import logging
import time
from datetime import datetime

import httpx

from argus import config
from argus.connectors.types import DataSnapshot

logger = logging.getLogger(__name__)

_API_URL = "https://api.unusualwhales.com/api/option-trades/flow-alerts"
_CACHE_TTL = 300  # 5 minutes

_cache: dict = {}
_warned_no_key: bool = False

_TICKER_MAP: dict[str, str] = {
    "SPY": "ES",
    "SPX": "ES",
    "QQQ": "NQ",
    "GLD": "GC",
    "USO": "CL",
    "TLT": "ZB",
    "IEF": "ZN",
    "BTC": "BTC",
}


async def fetch_snapshot() -> DataSnapshot | None:
    global _warned_no_key
    now = datetime.utcnow()

    if not config.UNUSUAL_WHALES_API_KEY:
        if not _warned_no_key:
            logger.warning("UNUSUAL_WHALES_API_KEY not set; options flow disabled")
            _warned_no_key = True
        return None

    cached = _cache.get("snapshot")
    if cached is not None and (time.time() - _cache.get("fetched_at", 0.0)) < _CACHE_TTL:
        return cached

    flows: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                _API_URL,
                params={"limit": "50"},
                headers={"Authorization": f"Bearer {config.UNUSUAL_WHALES_API_KEY}"},
            )
            resp.raise_for_status()
            data = resp.json()

            raw_items = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(raw_items, list):
                raw_items = []

            for item in raw_items:
                try:
                    ticker = str(item.get("ticker", item.get("symbol", "")) or "")
                    side = str(item.get("type", item.get("call_or_put", "")) or "").lower()
                    premium = float(item.get("total_premium", item.get("premium", 0)) or 0)
                    dte = int(item.get("dte", 0) or 0)
                    strike = float(item.get("strike_price", item.get("strike", 0)) or 0)
                    expiry = str(item.get("expiry", item.get("expiration_date", "")) or "")
                    timestamp = str(
                        item.get("timestamp", item.get("created_at", now.isoformat())) or ""
                    )

                    if premium <= 500_000 or dte <= 7:
                        continue

                    instrument = _TICKER_MAP.get(ticker.upper(), ticker)
                    sentiment = (
                        "bullish" if side == "call" else "bearish" if side == "put" else "neutral"
                    )

                    flows.append({
                        "ticker": ticker,
                        "instrument": instrument,
                        "side": side,
                        "premium": premium,
                        "strike": strike,
                        "expiry": expiry,
                        "dte": dte,
                        "sentiment": sentiment,
                        "timestamp": timestamp,
                    })
                except (TypeError, ValueError):
                    continue

    except Exception as exc:
        logger.warning("Options flow fetch failed: %s", exc)
        return DataSnapshot(source="options", timestamp=now, payload={"flows": []})

    snapshot = DataSnapshot(source="options", timestamp=now, payload={"flows": flows})
    _cache["snapshot"] = snapshot
    _cache["fetched_at"] = time.time()
    return snapshot
