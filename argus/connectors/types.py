from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NewsItem:
    headline: str
    source: str
    url: str
    timestamp: datetime
    instruments: list[str] = field(default_factory=list)


@dataclass
class DataSnapshot:
    source: str
    timestamp: datetime
    payload: dict[str, Any]


@dataclass
class OHLCVBar:
    instrument: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class MacroRelease:
    series_id: str
    name: str
    value: float
    timestamp: datetime
    previous: float | None = None


@dataclass
class KalshiMarket:
    ticker: str
    title: str
    yes_price: float
    no_price: float
    timestamp: datetime
