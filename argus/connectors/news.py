import asyncio
import logging
from collections import deque
from datetime import datetime

import feedparser
import httpx

from argus import config
from argus.connectors.types import NewsItem

logger = logging.getLogger(__name__)

BENZINGA_RSS = "https://www.benzinga.com/feed"
REUTERS_RSS = "https://feeds.reuters.com/reuters/businessNews"

_FEEDS = {
    "Benzinga": BENZINGA_RSS,
    "Reuters": REUTERS_RSS,
}

_DEDUP_MAX = 500


def _parse_timestamp(entry) -> datetime:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6])
        except Exception:
            pass
    return datetime.utcnow()


def _extract_instruments(headline: str) -> list[str]:
    upper = headline.upper()
    return [ticker for ticker in config.INSTRUMENTS if ticker.upper() in upper]


class NewsPoller:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._queue: asyncio.Queue[NewsItem] = asyncio.Queue()

    def _record_url(self, url: str) -> bool:
        """Return True if url is new; False if already seen."""
        if url in self._seen:
            return False
        if len(self._seen) >= _DEDUP_MAX:
            oldest = self._seen_order.popleft()
            self._seen.discard(oldest)
        self._seen.add(url)
        self._seen_order.append(url)
        return True

    async def _fetch_feed(self, client: httpx.AsyncClient, source: str, url: str) -> None:
        try:
            response = await client.get(url, timeout=15)
            response.raise_for_status()
            feed = feedparser.parse(response.text)
            for entry in feed.entries:
                link = getattr(entry, "link", None)
                if not link:
                    continue
                if not self._record_url(link):
                    continue
                item = NewsItem(
                    headline=getattr(entry, "title", ""),
                    source=source,
                    url=link,
                    timestamp=_parse_timestamp(entry),
                    instruments=_extract_instruments(getattr(entry, "title", "")),
                )
                await self._queue.put(item)
        except Exception as exc:
            logger.warning("Failed to fetch %s feed (%s): %s", source, url, exc)

    async def poll_forever(self, interval_seconds: int = config.NEWS_POLL_INTERVAL) -> None:
        async with httpx.AsyncClient() as client:
            while True:
                tasks = [
                    self._fetch_feed(client, source, url)
                    for source, url in _FEEDS.items()
                ]
                await asyncio.gather(*tasks)
                await asyncio.sleep(interval_seconds)

    async def stream_news(self):
        while True:
            item = await self._queue.get()
            yield item


poller = NewsPoller()
