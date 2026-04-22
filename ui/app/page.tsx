"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useArgusStream, type Flag, type FlagEntry } from "../hooks/useArgusStream";
import { useAnalysis } from "../hooks/useAnalysis";
import KalshiStrip from "../components/KalshiStrip";

const ArgusChart = dynamic(() => import("../components/ArgusChart"), { ssr: false });

const INSTRUMENTS = [
  "ES", "NQ", "RTY", "YM",
  "CL", "NG", "GC", "SI",
  "ZB", "ZN", "ZC", "ZS", "ZW",
  "6E", "6J", "6B", "6A",
  "HG", "VX", "BTC",
] as const;

type TimeRange = "1H" | "4H" | "1D";

const SEVERITY_DOT: Record<FlagEntry["severity"], string> = {
  high: "#ef4444",
  medium: "#f59e0b",
  low: "#4b4b4b",
};

const STATUS_DOT: Record<string, string> = {
  live: "bg-green-500",
  connecting: "bg-yellow-500",
  error: "bg-red-500",
};

function formatTs(d: Date | null): string {
  if (!d) return "—";
  return d.toLocaleTimeString("en-US", { hour12: false });
}

type AnalysisEntry = {
  label: string;
  timestamp: Date;
  text: string;
};

function highestSeverityInstrument(flags: Flag[]): string | null {
  const order = { high: 3, medium: 2, low: 1 };
  if (flags.length === 0) return null;
  return flags.reduce((best, f) =>
    order[f.severity] > order[best.severity] ? f : best
  ).instrument;
}

