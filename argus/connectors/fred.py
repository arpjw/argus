import logging
from dataclasses import asdict
from datetime import datetime

import httpx

from argus import config
from argus.connectors.types import DataSnapshot, MacroRelease

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

FRED_SERIES: list[str] = ["UNRATE", "CPIAUCSL", "DFF", "T10Y2Y", "VIXCLS", "DTWEXBGS"]

_SERIES_NAMES: dict[str, str] = {
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "CPI All Urban Consumers",
    "DFF": "Federal Funds Effective Rate",
    "T10Y2Y": "10Y-2Y Treasury Spread",
    "VIXCLS": "CBOE Volatility Index",
    "DTWEXBGS": "Trade Weighted USD Index",
}


def _parse_observation(series_id: str, obs: list[dict]) -> MacroRelease | None:
    valid = [o for o in obs if o.get("value", ".") != "."]
    if not valid:
        return None
    latest = valid[-1]
    previous = valid[-2] if len(valid) >= 2 else None
    try:
        ts = datetime.fromisoformat(latest["date"])
    except (KeyError, ValueError):
        ts = datetime.utcnow()
    return MacroRelease(
        series_id=series_id,
        name=_SERIES_NAMES.get(series_id, series_id),
        value=float(latest["value"]),
        timestamp=ts,
        previous=float(previous["value"]) if previous else None,
    )


async def fetch_snapshot() -> DataSnapshot:
    now = datetime.utcnow()
    series_list = getattr(config, "FRED_SERIES", FRED_SERIES)
    releases: list[dict] = []

    if not config.FRED_API_KEY:
        logger.warning("FRED_API_KEY not set; returning empty snapshot")
        return DataSnapshot(
            source="fred",
            timestamp=now,
            payload={"releases": [], "error": "FRED_API_KEY not configured"},
        )

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for series_id in series_list:
                try:
                    resp = await client.get(
                        FRED_BASE,
                        params={
                            "series_id": series_id,
                            "api_key": config.FRED_API_KEY,
                            "file_type": "json",
                            "sort_order": "desc",
                            "limit": "2",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    obs = data.get("observations", [])
                    # desc order — reverse to get [prev, latest]
                    release = _parse_observation(series_id, list(reversed(obs)))
                    if release:
                        d = asdict(release)
                        d["timestamp"] = release.timestamp.isoformat()
                        releases.append(d)
                    else:
                        logger.debug("No valid observations for series %s", series_id)
                except Exception as exc:
                    logger.warning("Failed to fetch FRED series %s: %s", series_id, exc)
    except Exception as exc:
        logger.error("FRED connector error: %s", exc)
        return DataSnapshot(
            source="fred",
            timestamp=now,
            payload={"releases": releases, "error": str(exc)},
        )

    return DataSnapshot(source="fred", timestamp=now, payload={"releases": releases})
