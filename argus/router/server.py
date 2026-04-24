import asyncio
import json
import logging
import time
from datetime import datetime

import anthropic
import pandas as pd
import yfinance as yf
from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from argus.config import ANTHROPIC_API_KEY
from argus.router.auth import verify_api_key
from argus.store import db
from argus.connectors import fred as fred_connector
from argus.connectors import kalshi as kalshi_connector
from argus.connectors.prices import price_buffer
import argus.coordinator.main as coordinator_module
from argus.coordinator.main import broadcast_queue, run as coordinator_run
from argus.router.query import router as query_router
from argus.synthesis.claude import SynthesisResult, synthesis_queue

logger = logging.getLogger("argus.router")

app = FastAPI(title="Argus")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query_router)

latest_synthesis: SynthesisResult | None = None

_search_cache: dict[str, tuple[float, dict]] = {}

_anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

ANALYZE_SYSTEM_PROMPT = (
    "You are Argus, a systematic macro market analyst. You are given the current live market context "
    "and a piece of text submitted by the user — an article, transcript, research note, or any raw text. "
    "Your job is to analyze the submitted text through the lens of current market conditions. "
    "Identify: (1) what this text signals for the instruments and macro factors currently in focus, "
    "(2) whether it confirms, contradicts, or adds nuance to the current market narrative, "
    "(3) any specific risks or opportunities implied. "
    "Be direct and quantitative where possible. Reference actual data points from the market context."
)


class AnalyzeRequest(BaseModel):
    text: str
    label: str = "Document"


@app.get("/history")
async def get_history(limit: int = 20, _: None = Depends(verify_api_key)):
    try:
        return await db.get_recent_runs(limit=limit)
    except Exception:
        return []


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/prices/search")
async def search_prices(ticker: str):
    ticker = ticker.upper()
    now = time.time()
    if ticker in _search_cache:
        ts, cached = _search_cache[ticker]
        if now - ts < 60:
            return cached

    try:
        def _get_fast_info():
            return yf.Ticker(ticker).fast_info

        df, fast_info = await asyncio.gather(
            asyncio.to_thread(
                yf.download, ticker, period="5d", interval="5m",
                progress=False, auto_adjust=True
            ),
            asyncio.to_thread(_get_fast_info),
        )

        if df is None or df.empty:
            result = {"valid": False, "ticker": ticker}
            _search_cache[ticker] = (time.time(), result)
            return result

        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)

        for col in ("Open", "High", "Low", "Close", "Volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Close"])

        if df.empty:
            result = {"valid": False, "ticker": ticker}
            _search_cache[ticker] = (time.time(), result)
            return result

        bars = []
        for ts_val, row in df.iterrows():
            bars.append({
                "timestamp": ts_val.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume", 0) or 0),
            })

        name = getattr(fast_info, "long_name", None) or ticker
        exchange = getattr(fast_info, "exchange", "") or ""

        result = {
            "valid": True,
            "ticker": ticker,
            "name": name,
            "exchange": exchange,
            "bars": bars,
        }
        _search_cache[ticker] = (time.time(), result)
        return result

    except Exception as exc:
        logger.warning("search_prices failed for %s: %s", ticker, exc)
        result = {"valid": False, "ticker": ticker}
        _search_cache[ticker] = (time.time(), result)
        return result


@app.get("/prices/{instrument}")
async def prices(instrument: str):
    bars = price_buffer.get(instrument)
    if bars is None:
        return JSONResponse({"error": "No data"}, status_code=404)
    return {"instrument": instrument, "bars": bars}


@app.get("/kalshi")
async def kalshi():
    snap = coordinator_module.latest_kalshi_snapshot
    if snap is None:
        return {"markets": []}
    return snap.payload


@app.get("/stream")
async def stream(_: None = Depends(verify_api_key)):
    async def event_generator():
        global latest_synthesis
        try:
            while True:
                try:
                    item = await asyncio.wait_for(synthesis_queue.get(), timeout=15)
                    if isinstance(item, str):
                        yield f"data: {json.dumps({'type': 'token', 'text': item})}\n\n"
                    elif isinstance(item, SynthesisResult):
                        latest_synthesis = item
                        payload = json.dumps({
                            "type": "synthesis",
                            "timestamp": item.timestamp.isoformat(),
                            "flags": item.flags,
                            "narrative": item.narrative,
                        })
                        yield f"event: done\ndata: {payload}\n\n"
                    else:
                        # None sentinel — synthesis error
                        yield "event: done\ndata: \n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            logger.info("SSE client disconnected")
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    synthesis = latest_synthesis

    if synthesis is not None:
        flags_text = "\n".join(
            f"- [{f.get('severity', '').upper()}] {f.get('instrument', '')}: {f.get('rationale', '')}"
            for f in synthesis.flags
        )
        market_context = (
            f"NARRATIVE:\n{synthesis.narrative}\n\n"
            f"FLAGS:\n{flags_text or '(none)'}"
        )
    else:
        fred_snap = await fred_connector.fetch_snapshot()
        kalshi_snap = await kalshi_connector.fetch_snapshot()
        fred_releases = fred_snap.payload.get("releases", [])
        kalshi_markets = kalshi_snap.payload.get("markets", [])
        fred_text = "\n".join(
            f"- {r['name']} ({r['series_id']}): {r['value']}"
            for r in fred_releases
        ) or "(unavailable)"
        kalshi_text = "\n".join(
            f"- {m['ticker']}: YES {m['yes_price']:.0%}"
            for m in kalshi_markets
        ) or "(unavailable)"
        market_context = f"MACRO DATA:\n{fred_text}\n\nPREDICTION MARKETS:\n{kalshi_text}"

    user_message = (
        f"CURRENT MARKET CONTEXT:\n{market_context}\n\n"
        f"---\n\n"
        f"DOCUMENT ({req.label}):\n{req.text}"
    )

    async def token_stream():
        try:
            async with _anthropic_client.messages.stream(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                system=ANALYZE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            ) as stream_ctx:
                async for text in stream_ctx.text_stream:
                    yield f"data: {json.dumps({'token': text})}\n\n"
            yield 'data: {"done": true}\n\n'
        except Exception as e:
            logger.error("analyze stream error: %s", e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield 'data: {"done": true}\n\n'

    return StreamingResponse(
        token_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _drain_broadcast_queue():
    while True:
        await broadcast_queue.get()


@app.on_event("startup")
async def startup():
    asyncio.create_task(coordinator_run())
    asyncio.create_task(_drain_broadcast_queue())
