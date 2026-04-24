import asyncio
import logging

from argus.connectors.prices import fetch_snapshot as fetch_prices
from argus.connectors.prices import price_buffer
from argus.connectors.fred import fetch_snapshot as fetch_fred
from argus.connectors.kalshi import fetch_snapshot as fetch_kalshi
from argus.connectors.calendar import fetch_snapshot as fetch_calendar
from argus.connectors.cot import fetch_snapshot as fetch_cot
from argus.connectors.options import fetch_snapshot as fetch_options
from argus.connectors.news import poller as news_poller
from argus.engines.anomaly import AnomalyEngine
from argus.engines.sentiment import SentimentScorer
from argus.engines.regime import RegimeClassifier, regime_change_event
from argus.engines.event_detector import EventDetector, EventSignal
from argus.synthesis.packager import pack_context
from argus.synthesis.claude import synthesize, SynthesisResult
from argus import config
from argus.store import db

logger = logging.getLogger("argus.coordinator")

broadcast_queue: asyncio.Queue[SynthesisResult] = asyncio.Queue(maxsize=100)

anomaly_engine = AnomalyEngine()
sentiment_scorer = SentimentScorer()
regime_classifier = RegimeClassifier()
event_detector = EventDetector()

prev_price_snapshot = None
prev_kalshi_snapshot = None
latest_kalshi_snapshot = None
latest_price_buffer = price_buffer  # reference — updated in-place by fetch_prices
latest_context: str = ""


async def run_cycle(
    news_items: list,
    triggered_events: list[EventSignal] | None = None,
) -> SynthesisResult | None:
    global prev_price_snapshot, prev_kalshi_snapshot, latest_kalshi_snapshot, latest_context

    price, fred, kalshi, calendar, cot, options = await asyncio.gather(
        fetch_prices(),
        fetch_fred(),
        fetch_kalshi(),
        fetch_calendar(),
        fetch_cot(),
        fetch_options(),
        return_exceptions=True,
    )

    if isinstance(price, Exception):
        logger.warning("fetch_prices failed: %s", price)
        price = None
    if isinstance(fred, Exception):
        logger.warning("fetch_fred failed: %s", fred)
        fred = None
    if isinstance(kalshi, Exception):
        logger.warning("fetch_kalshi failed: %s", kalshi)
        kalshi = None
    if isinstance(calendar, Exception):
        logger.warning("fetch_calendar failed: %s", calendar)
        calendar = None
    if isinstance(cot, Exception):
        logger.warning("fetch_cot failed: %s", cot)
        cot = None
    if isinstance(options, Exception):
        logger.warning("fetch_options failed: %s", options)
        options = None

    if price is None or fred is None or kalshi is None:
        return None

    anomaly_flags, sentiment_scores = await asyncio.gather(
        anomaly_engine.run_all(price, prev_price_snapshot, kalshi),
        asyncio.to_thread(
            sentiment_scorer.run_all, kalshi, prev_kalshi_snapshot, news_items
        ),
    )

    try:
        options_flags = await anomaly_engine.check_options_flow(options)
        anomaly_flags = list(anomaly_flags) + options_flags
    except Exception as exc:
        logger.warning("check_options_flow failed: %s", exc)

    regime_result = regime_classifier.classify(fred, price)

    context = pack_context(
        anomaly_flags=anomaly_flags,
        sentiment_scores=sentiment_scores,
        price_snapshot=price,
        kalshi_snapshot=kalshi,
        fred_snapshot=fred,
        news_items=news_items,
        prev_price_snapshot=prev_price_snapshot,
        calendar_snapshot=calendar,
        cot_snapshot=cot,
        options_snapshot=options,
        regime_result=regime_result,
        triggered_events=triggered_events,
    )
    latest_context = context

    result = await synthesize(context)

    try:
        broadcast_queue.put_nowait(result)
    except asyncio.QueueFull:
        logger.warning("broadcast_queue full — dropping synthesis result")

    try:
        run_id = await db.save_run(
            timestamp=result.timestamp.isoformat(),
            regime=regime_result.regime if regime_result else None,
            confidence=regime_result.confidence if regime_result else None,
            narrative=result.narrative,
            flag_count=len(anomaly_flags),
            trigger_type=triggered_events[0].trigger_type if triggered_events else None,
        )
        await db.save_flags(run_id, anomaly_flags)
    except Exception as e:
        logger.warning("Persistence write failed (non-fatal): %s", e)

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


async def price_check_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            price = await fetch_prices()
            signals = event_detector.check(price)
            if signals:
                logger.info(
                    "Event detector fired %d signal(s) — triggering immediate synthesis",
                    len(signals),
                )
                await run_cycle([], triggered_events=signals)
        except Exception as exc:
            logger.exception("price_check_loop error: %s", exc)


async def regime_change_loop() -> None:
    while True:
        await regime_change_event.wait()
        logger.info("Regime change detected — triggering immediate synthesis cycle")
        try:
            await run_cycle([])
        except Exception as exc:
            logger.exception("regime_change_loop run_cycle error: %s", exc)


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
    if not config.TELEGRAM_ENABLED:
        logger.info("Telegram disabled, output routed to web only")

    await db.init_db()
    last_run = await db.get_recent_runs(limit=1)
    if last_run:
        logger.info("Argus resuming — last synthesis at %s", last_run[0]["timestamp"])
    else:
        logger.info("Argus starting fresh — no prior synthesis history found")

    await run_cycle([])

    await asyncio.gather(
        heartbeat_loop(),
        event_loop(),
        regime_change_loop(),
        price_check_loop(),
    )
