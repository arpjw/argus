import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator

import anthropic

from argus.config import ANTHROPIC_API_KEY
from argus.engines.types import AnomalyFlag, SentimentScore  # noqa: F401

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Argus, a systematic macro market analyst. You watch futures markets, macro data, prediction markets, and news simultaneously. You are precise, direct, and quantitative. You do not speculate — you synthesize what the data shows.

When called, you receive a structured market snapshot. Respond with exactly two sections separated by a line containing only "---":

SECTION 1: A JSON array of anomaly flags. Each flag is an object with:
  - "instrument": ticker string
  - "type": flag type string
  - "severity": "low" | "medium" | "high"
  - "rationale": one concise sentence explaining why this is flagged

Only include flags for genuinely notable signals. If nothing is anomalous, return an empty array [].

SECTION 2: A concise prose narrative (3-5 sentences) describing current market conditions, what the data is showing, and what deserves attention. Write in present tense. No preamble, no sign-off. Start directly with the observation."""

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


@dataclass
class SynthesisResult:
    flags: list[dict]
    narrative: str
    raw: str
    timestamp: datetime


async def synthesize_stream(context: str) -> AsyncIterator[str]:
    try:
        async with client.messages.stream(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except Exception as e:
        logger.error("synthesize_stream error: %s", e)
        yield f"[synthesis error: {e}]"


async def synthesize(context: str) -> SynthesisResult:
    try:
        full_response = ""
        async for chunk in synthesize_stream(context):
            full_response += chunk

        parts = full_response.split("\n---\n", 1)
        if len(parts) == 2:
            flags_raw, narrative = parts
        else:
            flags_raw = parts[0]
            narrative = ""

        try:
            parsed_flags = json.loads(flags_raw.strip())
        except json.JSONDecodeError:
            parsed_flags = []

        return SynthesisResult(
            flags=parsed_flags,
            narrative=narrative.strip(),
            raw=full_response,
            timestamp=datetime.utcnow(),
        )
    except Exception as e:
        logger.error("synthesize error: %s", e)
        return SynthesisResult(
            flags=[],
            narrative="Synthesis unavailable.",
            raw="",
            timestamp=datetime.utcnow(),
        )


__all__ = ["SynthesisResult", "synthesize", "synthesize_stream", "SYSTEM_PROMPT"]
