from __future__ import annotations

from argus.connectors.types import DataSnapshot, OHLCVBar, MacroRelease, KalshiMarket, NewsItem
from argus.engines.types import AnomalyFlag, SentimentScore
from argus.engines.regime import RegimeResult
from argus.engines.event_detector import EventSignal

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _format_signal(sig: EventSignal) -> str:
    ts = sig.timestamp.strftime("%H:%M UTC")
    if sig.trigger_type == "price_spike":
        return f"TRIGGERED BY: {sig.instrument} price spike {sig.magnitude:+.1%} ({ts})"
    if sig.trigger_type == "volume_anomaly":
        return f"TRIGGERED BY: {sig.instrument} volume anomaly {sig.magnitude:.1f}x avg ({ts})"
    if sig.trigger_type == "vix_spike":
        return f"TRIGGERED BY: {sig.instrument} VIX spike {sig.magnitude:+.1f} pts ({ts})"
    if sig.trigger_type == "cross_asset_divergence":
        return f"TRIGGERED BY: {sig.instrument} cross-asset divergence {sig.magnitude:+.1%} ({ts})"
    return f"TRIGGERED BY: {sig.instrument} {sig.trigger_type} {sig.magnitude:.4f} ({ts})"


def pack_context(
    anomaly_flags: list[AnomalyFlag],
    sentiment_scores: list[SentimentScore],
    price_snapshot: DataSnapshot,
    kalshi_snapshot: DataSnapshot,
    fred_snapshot: DataSnapshot,
    news_items: list[NewsItem],
    prev_price_snapshot: DataSnapshot | None = None,
    calendar_snapshot: DataSnapshot | None = None,
    cot_snapshot: DataSnapshot | None = None,
    regime_result: RegimeResult | None = None,
    triggered_events: list[EventSignal] | None = None,
) -> str:
    sections: list[str] = []

    # --- TRIGGER ---
    if triggered_events:
        trigger_lines = ["--- TRIGGER ---"]
        for sig in triggered_events:
            trigger_lines.append(_format_signal(sig))
        sections.append("\n".join(trigger_lines))

    # --- MACRO REGIME ---
    if regime_result is not None:
        regime_lines = ["--- MACRO REGIME ---"]
        if regime_result.regime_change and regime_result.prev_regime is not None:
            regime_lines.append(
                f"[REGIME CHANGE] {regime_result.prev_regime} → {regime_result.regime}"
            )
        conf_pct = int(regime_result.confidence * 100)
        regime_lines.append(f"CURRENT: {regime_result.regime} ({conf_pct}% confidence)")
        regime_lines.append(f"SIGNALS: {', '.join(regime_result.signals)}")
        sections.append("\n".join(regime_lines))

    # --- MARKET SNAPSHOT ---
    bars: list[OHLCVBar] = price_snapshot.payload.get("bars", [])
    prev_bars: dict[str, OHLCVBar] = {}
    if prev_price_snapshot:
        for b in prev_price_snapshot.payload.get("bars", []):
            prev_bars[b["instrument"]] = b

    market_lines = ["--- MARKET SNAPSHOT ---"]
    header = f"{'INSTRUMENT':<20} {'CLOSE':>10} {'1BAR_CHG%':>10} {'SIGNAL':>6}"
    market_lines.append(header)
    market_lines.append("-" * len(header))

    for bar in bars:
        chg_str = "—"
        signal = "—"
        prev = prev_bars.get(bar["instrument"])
        if prev is not None and prev["close"] != 0:
            chg = (bar["close"] - prev["close"]) / abs(prev["close"]) * 100
            chg_str = f"{chg:+.2f}%"

        # TSMOM signal: last bar close vs previous close within the same snapshot
        # Use prev_bar if available, otherwise fall back to bar.open as a proxy
        if prev is not None:
            signal = "▲" if bar["close"] > prev["close"] else "▼"

        market_lines.append(
            f"{bar['instrument']:<20} {bar['close']:>10.4f} {chg_str:>10} {signal:>6}"
        )

    sections.append("\n".join(market_lines))

    # --- MACRO RELEASES ---
    releases: list[MacroRelease] = fred_snapshot.payload.get("releases", [])
    if releases and not fred_snapshot.payload.get("error"):
        macro_lines = ["--- MACRO RELEASES ---"]
        for r in releases:
            prev_str = f"prev: {r['previous']}" if r["previous"] is not None else "prev: —"
            macro_lines.append(f"{r['series_id']}: {r['value']} ({prev_str})")
        sections.append("\n".join(macro_lines))

    # --- KALSHI MARKETS ---
    markets: list[KalshiMarket] = kalshi_snapshot.payload.get("markets", [])
    if markets and not kalshi_snapshot.payload.get("error"):
        kalshi_lines = ["--- KALSHI MARKETS ---"]
        for m in markets:
            yes_pct = m["yes_price"] * 100
            no_pct = m["no_price"] * 100
            kalshi_lines.append(f"{m['ticker']}: YES={yes_pct:.1f}% / NO={no_pct:.1f}%")
        sections.append("\n".join(kalshi_lines))

    # --- ANOMALY FLAGS ---
    sorted_flags = sorted(
        anomaly_flags,
        key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.timestamp),
    )
    flag_lines = [f"--- ANOMALY FLAGS ({len(sorted_flags)} total) ---"]
    if sorted_flags:
        for f in sorted_flags:
            flag_lines.append(f"[{f.severity.upper()}] {f.instrument} | {f.type} | {f.description}")
    else:
        flag_lines.append("None detected this cycle.")
    anomaly_section = "\n".join(flag_lines)
    sections.append(anomaly_section)

    # --- SENTIMENT ---
    nonzero = [s for s in sentiment_scores if s.score != 0.0]
    sentiment_lines = ["--- SENTIMENT ---"]
    if nonzero:
        for s in nonzero:
            sign = "+" if s.score >= 0 else ""
            if s.headline_count:
                sentiment_lines.append(
                    f"{s.instrument}: {sign}{s.score:.2f} ({s.source}, {s.headline_count} headlines)"
                )
            else:
                sentiment_lines.append(f"{s.instrument}: {sign}{s.score:.2f} ({s.source})")
    else:
        sentiment_lines.append("No sentiment signals this cycle.")
    sentiment_section = "\n".join(sentiment_lines)
    sections.append(sentiment_section)

    # --- RECENT HEADLINES ---
    flagged_instruments = {f.instrument for f in anomaly_flags}

    def _headline_priority(item: NewsItem) -> tuple[int, object]:
        has_flag = any(inst in flagged_instruments for inst in item.instruments)
        return (0 if has_flag else 1, item.timestamp)

    sorted_news = sorted(news_items, key=_headline_priority, reverse=False)
    top_news = sorted(sorted_news[:5], key=lambda n: n.timestamp, reverse=True)

    headline_lines = ["--- RECENT HEADLINES ---"]
    if top_news:
        for n in top_news:
            ts = n.timestamp.strftime("%Y-%m-%d %H:%M")
            headline_lines.append(f"[{n.source}] {n.headline} ({ts})")
    else:
        headline_lines.append("No headlines this cycle.")
    headline_section = "\n".join(headline_lines)
    sections.append(headline_section)

    # --- UPCOMING EVENTS ---
    if calendar_snapshot is not None:
        events: list[dict] = calendar_snapshot.payload.get("events", [])
        if events:
            event_lines = ["--- UPCOMING EVENTS ---"]
            for e in events:
                instruments = e.get("related_instruments", [])
                tag = " [IMMINENT]" if e.get("days_until", 99) <= 3 else ""
                inst_str = (": " + ", ".join(instruments)) if instruments else ""
                event_lines.append(
                    f"{e['name']} ({e['days_until']} days){tag}{inst_str}"
                )
            sections.append("\n".join(event_lines))

    # --- COT POSITIONING ---
    if cot_snapshot is not None:
        positions: list[dict] = cot_snapshot.payload.get("positions", [])
        if positions:
            cot_lines = ["--- COT POSITIONING ---"]
            for p in positions:
                comm_net = p["commercial_net"]
                wk_chg = p["commercial_net_change"]
                spec_net = p["noncommercial_net"]
                z = p["noncommercial_z_score"]
                extreme_tag = " [EXTREME]" if abs(z) > 2 else ""
                cot_lines.append(
                    f"{p['instrument']}: Commercial NET {comm_net:+,} (Wk chg: {wk_chg:+,})"
                    f" | Spec NET {spec_net:+,} (z: {z:+.1f}σ){extreme_tag}"
                )
            sections.append("\n".join(cot_lines))

    output = "\n\n".join(sections)

    # Truncate to fit ~1800 token budget (approx 4 chars/token = 7200 chars)
    TOKEN_LIMIT = 1800
    CHAR_LIMIT = TOKEN_LIMIT * 4

    if len(output) // 4 > TOKEN_LIMIT:
        # Rebuild without headlines first
        sections[-1] = "--- RECENT HEADLINES ---\n(truncated to fit context limit)"
        output = "\n\n".join(sections)

    if len(output) // 4 > TOKEN_LIMIT:
        # Also truncate sentiment
        sections[-2] = "--- SENTIMENT ---\n(truncated to fit context limit)"
        output = "\n\n".join(sections)

    if len(output) > CHAR_LIMIT:
        output = output[:CHAR_LIMIT]

    return output
