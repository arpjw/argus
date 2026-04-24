# ARGUS
> real-time market intelligence. all-seeing, never sleeps.

## Overview

Argus is an autonomous market intelligence system that monitors futures markets across equities, commodities, fixed income, currencies, and crypto. It ingests live data, detects anomalies, correlates signals across instruments, and delivers synthesized alerts via Telegram.

## Architecture
Data Layer      →  Connectors (yfinance, FRED, Kalshi, CFTC, macro calendar)
Coordinator     →  Orchestrates polling loops, data routing, regime change events
Engines         →  Signal detection (z-score, correlation, regime classification)
Synthesis       →  Claude-powered narrative generation
Output          →  Telegram alerts + FastAPI status endpoint

Five-tier pipeline:

1. **Data** — raw ingestion from market data providers and macro sources
2. **Coordinator** — async event loop managing polling schedules and regime change triggers
3. **Engines** — statistical signal detection and macro regime classification
4. **Synthesis** — LLM-driven interpretation and alert composition
5. **Output** — Telegram delivery and REST health endpoint

## Signal Intelligence (Phase 3)

Argus synthesizes five data streams per cycle:

| Connector | Source | Signal |
|---|---|---|
| Price Data | yfinance | Real-time OHLCV across 9 instruments |
| FRED Macro | FRED API | 20+ macro series (rates, inflation, employment) |
| COT Positioning | CFTC com-disagg | Commercial vs speculative net positioning with 4-week z-scores |
| Macro Event Calendar | FRED + hardcoded schedule | 30-day forward event window with [IMMINENT] tagging |
| Kalshi Markets | Kalshi API | Prediction market probabilities on macro outcomes |

### Regime Classification

A voting-based `RegimeClassifier` runs after each connector cycle, scoring 8 indicators across VIX, T10Y2Y, DFF, ES, UNRATE, CPIAUCSL, CL, and 6E to classify the current macro environment:

- **Risk-On** — VIX suppressed, curve steep, equities bid
- **Risk-Off** — VIX elevated, curve flat/inverted, equities falling
- **Stagflation** — CPI hot, unemployment rising, commodities bid
- **Reflation** — CPI moderating, growth accelerating, dollar weakening

Confidence is expressed as vote share. A minimum of 3 indicator votes is required for a valid classification. On regime change, an `asyncio.Event` fires and the coordinator triggers an immediate out-of-band synthesis cycle outside the normal 15-minute heartbeat.

### Synthesis Context Structure

Each Claude synthesis cycle receives a structured context in the following order:
--- MACRO REGIME ---
CURRENT: Risk-Off (71% confidence)
SIGNALS: VIX > 25, T10Y2Y inverting, ES 5d return -2.1%
--- UPCOMING EVENTS ---
CPI (2 days) [IMMINENT]: ZB, ZN, 6E, 6J, GC
NFP (9 days): ES, NQ, RTY
--- COT POSITIONING ---
ES: Commercial NET +12400 (Wk chg: +3200) | Spec NET -89000 (z: -2.3σ) [EXTREME]
GC: Commercial NET +8100 (Wk chg: -400) | Spec NET +44000 (z: +0.7σ)
--- PRICE DATA ---
--- FRED MACRO ---
--- KALSHI MARKETS ---

`[IMMINENT]` tags events within 3 days. `[EXTREME]` tags COT readings where |z| > 2. `[REGIME CHANGE]` is prepended to the macro regime section when a transition is detected.

## Quickstart

```bash
cp .env.example .env
# Fill in API keys in .env
docker-compose up
```

## Environment Variables
FRED_API_KEY=
KALSHI_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ANTHROPIC_API_KEY=

## Project Structure
argus/
├── main.py          # Entry point
├── config.py            # Typed env config
├── coordinator/         # Async orchestration loop + regime change listener
├── engines/
│   └── regime.py        # Macro regime classifier (voting model)
├── connectors/
│   ├── price.py         # yfinance real-time prices
│   ├── fred.py          # FRED macro series
│   ├── kalshi.py        # Kalshi prediction markets
│   ├── cot.py           # CFTC COT positioning data
│   └── calendar.py      # Macro event calendar
├── synthesis/           # LLM synthesis layer
└── router/              # Output routing (Telegram, API)
ui/                      # Frontend (future)
Dockerfile
docker-compose.yml
pyproject.toml
