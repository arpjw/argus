"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  CandlestickData,
  SeriesMarker,
  Time,
} from "lightweight-charts";
import { Flag } from "../hooks/useArgusStream";

type TimeRange = "1H" | "4H" | "1D";

const BASE_PRICES: Record<string, number> = {
  ES: 5200, NQ: 18000, RTY: 2100, YM: 39000,
  CL: 75, NG: 2.5, GC: 2300, SI: 27,
  ZB: 120, ZN: 110, ZC: 470, ZS: 1180, ZW: 590,
  "6E": 1.09, "6J": 0.0067, "6B": 1.27, "6A": 0.65,
  HG: 4.2, VX: 15, BTC: 85000,
};

function seededRng(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    return (s >>> 0) / 0xffffffff;
  };
}

function generateBars(instrument: string, count: number): CandlestickData<Time>[] {
  const base = BASE_PRICES[instrument] ?? 100;
  const seed = instrument.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  const rng = seededRng(seed);

  const volatility = base * 0.004;
  const bars: CandlestickData<Time>[] = [];
  let price = base;

  const now = Math.floor(Date.now() / 1000);
  const interval = 5 * 60;
  const startTime = now - count * interval;

  for (let i = 0; i < count; i++) {
    const open = price;
    const change = (rng() - 0.48) * volatility;
    const close = Math.max(open * 0.95, open + change);
    const high = Math.max(open, close) + rng() * volatility * 0.5;
    const low = Math.min(open, close) - rng() * volatility * 0.5;

    bars.push({
      time: (startTime + i * interval) as Time,
      open: parseFloat(open.toFixed(2)),
      high: parseFloat(high.toFixed(2)),
      low: parseFloat(low.toFixed(2)),
      close: parseFloat(close.toFixed(2)),
    });

    price = close;
  }

  return bars;
}

function getVisibleRange(bars: CandlestickData<Time>[], range: TimeRange) {
  const barsPerRange = { "1H": 12, "4H": 48, "1D": 288 };
  const count = barsPerRange[range];
  const last = bars[bars.length - 1].time as number;
  const first = bars[Math.max(0, bars.length - count)].time as number;
  return { from: first as Time, to: last as Time };
}

interface ArgusChartProps {
  instrument: string;
  flags: Flag[];
  timeRange: TimeRange;
  initialBars?: any[];
}

export default function ArgusChart({ instrument, flags, timeRange, initialBars }: ArgusChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const barsRef = useRef<CandlestickData<Time>[]>([]);
  const prevBarCountRef = useRef(0);
  const [loading, setLoading] = useState(true);

  // Initialize chart once
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "#0a0a0a" },
        textColor: "#666",
      },
      grid: {
        vertLines: { color: "#1a1a1a" },
        horzLines: { color: "#1a1a1a" },
      },
      timeScale: {
        borderColor: "#222",
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: "#222",
      },
      crosshair: {
        vertLine: { color: "#333" },
        horzLine: { color: "#333" },
      },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    const markers = createSeriesMarkers(series);

    chartRef.current = chart;
    seriesRef.current = series;
    markersRef.current = markers;

    const observer = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.resize(
          containerRef.current.clientWidth,
          containerRef.current.clientHeight
        );
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      markersRef.current = null;
    };
  }, []);

  // Load and poll price data via search endpoint; use initialBars if provided
  useEffect(() => {
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

    // Apply initialBars immediately when instrument changes
    if (initialBars && initialBars.length > 0) {
      const mapped: CandlestickData<Time>[] = (initialBars as Array<{
        timestamp: string; open: number; high: number; low: number; close: number;
      }>)
        .map((b) => ({
          time: Math.floor(new Date(b.timestamp).getTime() / 1000) as Time,
          open: b.open, high: b.high, low: b.low, close: b.close,
        }))
        .sort((a, b) => (a.time as number) - (b.time as number));
      barsRef.current = mapped;
      prevBarCountRef.current = mapped.length;
      seriesRef.current?.setData(mapped);
      chartRef.current?.timeScale().fitContent();
      setLoading(false);
    }

    const loadData = async () => {
      if (!initialBars || initialBars.length === 0) setLoading(true);
      try {
        const res = await fetch(`${apiBase}/prices/search?ticker=${encodeURIComponent(instrument)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!data.valid || !data.bars?.length) throw new Error("empty");

        const rawBars = data.bars as Array<{
          timestamp: string; open: number; high: number; low: number; close: number;
        }>;
        const mapped: CandlestickData<Time>[] = rawBars
          .map((b) => ({
            time: Math.floor(new Date(b.timestamp).getTime() / 1000) as Time,
            open: b.open, high: b.high, low: b.low, close: b.close,
          }))
          .sort((a, b) => (a.time as number) - (b.time as number));

        const prevCount = prevBarCountRef.current;
        barsRef.current = mapped;
        seriesRef.current?.setData(mapped);
        if (mapped.length !== prevCount) {
          chartRef.current?.timeScale().fitContent();
        }
        prevBarCountRef.current = mapped.length;
      } catch {
        if (barsRef.current.length === 0) {
          const bars = generateBars(instrument, 200);
          barsRef.current = bars;
          prevBarCountRef.current = bars.length;
          seriesRef.current?.setData(bars);
          const range = getVisibleRange(bars, timeRange);
          chartRef.current?.timeScale().setVisibleRange(range);
        }
      } finally {
        setLoading(false);
      }
    };

    if (!initialBars || initialBars.length === 0) loadData();
    const id = setInterval(loadData, 60_000);
    return () => clearInterval(id);
  }, [instrument]); // eslint-disable-line react-hooks/exhaustive-deps

  // Update time range
  useEffect(() => {
    if (!chartRef.current || barsRef.current.length === 0) return;
    const range = getVisibleRange(barsRef.current, timeRange);
    chartRef.current.timeScale().setVisibleRange(range);
  }, [timeRange]);

  // Update flag markers
  useEffect(() => {
    if (!markersRef.current || barsRef.current.length === 0) return;

    const lastBar = barsRef.current[barsRef.current.length - 1];
    const instrBase = instrument.replace(/=F$/, "").replace(/-USD$/, "");
    const relevantFlags = flags.filter(
      (f) => f.instrument === instrument || f.instrument === instrBase
    );

    const markers: SeriesMarker<Time>[] = relevantFlags.map((flag) => {
      const color =
        flag.severity === "high"
          ? "#ef4444"
          : flag.severity === "medium"
          ? "#f97316"
          : "#6b7280";

      return {
        time: lastBar.time,
        position: "aboveBar" as const,
        color,
        shape: "arrowDown" as const,
        text: flag.type.slice(0, 8),
        size: flag.severity === "high" ? 2 : 1,
      };
    });

    markersRef.current.setMarkers(markers);
  }, [flags, instrument]);

  return (
    <div className="relative w-full h-full">
      <div ref={containerRef} className="w-full h-full" />
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center text-zinc-500 text-sm pointer-events-none">
          Loading...
        </div>
      )}
    </div>
  );
}
