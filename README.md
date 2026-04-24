# ARGUS
> real-time market intelligence. all-seeing, never sleeps.

## Overview

Argus is an autonomous market intelligence system that monitors futures markets across equities, commodities, fixed income, currencies, and crypto. It ingests live data, detects anomalies, correlates signals across instruments, and delivers synthesized intelligence via a live web UI at [argus.monolithsystematic.com](https://argus.monolithsystematic.com).

## Architecture

```
Data Layer      →  Connectors (yfinance, FRED, Kalshi, CFTC, macro calendar, Unusual Whales)
Coordinator     →  Orchestrates polling loops, data routing, regime change and event-driven triggers
Engines         →  Signal detection, macro regime classification, event detection
Synthesis       →  Claude-powered streaming narrative generation
Store           →  SQLite persistence for synthesis history and anomaly flags
Output          →  SSE web UI + FastAPI REST endpoints
```

Five-tier pipeline:

1. **Data** — raw ingestion from market data providers and macro sources
2. **Coordinator** — async event loop managing polling schedules, regime change triggers, and price spike interrupts
3. **Engines** — statistical signal detection, macro regime classification, and event-driven trigger evaluation
4. **Synthesis** — LLM-driven interpretation streamed token-by-token to the UI
5. **Output** — live SSE web feed, query interface, and REST history endpoint

## Signal Intelligence (Phase 3)

Argus synthesizes six data streams per cycle:

| Connector | Source | Signal |
|---|---|---|
| Price Data | yfinance | Real-time OHLCV across 9 instruments |
| FRED Macro | FRED API | 20+ macro series (rates, inflation, employment) |
| COT Positioning | CFTC com-disagg | Commercial vs speculative net positioning with 4-week z-scores |
| Macro Event Calendar | FRED + hardcoded schedule | 30-day forward event window with [IMMINENT] tagging |
| Kalshi Markets | Kalshi API | Prediction market probabilities on macro outcomes |
| Options Flow | Unusual Whales API | Institutional flow alerts filtered for premium > $500k and DTE > 7 |

### Regime Classification

A voting-based `RegimeClassifier` runs after each connector cycle, scoring 8 indicators across VIX, T10Y2Y, DFF, ES, UNRATE, CPIAUCSL, CL, and 6E to classify the current macro environment:

- **Risk-On** — VIX suppressed, curve steep, equities bid
- **Risk-Off** — VIX elevated, curve flat/inverted, equities falling
- **Stagflation** — CPI hot, unemployment rising, commodities bid
- **Reflation** — CPI moderating, growth accelerating, dollar weakening

Confidence is expressed as vote share. A minimum of 3 indicator votes is required for a valid classification. On regime change, an `asyncio.Event` fires and the coordinator triggers an immediate out-of-band synthesis cycle.

### Event-Driven Triggers

An `EventDetector` runs every 60 seconds against the price snapshot. Synthesis fires immediately (outside the 15-min heartbeat) on:

- Price spike: single-candle return > ±1.5% on ES, NQ, GC, CL; > ±0.8% on ZB, ZN, 6E, 6J
- Volume anomaly: current bar > 2.5x 20-bar rolling average
- VIX spike: intraday move > 2 points
- Cross-asset divergence: ES up > 0.5% while ZB also up > 0.3%

10-minute deduplication per instrument + trigger type prevents alert storms.

### Synthesis Context Structure

Each Claude synthesis cycle receives a structured context in the following order:

```
--- TRIGGER ---          (event-driven cycles only)
--- MACRO REGIME ---
--- UPCOMING EVENTS ---
--- COT POSITIONING ---
--- OPTIONS FLOW ---
--- PRICE DATA ---
--- FRED MACRO ---
--- KALSHI MARKETS ---
```

`[IMMINENT]` tags events within 3 days. `[EXTREME]` tags COT readings where |z| > 2. `[REGIME CHANGE]` is prepended when a regime transition is detected. `[EXTREME]` tags options flow where premium > $2M.

## Quickstart

```bash
cp .env.example .env
# Fill in API keys in .env
docker-compose up
```

## Environment Variables

```bash
# Core
ANTHROPIC_API_KEY=        # Required
ARGUS_API_KEY=            # Required for production — set a long random string

# Data sources
FRED_API_KEY=             # Required
KALSHI_API_KEY=           # Required
UNUSUAL_WHALES_API_KEY=   # Optional — enables options flow (ARG-19)

# Telegram (optional)
TELEGRAM_ENABLED=false    # Set to true to re-enable Telegram alerts
TELEGRAM_BOT_TOKEN=       # Optional
TELEGRAM_CHAT_ID=         # Optional

# Storage
DB_PATH=./data/argus.db   # SQLite database path
```

## Project Structure

```
argus/
├── __main__.py          # Entry point
├── config.py            # Typed env config
├── coordinator/         # Async orchestration loop + regime and event-driven triggers
├── engines/
│   ├── anomaly.py       # Anomaly detection + options flow flagging
│   ├── regime.py        # Macro regime classifier (voting model)
│   └── event_detector.py # Price spike and cross-asset divergence detection
├── connectors/
│   ├── price.py         # yfinance real-time prices
│   ├── fred.py          # FRED macro series
│   ├── kalshi.py        # Kalshi prediction markets
│   ├── cot.py           # CFTC COT positioning data
│   ├── calendar.py      # Macro event calendar
│   └── options.py       # Unusual Whales options flow
├── synthesis/
│   ├── claude.py        # Streaming Claude API integration
│   └── packager.py      # Context assembly and section formatting
├── store/
│   └── db.py            # aiosqlite persistence (synthesis_runs, anomaly_flags)
└── router/
    ├── server.py        # FastAPI app + SSE /stream + /history endpoints
    ├── query.py         # /query endpoint with streaming Claude response
    └── auth.py          # API key verification dependency
ui/                      # Next.js frontend (argus.monolithsystematic.com)
data/                    # SQLite database (gitignored)
Dockerfile
docker-compose.yml
pyproject.toml
```
