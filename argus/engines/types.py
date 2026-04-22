from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass
class AnomalyFlag:
    instrument: str
    type: str
    severity: Literal["low", "medium", "high"]
    description: str
    timestamp: datetime


@dataclass
class SentimentScore:
    instrument: str
    score: float  # -1.0 (bearish) to 1.0 (bullish)
    source: str
    timestamp: datetime
    headline_count: int = 0
