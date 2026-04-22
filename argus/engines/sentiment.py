import logging
from datetime import datetime

from argus.connectors.types import DataSnapshot, NewsItem
from argus.engines.types import SentimentScore

logger = logging.getLogger(__name__)

INSTRUMENT_KEYWORDS: dict[str, list[str]] = {
    "ES":  ["S&P", "SPX", "S&P 500", "sp500", "equity", "equities", "stocks", "stock market"],
    "NQ":  ["nasdaq", "NASDAQ", "tech stocks", "QQQ", "NDX"],
    "RTY": ["russell", "Russell 2000", "small cap", "smallcap", "RTY"],
    "YM":  ["dow", "Dow Jones", "DJIA", "blue chip"],
    "CL":  ["crude", "oil", "WTI", "Brent", "OPEC", "petroleum", "barrel"],
    "NG":  ["natural gas", "natgas", "LNG", "Henry Hub"],
    "GC":  ["gold", "XAU", "bullion", "precious metals"],
    "SI":  ["silver", "XAG"],
    "ZB":  ["treasury", "treasuries", "bonds", "bond market", "yield", "yields", "Fed", "FOMC",
            "interest rate", "rates", "monetary policy"],
    "ZN":  ["10-year", "10 year", "note", "T-note", "treasury note"],
    "ZC":  ["corn", "maize", "crop", "grain"],
    "ZS":  ["soybean", "soybeans", "soy"],
    "ZW":  ["wheat", "grain"],
    "6E":  ["euro", "EUR", "EUR/USD", "eurozone", "ECB"],
    "6J":  ["yen", "JPY", "USD/JPY", "BOJ", "Bank of Japan"],
    "6B":  ["pound", "sterling", "GBP", "cable", "BOE", "Bank of England"],
    "6A":  ["aussie", "AUD", "Australian dollar", "RBA"],
    "HG":  ["copper", "HG", "industrial metals"],
    "VX":  ["VIX", "volatility", "fear index", "options volatility"],
    "BTC": ["bitcoin", "Bitcoin", "crypto", "cryptocurrency", "BTC", "digital asset"],
}

# Maps Kalshi ticker substrings to affected futures instruments
KALSHI_INSTRUMENT_MAP: dict[str, list[str]] = {
    "FED":       ["ZB", "ZN"],
    "CPI":       ["ZB", "ZN", "GC", "ES"],
    "INFL":      ["ZB", "ZN", "GC", "ES"],
    "RECESSION": ["ES", "NQ", "ZB", "GC"],
    "UNEMP":     ["ES", "NQ", "ZB"],
    "GDP":       ["ES", "NQ", "ZB"],
    "NFP":       ["ES", "ZB"],
    "RATE":      ["ZB", "ZN", "ES"],
    "OIL":       ["CL"],
    "CRUDE":     ["CL"],
    "GOLD":      ["GC"],
    "BITCOIN":   ["BTC"],
    "CRYPTO":    ["BTC"],
    "TRADE":     ["ES", "NQ", "6E", "6J"],
    "TARIFF":    ["ES", "NQ", "6E", "6J"],
    "DEBT":      ["ZB", "ZN"],
    "DEFAULT":   ["ZB", "ZN", "ES"],
}


def _kalshi_instruments(ticker: str) -> list[str]:
    ticker_upper = ticker.upper()
    for key, instruments in KALSHI_INSTRUMENT_MAP.items():
        if key in ticker_upper:
            return instruments
    return []


def _headline_instruments(headline: str) -> list[str]:
    headline_lower = headline.lower()
    matched: list[str] = []
    for instrument, keywords in INSTRUMENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in headline_lower:
                matched.append(instrument)
                break
    return matched


