import logging
import statistics
import time
from datetime import datetime

import httpx

from argus.connectors.types import DataSnapshot

logger = logging.getLogger(__name__)

CFTC_BASE = "https://publicreporting.cftc.gov/api/explore/dataset/com-disagg/records/"

COT_INSTRUMENTS: dict[str, str] = {
    "ES": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
    "NQ": "E-MINI NASDAQ-100 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE",
    "CL": "CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE",
    "GC": "GOLD - COMMODITY EXCHANGE INC.",
    "ZB": "U.S. TREASURY BONDS - CHICAGO BOARD OF TRADE",
    "ZN": "10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE",
    "6E": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    "6J": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
    "BTC": "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
}

# Disaggregated COT field names in the CFTC Opendatasoft API:
# "commercial" → Producer/Merchant/Processor/User (the hedger category)
# "noncommercial" → Managed Money (the speculator category)
_COMM_LONG = "prod_merc_positions_long_all"
_COMM_SHORT = "prod_merc_positions_short_all"
_SPEC_LONG = "m_money_positions_long_all"
_SPEC_SHORT = "m_money_positions_short_all"
_REPORT_DATE = "report_date_as_yyyy_mm_dd"

_CACHE_TTL = 6 * 3600  # COT is weekly; 6-hour cache is sufficient

_cache: dict = {}


def _parse_row(fields: dict) -> tuple[int, int, int, int, str] | None:
    try:
        return (
            int(fields[_COMM_LONG]),
            int(fields[_COMM_SHORT]),
            int(fields[_SPEC_LONG]),
            int(fields[_SPEC_SHORT]),
            str(fields[_REPORT_DATE])[:10],
        )
    except (KeyError, TypeError, ValueError):
        return None


async def fetch_snapshot() -> DataSnapshot:
    now = datetime.utcnow()

    cached = _cache.get("snapshot")
    if cached is not None and (time.time() - _cache.get("fetched_at", 0.0)) < _CACHE_TTL:
        return cached

    positions: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for instrument, market_name in COT_INSTRUMENTS.items():
                try:
                    resp = await client.get(
                        CFTC_BASE,
                        params={
                            "limit": "4",
                            "refine.market_and_exchange_names": market_name,
                            "sort": "-report_date_as_yyyy_mm_dd",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    rows = []
                    for rec in data.get("records", []):
                        row = _parse_row(rec.get("fields", {}))
                        if row:
                            rows.append(row)

                    if not rows:
                        logger.debug("No COT records for %s", instrument)
                        continue

                    # API returns newest-first; reverse so index 0 is oldest
                    rows.reverse()

                    comm_long, comm_short, nc_long, nc_short, report_date = rows[-1]
                    commercial_net = comm_long - comm_short
                    noncommercial_net = nc_long - nc_short

                    if len(rows) >= 2:
                        prev = rows[-2]
                        commercial_net_change = commercial_net - (prev[0] - prev[1])
                    else:
                        commercial_net_change = 0

                    nc_nets = [r[2] - r[3] for r in rows]
                    if len(nc_nets) >= 2:
                        mean_nc = statistics.mean(nc_nets)
                        stdev_nc = statistics.stdev(nc_nets)
                        noncommercial_z_score = (
                            round((noncommercial_net - mean_nc) / stdev_nc, 1)
                            if stdev_nc != 0
                            else 0.0
                        )
                    else:
                        noncommercial_z_score = 0.0

                    positions.append(
                        {
                            "instrument": instrument,
                            "commercial_net": commercial_net,
                            "noncommercial_net": noncommercial_net,
                            "commercial_net_change": commercial_net_change,
                            "noncommercial_z_score": noncommercial_z_score,
                            "report_date": report_date,
                        }
                    )

                except Exception as exc:
                    logger.warning("COT fetch failed for %s: %s", instrument, exc)

    except Exception as exc:
        logger.warning("COT connector error: %s", exc)
        return DataSnapshot(source="cot", timestamp=now, payload={"positions": []})

    snapshot = DataSnapshot(source="cot", timestamp=now, payload={"positions": positions})
    _cache["snapshot"] = snapshot
    _cache["fetched_at"] = time.time()
    return snapshot
