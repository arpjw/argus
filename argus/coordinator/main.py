import asyncio
import logging

from argus.connectors.norgate import fetch_snapshot as fetch_norgate
from argus.connectors.fred import fetch_snapshot as fetch_fred
from argus.connectors.kalshi import fetch_snapshot as fetch_kalshi
from argus.connectors.news import poller as news_poller
from argus.engines.anomaly import AnomalyEngine
from argus.engines.sentiment import SentimentScorer
from argus.synthesis.packager import pack_context
from argus.synthesis.claude import synthesize, SynthesisResult
from argus import config

logger = logging.getLogger("argus.coordinator")

broadcast_queue: asyncio.Queue[SynthesisResult] = asyncio.Queue(maxsize=100)

anomaly_engine = AnomalyEngine()
sentiment_scorer = SentimentScorer()

prev_price_snapshot = None
prev_kalshi_snapshot = None
latest_kalshi_snapshot = None


async def run_cycle(news_items: list) -> SynthesisResult | None:
    global prev_price_snapshot, prev_kalshi_snapshot, latest_kalshi_snapshot

    price, fred, kalshi = await asyncio.gather(
        fetch_norgate(),
        fetch_fred(),
        fetch_kalshi(),
        return_exceptions=True,
    )

    if isinstance(price, Exception):
        logger.warning("fetch_norgate failed: %s", price)
        price = None
    if isinstance(fred, Exception):
        logger.warning("fetch_fred failed: %s", fred)
        fred = None
    if isinstance(kalshi, Exception):
        logger.warning("fetch_kalshi failed: %s", kalshi)
        kalshi = None

    if price is None or fred is None or kalshi is None:
        return None

    anomaly_flags, sentiment_scores = await asyncio.gather(
        anomaly_engine.run_all(price, prev_price_snapshot, kalshi),
        asyncio.to_thread(
            sentiment_scorer.run_all, kalshi, prev_kalshi_snapshot, news_items
        ),
    )

    context = pack_context(
        anomaly_flags=anomaly_flags,
        sentiment_scores=sentiment_scores,
        price_snapshot=price,
        kalshi_snapshot=kalshi,
        fred_snapshot=fred,
        news_items=news_items,
        prev_price_snapshot=prev_price_snapshot,
    )

    result = await synthesize(context)

    try:
        broadcast_queue.put_nowait(result)
    except asyncio.QueueFull:
        logger.warning("broadcast_queue full — dropping synthesis result")

    prev_price_snapshot = price
    prev_kalshi_snapshot = kalshi
    latest_kalshi_snapshot = kalshi

    logger.info(
        "Argus cycle complete — %d flags, narrative length %d",
        len(result.flags),
        len(result.narrative),
    )
    return result


async def heartbeat_loop() -> None:
    while True:
        await asyncio.sleep(config.HEARTBEAT_INTERVAL)
        logger.info("Heartbeat triggered")
        try:
            await run_cycle([])
        except Exception as exc:
            logger.exception("heartbeat_loop error: %s", exc)


async def event_loop() -> None:
    asyncio.create_task(news_poller.poll_forever(config.NEWS_POLL_INTERVAL))

    buffer: list = []
    flush_handle: asyncio.TimerHandle | None = None

    def _schedule_flush(loop: asyncio.AbstractEventLoop) -> None:
        nonlocal flush_handle
        if flush_handle is None:
            flush_handle = loop.call_later(30, lambda: asyncio.ensure_future(_flush()))

    async def _flush() -> None:
        nonlocal buffer, flush_handle
        flush_handle = None
        if not buffer:
            return
        items = list(buffer)
        buffer.clear()
        logger.info("Event triggered by %d news items", len(items))
        try:
            await run_cycle(items)
        except Exception as exc:
            logger.exception("event_loop run_cycle error: %s", exc)

    loop = asyncio.get_event_loop()
    async for item in news_poller.stream_news():
        try:
            buffer.append(item)
            _schedule_flush(loop)
        except Exception as exc:
            logger.exception("event_loop error: %s", exc)


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    logger.info("Argus initializing...")
    logger.info("Instruments: %s", config.INSTRUMENTS)
    logger.info("Heartbeat interval: %ss", config.HEARTBEAT_INTERVAL)

    await run_cycle([])

    await asyncio.gather(
        heartbeat_loop(),
        event_loop(),
    )