class SentimentScorer:
    def __init__(self) -> None:
        self._pipeline = None

    def _load_pipeline(self) -> None:
        if self._pipeline is not None:
            return
        try:
            from transformers import pipeline  # type: ignore
            self._pipeline = pipeline(
                "text-classification",
                model="ProsusAI/finbert",
            )
        except Exception as exc:
            logger.warning("FinBERT unavailable: %s", exc)
            self._pipeline = None

    def score_kalshi(
        self,
        kalshi_snapshot: DataSnapshot,
        prev_snapshot: DataSnapshot | None,
    ) -> list[SentimentScore]:
        if prev_snapshot is None:
            return []

        now = kalshi_snapshot.timestamp
        current_markets: dict[str, float] = {
            m["ticker"]: m["yes_price"]
            for m in kalshi_snapshot.payload.get("markets", [])
        }
        prev_markets: dict[str, float] = {
            m["ticker"]: m["yes_price"]
            for m in prev_snapshot.payload.get("markets", [])
        }

        scores: dict[str, list[float]] = {}
        for ticker, yes_price in current_markets.items():
            if ticker not in prev_markets:
                continue
            delta = yes_price - prev_markets[ticker]
            raw_score = max(-1.0, min(1.0, delta * 10))
            for instrument in _kalshi_instruments(ticker):
                scores.setdefault(instrument, []).append(raw_score)

        result: list[SentimentScore] = []
        for instrument, vals in scores.items():
            result.append(SentimentScore(
                instrument=instrument,
                score=sum(vals) / len(vals),
                source="kalshi",
                timestamp=now,
            ))
        return result

    def score_news(self, news_items: list[NewsItem]) -> list[SentimentScore]:
        if not news_items:
            return []

        self._load_pipeline()
        now = datetime.utcnow()

        # instrument -> list of (sentiment_score, abs_weight)
        grouped: dict[str, list[tuple[float, float]]] = {}

        for item in news_items:
            instruments = item.instruments if item.instruments else _headline_instruments(item.headline)
            if not instruments:
                continue

            raw_score = 0.0
            source_tag = "finbert_unavailable"

            if self._pipeline is not None:
                try:
                    result = self._pipeline(item.headline, truncation=True, max_length=512)
                    label: str = result[0]["label"].lower()
                    conf: float = float(result[0]["score"])
                    if label == "positive":
                        raw_score = conf
                    elif label == "negative":
                        raw_score = -conf
                    else:
                        raw_score = 0.0
                    source_tag = "finbert"
                except Exception as exc:
                    logger.warning("FinBERT inference failed for headline '%s': %s", item.headline[:60], exc)
                    raw_score = 0.0
                    source_tag = "finbert_unavailable"

            weight = abs(raw_score) if raw_score != 0.0 else 1e-6
            for instrument in instruments:
                grouped.setdefault(instrument, []).append((raw_score, weight))

        result_list: list[SentimentScore] = []
        for instrument, pairs in grouped.items():
            total_weight = sum(w for _, w in pairs)
            weighted_sum = sum(s * w for s, w in pairs)
            agg_score = weighted_sum / total_weight if total_weight > 0 else 0.0
            # Use finbert_unavailable if any call fell back
            sources = {
                "finbert_unavailable" if self._pipeline is None else "finbert"
            }
            result_list.append(SentimentScore(
                instrument=instrument,
                score=max(-1.0, min(1.0, agg_score)),
                source=next(iter(sources)),
                timestamp=now,
                headline_count=len(pairs),
            ))
        return result_list

    def run_all(
        self,
        kalshi_snapshot: DataSnapshot,
        prev_kalshi_snapshot: DataSnapshot | None,
        news_items: list[NewsItem],
    ) -> list[SentimentScore]:
        kalshi_scores = self.score_kalshi(kalshi_snapshot, prev_kalshi_snapshot)
        news_scores = self.score_news(news_items)

        by_instrument: dict[str, list[SentimentScore]] = {}
        for s in kalshi_scores + news_scores:
            by_instrument.setdefault(s.instrument, []).append(s)

        merged: list[SentimentScore] = []
        for instrument, entries in by_instrument.items():
            if len(entries) == 1:
                merged.append(entries[0])
            else:
                avg_score = sum(e.score for e in entries) / len(entries)
                total_headlines = sum(e.headline_count for e in entries)
                sources = "+".join(sorted({e.source for e in entries}))
                merged.append(SentimentScore(
                    instrument=instrument,
                    score=max(-1.0, min(1.0, avg_score)),
                    source=sources,
                    timestamp=entries[0].timestamp,
                    headline_count=total_headlines,
                ))
        return merged
