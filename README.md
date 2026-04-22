# ARGUS

> real-time market intelligence. all-seeing, never sleeps.

## Overview

Argus is an autonomous market intelligence system that monitors futures markets across equities, commodities, fixed income, currencies, and crypto. It ingests live data, detects anomalies, correlates signals across instruments, and delivers synthesized alerts via Telegram.

## Architecture

```
Data Layer      →  Connectors (Norgate, FRED, Kalshi, News feeds)
Coordinator     →  Orchestrates polling loops and data routing
Engines         →  Signal detection (z-score, correlation, regime)
Synthesis       →  Claude-powered narrative generation
Output          →  Telegram alerts + FastAPI status endpoint
```

Five-tier pipeline:

1. **Data** — raw ingestion from market data providers and news APIs
2. **Coordinator** — async event loop managing polling schedules
3. **Engines** — statistical signal detection across 20 instruments
4. **Synthesis** — LLM-driven interpretation and alert composition
5. **Output** — Telegram delivery and REST health endpoint

## Quickstart

```bash
cp .env.example .env
# Fill in API keys in .env
docker-compose up
```

## Project Structure

```
argus/
├── __main__.py          # Entry point
├── config.py            # Typed env config
├── coordinator/         # Async orchestration loop
├── engines/             # Signal detection logic
├── connectors/          # Data source adapters
├── synthesis/           # LLM synthesis layer
└── router/              # Output routing (Telegram, API)
ui/                      # Frontend (future)
Dockerfile
docker-compose.yml
pyproject.toml
```
