import asyncio
import logging
from datetime import datetime

import pandas as pd
import yfinance as yf

from argus.connectors.types import DataSnapshot

logger = logging.getLogger(__name__)

TICKER_MAP = {
    "ES": "ES=F", "NQ": "NQ=F", "RTY": "RTY=F", "YM": "YM=F",
    "CL": "CL=F", "NG": "NG=F", "GC": "GC=F", "SI": "SI=F",
    "ZB": "ZB=F", "ZN": "ZN=F", "ZC": "ZC=F", "ZS": "ZS=F",
    "ZW": "ZW=F", "6E": "6E=F", "6J": "6J=F", "6B": "6B=F",
    "6A": "6A=F", "HG": "HG=F", "VX": "VX=F", "BTC": "BTC-USD",
}

price_buffer: dict[str, list[dict]] = {}


def _fetch_instrument(instrument: str, ticker: str) -> list[dict]:
    try:
        df = yf.download(ticker, period="5d", interval="5m", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return []
        # droplevel is safer than tuple indexing — avoids duplicate column names
        # when yfinance returns (field, ticker) MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        for col in ("Open", "High", "Low", "Close", "Volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Close"])
        if df.empty:
            return []
        bars: list[dict] = []
        for ts, row in df.iterrows():
            bars.append({
                "instrument": instrument,
                "timestamp": ts.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            })
        return bars
    except Exception as exc:
        logger.warning("_fetch_instrument failed for %s (%s): %s", instrument, ticker, exc)
        return []


async def fetch_snapshot() -> DataSnapshot:
    tasks = [
        asyncio.to_thread(_fetch_instrument, instrument, ticker)
        for instrument, ticker in TICKER_MAP.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_bars: list[dict] = []
    for instrument, result in zip(TICKER_MAP.keys(), results):
        if isinstance(result, Exception):
            logger.warning("fetch for %s raised: %s", instrument, result)
            continue
        bars: list[dict] = result  # type: ignore[assignment]
        if not bars:
            continue
        price_buffer[instrument] = bars[-200:]
        all_bars.extend(bars)

    return DataSnapshot(
        source="prices",
        timestamp=datetime.utcnow(),
        payload={"bars": all_bars},
    )
