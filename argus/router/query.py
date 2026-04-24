import json
import logging
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse

import anthropic
import argus.coordinator.main as coordinator_module
from argus.config import ANTHROPIC_API_KEY
from argus.router.auth import verify_api_key

logger = logging.getLogger("argus.router.query")

router = APIRouter()

_anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

QUERY_SYSTEM = (
    "You are Argus, a real-time macro market intelligence system. "
    "Answer concisely and precisely based only on the context provided."
)

_last_query_time: float = 0.0
RATE_LIMIT_SECONDS = 10


@router.get("/query")
async def query_endpoint(question: str = Query(...), _: None = Depends(verify_api_key)):
    global _last_query_time
    now = time.time()

    since_last = now - _last_query_time
    if since_last < RATE_LIMIT_SECONDS:
        retry_after = int(RATE_LIMIT_SECONDS - since_last) + 1
        return Response(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    _last_query_time = now
    context = coordinator_module.latest_context

    async def token_stream():
        if not context:
            yield f"data: {json.dumps({'type': 'token', 'text': 'Argus is still warming up — no snapshot available yet.'})}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        user_message = f"{context}\n\nQuestion: {question}"
        try:
            async with _anthropic_client.messages.stream(
                model="claude-sonnet-4-5",
                max_tokens=512,
                system=QUERY_SYSTEM,
                messages=[{"role": "user", "content": user_message}],
            ) as stream_ctx:
                async for text in stream_ctx.text_stream:
                    yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"
            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            logger.error("query stream error: %s", e)
            yield f"data: {json.dumps({'type': 'token', 'text': f'Error: {e}'})}\n\n"
            yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        token_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
