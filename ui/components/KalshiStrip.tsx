"use client";

import { useEffect, useRef, useState } from "react";

type KalshiMarket = {
  ticker: string;
  title: string;
  yes_price: number;
};

type MarketHistory = Map<string, number[]>;

// Maps instrument prefixes to Kalshi ticker keyword fragments to highlight
const KALSHI_INSTRUMENT_MAP: Record<string, string[]> = {
  ZB: ["FED", "INFL", "RECESSION"],
  ZN: ["FED", "INFL", "RECESSION"],
  ZF: ["FED", "INFL"],
  ZT: ["FED"],
  GC: ["INFL", "CPI"],
  CL: ["INFL", "RECESSION"],
  ES: ["RECESSION"],
  NQ: ["RECESSION"],
};

function getHighlightKeys(instrument: string): string[] {
  const prefix = instrument.replace(/[0-9]/g, "").toUpperCase().slice(0, 3);
  return KALSHI_INSTRUMENT_MAP[prefix] ?? [];
}

function isHighlighted(ticker: string, keys: string[]): boolean {
  if (keys.length === 0) return false;
  const t = ticker.toUpperCase();
  return keys.some((k) => t.includes(k));
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <span style={{ width: 40, display: "inline-block" }} />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 0.01;
  const w = 40;
  const h = 20;
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline points={pts} fill="none" stroke="#444" strokeWidth={1.5} />
    </svg>
  );
}

function trendArrow(values: number[]): string {
  if (values.length < 2) return "—";
  const delta = values[values.length - 1] - values[values.length - 2];
  if (delta > 0.005) return "▲";
  if (delta < -0.005) return "▼";
  return "—";
}

function arrowColor(arrow: string): string {
  if (arrow === "▲") return "#4ade80";
  if (arrow === "▼") return "#f87171";
  return "#555";
}

export default function KalshiStrip({ selectedInstrument }: { selectedInstrument: string }) {
  const [markets, setMarkets] = useState<KalshiMarket[]>([]);
  const [empty, setEmpty] = useState(false);
  const historyRef = useRef<MarketHistory>(new Map());

  async function fetchKalshi() {
    try {
      const res = await fetch("http://localhost:8000/kalshi");
      if (!res.ok) return;
      const data = await res.json();
      const list: KalshiMarket[] = data.markets ?? [];
      // update history
      list.forEach((m) => {
        const hist = historyRef.current.get(m.ticker) ?? [];
        hist.push(m.yes_price);
        if (hist.length > 10) hist.shift();
        historyRef.current.set(m.ticker, hist);
      });
      setMarkets(list);
      setEmpty(list.length === 0);
    } catch {
      setEmpty(true);
    }
  }

  useEffect(() => {
    fetchKalshi();
    const interval = setInterval(fetchKalshi, 30_000);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchKalshi();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedInstrument]);

  const highlightKeys = getHighlightKeys(selectedInstrument);

  return (
    <div
      style={{
        height: 120,
        background: "#0f0f0f",
        borderTop: "1px solid #1a1a1a",
        display: "flex",
        alignItems: "center",
        overflowX: "auto",
        padding: "0 16px",
        gap: 12,
        flexShrink: 0,
      }}
    >
      {empty || markets.length === 0 ? (
        <span style={{ color: "#333", fontSize: 12, margin: "0 auto" }}>No Kalshi data</span>
      ) : (
        markets.map((m) => {
          const hist = historyRef.current.get(m.ticker) ?? [m.yes_price];
          const arrow = trendArrow(hist);
          const highlighted = isHighlighted(m.ticker, highlightKeys);
          return (
            <div
              key={m.ticker}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                padding: "10px 14px",
                borderRadius: 6,
                border: highlighted ? "1px solid #3a3a2a" : "1px solid #1a1a1a",
                background: highlighted ? "#1a1a0f" : "#111",
                minWidth: 110,
                flexShrink: 0,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span
                  style={{
                    fontFamily: "monospace",
                    fontSize: 11,
                    color: highlighted ? "#d4c97a" : "#555",
                    fontWeight: 700,
                    letterSpacing: "0.05em",
                  }}
                >
                  {m.ticker}
                </span>
                <span style={{ fontSize: 11, color: arrowColor(arrow) }}>{arrow}</span>
              </div>
              <span
                style={{
                  fontFamily: "monospace",
                  fontSize: 22,
                  fontWeight: 700,
                  color: highlighted ? "#e8e0a0" : "#ccc",
                  lineHeight: 1,
                }}
              >
                {Math.round(m.yes_price * 100)}%
              </span>
              <Sparkline values={hist} />
            </div>
          );
        })
      )}
    </div>
  );
}