export default function Home() {
  const { flags, allFlags, entries, lastUpdated, status } = useArgusStream();
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = feedRef.current;
    if (!el || entries.length === 0) return;
    if (el.scrollTop <= 50) {
      el.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [entries.length]);
  const { analyze, response, isStreaming, error } = useAnalysis();

  const [activeTab, setActiveTab] = useState<"FLAGS" | "ANALYZE">("FLAGS");
  const [label, setLabel] = useState("");
  const [inputText, setInputText] = useState("");
  const [history, setHistory] = useState<AnalysisEntry[]>([]);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const [selectedInstrument, setSelectedInstrument] = useState<string>("ES");
  const [timeRange, setTimeRange] = useState<TimeRange>("1D");
  const manualSelectionRef = useRef(false);

  // Auto-select instrument with highest severity flag, unless user manually chose one
  useEffect(() => {
    if (manualSelectionRef.current) return;
    const top = highestSeverityInstrument(flags);
    if (top && INSTRUMENTS.includes(top as (typeof INSTRUMENTS)[number])) {
      setSelectedInstrument(top);
    }
  }, [flags]);

  async function handleAnalyze() {
    if (!inputText.trim() || isStreaming) return;
    const currentLabel = label.trim() || "Document";
    const fullResponse = await analyze(inputText.trim(), currentLabel);
    if (fullResponse) {
      setHistory((prev) =>
        [{ label: currentLabel, timestamp: new Date(), text: fullResponse }, ...prev].slice(0, 5)
      );
    }
  }

  return (
    <div className="flex flex-col h-screen" style={{ color: "#e5e5e5" }}>
      {/* Top bar */}
      <header
        className="flex items-center gap-4 px-6 py-3 border-b"
        style={{ borderColor: "#1f1f1f", background: "#0f0f0f" }}
      >
        <span className="text-lg font-semibold tracking-widest">ARGUS</span>
        <span className="flex items-center gap-2 text-sm" style={{ color: "#888" }}>
          <span className={`inline-block w-2 h-2 rounded-full ${STATUS_DOT[status]}`} />
          {status}
        </span>
        <span className="ml-auto text-xs" style={{ color: "#555" }}>
          last update: {formatTs(lastUpdated)}
        </span>
      </header>

      {/* Three-panel body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left — narrative feed */}
        <aside
          className="w-1/4 flex flex-col border-r overflow-hidden"
          style={{ borderColor: "#1f1f1f", background: "#0d0d0d" }}
        >
          {/* Sticky header */}
          <div
            className="flex items-center justify-between px-4 py-2 border-b shrink-0"
            style={{ borderColor: "#1f1f1f" }}
          >
            <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "#555" }}>
              Narrative
            </span>
            {entries.length > 0 && (
              <span
                className="text-xs font-mono px-1.5 py-0.5 rounded"
                style={{ background: "#1a1a1a", color: "#555" }}
              >
                {entries.length} cycles
              </span>
            )}
          </div>

          {/* Scrollable feed */}
          <div ref={feedRef} className="flex-1 overflow-y-auto">
            {entries.length === 0 ? (
              <div className="flex items-center justify-center gap-2 h-full" style={{ color: "#555" }}>
                <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse shrink-0" />
                <span className="text-xs font-mono">Watching markets...</span>
              </div>
            ) : (
              entries.map((entry, i) => (
                <div
                  key={entry.id}
                  className="feed-entry px-4 py-3"
                  style={{ borderBottom: i < entries.length - 1 ? "1px solid #1a1a1a" : "none" }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      {entry.highCount > 0 && (
                        <span className="font-mono" style={{ color: "#999", fontSize: "12px" }}>
                          🔴 {entry.highCount}
                        </span>
                      )}
                      {entry.mediumCount > 0 && (
                        <span className="font-mono" style={{ color: "#999", fontSize: "12px" }}>
                          🟡 {entry.mediumCount}
                        </span>
                      )}
                      {entry.lowCount > 0 && (
                        <span className="font-mono" style={{ color: "#999", fontSize: "12px" }}>
                          ⚪ {entry.lowCount}
                        </span>
                      )}
                      {entry.flagCount === 0 && (
                        <span className="font-mono" style={{ color: "#444", fontSize: "12px" }}>
                          no flags
                        </span>
                      )}
                    </div>
                    <span className="font-mono shrink-0 ml-2" style={{ color: "#555", fontSize: "11px" }}>
                      {entry.timestamp.toLocaleTimeString("en-US", { hour12: false })}
                    </span>
                  </div>
                  <p className="font-mono leading-relaxed" style={{ color: "#ccc", fontSize: "13px" }}>
                    {entry.narrative}
                  </p>
                </div>
              ))
            )}
          </div>
        </aside>

        {/* Center — chart */}
        <main
          className="w-1/2 flex flex-col overflow-hidden"
          style={{ background: "#0a0a0a" }}
        >
          {/* Panel header: instrument + time range */}
          <div
            className="flex items-center justify-between px-4 py-2 border-b shrink-0"
            style={{ borderColor: "#1f1f1f" }}
          >
            <span className="text-sm font-semibold tracking-widest" style={{ color: "#e5e5e5" }}>
              {selectedInstrument}
            </span>
            <div className="flex items-center gap-1">
              {(["1H", "4H", "1D"] as TimeRange[]).map((r) => (
                <button
                  key={r}
                  onClick={() => setTimeRange(r)}
                  className="px-2 py-0.5 text-xs rounded font-mono"
                  style={{
                    background: timeRange === r ? "#2a2a2a" : "transparent",
                    color: timeRange === r ? "#e5e5e5" : "#555",
                    border: timeRange === r ? "1px solid #333" : "1px solid transparent",
                  }}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>

          {/* Instrument chips */}
          <div
            className="flex items-center gap-1 px-3 py-2 border-b shrink-0 overflow-x-auto"
            style={{ borderColor: "#1f1f1f", scrollbarWidth: "none" }}
          >
            {INSTRUMENTS.map((ticker) => {
              const hasFlag = flags.some((f) => f.instrument === ticker);
              const flagSeverity = flags.find((f) => f.instrument === ticker)?.severity;
              const chipColor = flagSeverity === "high"
                ? "#7f1d1d"
                : flagSeverity === "medium"
                ? "#78350f"
                : hasFlag
                ? "#1f2937"
                : "transparent";
              const isActive = selectedInstrument === ticker;
              return (
                <button
                  key={ticker}
                  onClick={() => {
                    setSelectedInstrument(ticker);
                    manualSelectionRef.current = true;
                  }}
                  className="px-2 py-0.5 rounded text-xs font-mono shrink-0"
                  style={{
                    background: isActive ? "#e5e5e5" : chipColor,
                    color: isActive ? "#0a0a0a" : hasFlag ? "#e5e5e5" : "#666",
                    border: "1px solid",
                    borderColor: isActive ? "#e5e5e5" : hasFlag ? "#333" : "#1f1f1f",
                  }}
                >
                  {ticker}
                </button>
              );
            })}
          </div>

          {/* Chart */}
          <div className="flex-1 overflow-hidden">
            <ArgusChart
              instrument={selectedInstrument}
              flags={flags}
              timeRange={timeRange}
            />
          </div>
        </main>

        {/* Right — tabbed flags / analyze */}
        <aside
          className="w-1/4 flex flex-col border-l"
          style={{ borderColor: "#1f1f1f", background: "#0d0d0d" }}
        >
          {/* Tab headers */}
          <div className="flex border-b shrink-0" style={{ borderColor: "#1f1f1f" }}>
            {(["FLAGS", "ANALYZE"] as const).map((tab) => {
              const tabLabel = tab === "FLAGS" && allFlags.length > 0
                ? `FLAGS (${allFlags.length})`
                : tab;
              return (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className="px-4 py-2 text-xs font-semibold uppercase tracking-widest"
                  style={{
                    color: activeTab === tab ? "#e5e5e5" : "#555",
                    borderBottom: activeTab === tab ? "1px solid #e5e5e5" : "1px solid transparent",
                    background: "transparent",
                  }}
                >
                  {tabLabel}
                </button>
              );
            })}
          </div>

          {/* FLAGS tab — anomaly log */}
          {activeTab === "FLAGS" && (
            <div className="flex-1 overflow-y-auto">
              {allFlags.length === 0 ? (
                <div className="flex items-center justify-center h-full">
                  <span style={{ color: "#444", fontSize: 13 }}>
                    {status === "connecting" ? "Connecting to Argus..." : "No anomalies detected."}
                  </span>
                </div>
              ) : (
                allFlags.map((flag) => (
                  <button
                    key={flag.id}
                    onClick={() => {
                      setSelectedInstrument(flag.instrument);
                      manualSelectionRef.current = true;
                    }}
                    style={{
                      display: "block",
                      width: "100%",
                      textAlign: "left",
                      background: selectedInstrument === flag.instrument ? "#161616" : "transparent",
                      borderBottom: "1px solid #1a1a1a",
                      padding: "10px 14px",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
                      <span
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: SEVERITY_DOT[flag.severity],
                          flexShrink: 0,
                          display: "inline-block",
                        }}
                      />
                      <span
                        style={{
                          fontFamily: "monospace",
                          fontWeight: 700,
                          fontSize: 13,
                          color: "#e5e5e5",
                          flexShrink: 0,
                        }}
                      >
                        {flag.instrument}
                      </span>
                      <span style={{ fontSize: 11, color: "#555", flexGrow: 1 }}>
                        {flag.type}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          color: "#333",
                          flexShrink: 0,
                          fontFamily: "monospace",
                        }}
                      >
                        {flag.timestamp.toLocaleTimeString("en-US", { hour12: false })}
                      </span>
                    </div>
                    <p style={{ fontSize: 12, color: "#666", margin: 0, lineHeight: 1.5, paddingLeft: 16 }}>
                      {flag.rationale}
                    </p>
                  </button>
                ))
              )}
            </div>
          )}

          {/* ANALYZE tab */}
          {activeTab === "ANALYZE" && (
            <div className="flex-1 flex flex-col p-4 overflow-y-auto gap-3">
              {/* History */}
              {history.length > 0 && (
                <div className="flex flex-col gap-2 shrink-0">
                  {history.map((entry, i) => (
                    <div key={i} className="border rounded" style={{ borderColor: "#1f1f1f" }}>
                      <button
                        onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
                        className="w-full flex items-center justify-between px-3 py-2 text-left"
                        style={{ background: "transparent" }}
                      >
                        <div className="flex flex-col gap-0.5">
                          <span className="text-xs font-semibold" style={{ color: "#e5e5e5" }}>
                            {entry.label}
                          </span>
                          <span className="text-xs" style={{ color: "#555" }}>
                            {formatTs(entry.timestamp)}
                          </span>
                        </div>
                        <span className="text-xs ml-2 shrink-0" style={{ color: "#555" }}>
                          {expandedIdx === i ? "▲" : "▼"}
                        </span>
                      </button>
                      {expandedIdx === i && (
                        <div
                          className="px-3 pb-3 text-xs font-mono leading-relaxed whitespace-pre-wrap"
                          style={{ color: "#ccc", background: "#111" }}
                        >
                          {entry.text}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Input form */}
              <div className="flex flex-col gap-2 shrink-0">
                <input
                  type="text"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="Fed speech, article, earnings..."
                  className="w-full px-3 py-2 text-xs rounded border bg-transparent"
                  style={{ borderColor: "#2a2a2a", color: "#e5e5e5", outline: "none" }}
                />
                <textarea
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  placeholder="Paste any text — article, transcript, research note — and Argus will contextualize it against live market conditions."
                  rows={6}
                  className="w-full px-3 py-2 text-xs rounded border bg-transparent resize-none"
                  style={{ borderColor: "#2a2a2a", color: "#e5e5e5", outline: "none" }}
                />
                <button
                  onClick={handleAnalyze}
                  disabled={isStreaming || !inputText.trim()}
                  className="w-full py-2 text-xs font-semibold rounded"
                  style={{
                    background: isStreaming || !inputText.trim() ? "#1a1a1a" : "#2a2a2a",
                    color: isStreaming || !inputText.trim() ? "#444" : "#e5e5e5",
                    cursor: isStreaming || !inputText.trim() ? "not-allowed" : "pointer",
                  }}
                >
                  {isStreaming ? "Analyzing..." : "Analyze"}
                </button>
              </div>

              {/* Streaming response */}
              {(isStreaming || response) && (
                <div
                  className="text-xs font-mono leading-relaxed whitespace-pre-wrap rounded p-3"
                  style={{ background: "#111", color: "#ccc" }}
                >
                  {isStreaming && !response
                    ? "Argus is reading..."
                    : response}
                  {isStreaming && response && (
                    <span className="animate-pulse" style={{ color: "#555" }}>
                      ▌
                    </span>
                  )}
                </div>
              )}

              {error && (
                <p className="text-xs shrink-0" style={{ color: "#e57373" }}>
                  Error: {error}
                </p>
              )}
            </div>
          )}
        </aside>
      </div>

      {/* Kalshi probability strip */}
      <KalshiStrip selectedInstrument={selectedInstrument} />
    </div>
  );
}
