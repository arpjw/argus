# Argus

Real-time macro intelligence engine for Monolith Systematic LLC.
Watches FRED, Kalshi, Norgate, and news feeds to produce regime
assessments and signal overlays for the Onyx Fund's TSMOM strategy.

## Architecture

Local-first deployment with WAL-backed session persistence.
Uses the same binary WAL format as the Vela Exchange engine
and the Vela MM Agent SDK.

## Current status

Deployment scaffold complete. Placeholder classifier in use.
Data source integrations: Kalshi (live), FRED (stub),
News (stub), Norgate (stub).

## Usage

```bash
# Run with default config (Kalshi only, stdout publisher)
cargo run -- run

# Check last session status
cargo run -- status

# View active signals
cargo run -- signals

# Dump WAL entries for debugging
cargo run -- wal-dump --path ~/.argus/sessions/default/argus_wal_0000.log
```

## Roadmap

- [ ] FRED data ingestion (requires FRED_API_KEY)
- [ ] News NLP features (requires NEWS_API_KEY)
- [ ] Norgate local data reader
- [ ] Local 7B classifier model (llama.cpp / ONNX)
- [ ] Monolith strategy layer publisher
- [ ] TEE deployment (AMD SEV-SNP — VEL-T1-04)
