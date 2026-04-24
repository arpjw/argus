"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import dynamic from "next/dynamic";
import { useArgusStream, type FlagEntry } from "../hooks/useArgusStream";
import { useAnalysis } from "../hooks/useAnalysis";
import { useQuery } from "../hooks/useQuery";
import KalshiStrip from "../components/KalshiStrip";

const ArgusChart = dynamic(() => import("../components/ArgusChart"), { ssr: false });

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const WATCHLIST = [
  "ES=F", "NQ=F", "RTY=F", "YM=F",
  "CL=F", "NG=F", "GC=F", "SI=F",
  "ZB=F", "ZN=F", "ZC=F", "ZS=F", "ZW=F",
  "6E=F", "6J=F", "6B=F", "6A=F",
  "HG=F", "VX=F", "BTC-USD",
] as const;

const SHORT_TO_TICKER: Record<string, string> = {
  "ES": "ES=F", "NQ": "NQ=F", "RTY": "RTY=F", "YM": "YM=F",
  "CL": "CL=F", "NG": "NG=F", "GC": "GC=F", "SI": "SI=F",
  "ZB": "ZB=F", "ZN": "ZN=F", "ZC": "ZC=F", "ZS": "ZS=F", "ZW": "ZW=F",
  "6E": "6E=F", "6J": "6J=F", "6B": "6B=F", "6A": "6A=F",
  "HG": "HG=F", "VX": "VX=F", "BTC": "BTC-USD",
};

type TimeRange = "1H" | "4H" | "1D";

interface BarData { timestamp: string; open: number; high: number; low: number; close: number; volume: number; }

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

export default function Home() {
  const { flags, allFlags, entries, lastUpdated, status, streamingNarrative, isStreaming: isSynthesizing } = useArgusStream();
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = feedRef.current;
    if (!el || entries.length === 0) return;
    if (el.scrollTop <= 50) {
      el.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [entries.length]);

  const { analyze, response, isStreaming, error } = useAnalysis();
  const { submit: submitQuery, history: queryHistory, streamingAnswer, pendingQuestion, isStreaming: isQueryStreaming, rateLimited } = useQuery();
  const [queryInput, setQueryInput] = useState("");

  const [activeTab, setActiveTab] = useState<"FLAGS" | "ANALYZE">("FLAGS");
  const [label, setLabel] = useState("");
  const [inputText, setInputText] = useState("");
  const [history, setHistory] = useState<AnalysisEntry[]>([]);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const [timeRange, setTimeRange] = useState<TimeRange>("1D");

  // Search state
  const [searchInput, setSearchInput] = useState("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [recentTickers, setRecentTickers] = useState<string[]>([]);
  const [selectedTicker, setSelectedTicker] = useState("ES=F");
  const [selectedName, setSelectedName] = useState("E-mini S&P 500");
  const [selectedBars, setSelectedBars] = useState<BarData[] | null>(null);
  const debounceRef = useRef<NodeJS.Timeout>();

  // Load recent tickers from localStorage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem("argus_recent_tickers");
      if (stored) setRecentTickers(JSON.parse(stored));
    } catch {}
  }, []);

  const performSearch = useCallback(async (ticker: string) => {
    if (!ticker.trim()) {
      setSearchError(null);
      return;
    }
    setSearchLoading(true);
    try {
      const _apiKey = process.env.NEXT_PUBLIC_ARGUS_API_KEY ?? "";
      const res = await fetch(`${API_BASE}/prices/search?ticker=${encodeURIComponent(ticker)}`, {
        headers: _apiKey ? { "X-Api-Key": _apiKey } : {},
      });
      const data = await res.json();
      if (data.valid && data.bars?.length) {
        setSelectedTicker(data.ticker);
        setSelectedName(data.name || data.ticker);
        setSelectedBars(data.bars);
        setSearchError(null);
        setRecentTickers((prev) => {
          const updated = [data.ticker, ...prev.filter((t) => t !== data.ticker)].slice(0, 5);
          try { localStorage.setItem("argus_recent_tickers", JSON.stringify(updated)); } catch {}
          return updated;
        });
      } else {
        setSearchError("Ticker not found");
      }
    } catch {
      setSearchError("Search failed");
    } finally {
      setSearchLoading(false);
    }
  }, []);

  // Debounce search on input change
  useEffect(() => {
    clearTimeout(debounceRef.current);
    if (!searchInput.trim()) {
      setSearchError(null);
      return;
    }
    debounceRef.current = setTimeout(() => {
      performSearch(searchInput);
    }, 400);
    return () => clearTimeout(debounceRef.current);
  }, [searchInput, performSearch]);

  function handleChipClick(ticker: string) {
    clearTimeout(debounceRef.current);
    setSearchInput(ticker);
    performSearch(ticker);
  }

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

  const showChips = !(searchInput.trim() && searchLoading);

  // Derive short ticker for KalshiStrip
  const shortTicker = selectedTicker.replace(/=F$/, "").replace(/-USD$/, "");

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

          <div ref={feedRef} className="flex-1 overflow-y-auto">
            {/* Live streaming narrative — shown at top while tokens arrive */}
            {(isSynthesizing || streamingNarrative) && (
              <div
                className="px-4 py-3"
                style={{ borderBottom: "1px solid #1a1a1a" }}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono" style={{ color: "#555", fontSize: "11px" }}>
                    streaming...
                  </span>
                </div>
                <p className="font-mono leading-relaxed" style={{ color: "#ccc", fontSize: "13px" }}>
                  {streamingNarrative}
                  {isSynthesizing && <span className="cursor-blink">|</span>}
                </p>
              </div>
            )}

            {/* Historical entries — or empty state */}
            {entries.length === 0 && !isSynthesizing && !streamingNarrative ? (
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
          {/* Panel header: ticker name + time range */}
          <div
            className="flex items-center justify-between px-4 py-2 border-b shrink-0"
            style={{ borderColor: "#1f1f1f" }}
          >
            <span className="text-sm font-mono" style={{ color: "#e5e5e5" }}>
              {selectedTicker} · {selectedName}
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

          {/* Search input */}
          <div
            className="px-3 pt-2 pb-1 border-b shrink-0"
            style={{ borderColor: "#1f1f1f" }}
          >
            <div className="relative">
              <input
                type="text"
                value={searchInput}
                onChange={(e) => {
                  setSearchInput(e.target.value);
                  if (searchError) setSearchError(null);
                }}
                placeholder="Search any ticker — NVDA, SPY, BTC-USD, ES=F..."
                className="w-full px-3 py-1.5 text-xs rounded font-mono"
                style={{
                  background: "#111",
                  border: "1px solid #222",
                  color: "#e5e5e5",
                  outline: "none",
                  paddingRight: searchLoading ? "2rem" : undefined,
                }}
              />
              {searchLoading && (
                <span
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-xs animate-spin"
                  style={{ color: "#555" }}
                >
                  ◌
                </span>
              )}
            </div>
            {searchError && (
              <p className="mt-1 text-xs font-mono" style={{ color: "#7f1d1d" }}>
                {searchError}
              </p>
            )}
          </div>

          {/* Chip rows — hidden while actively searching */}
          {showChips && (
            <div
              className="flex flex-col gap-1 px-3 py-2 border-b shrink-0"
              style={{ borderColor: "#1f1f1f" }}
            >
              {recentTickers.length > 0 && (
                <div className="flex items-center gap-1 overflow-x-auto" style={{ scrollbarWidth: "none" }}>
                  <span className="text-xs shrink-0 mr-1 font-mono" style={{ color: "#444" }}>
                    RECENT
                  </span>
                  {recentTickers.map((t) => (
                    <button
                      key={t}
                      onClick={() => handleChipClick(t)}
                      className="px-2 py-0.5 rounded text-xs font-mono shrink-0"
                      style={{
                        background: selectedTicker === t ? "#e5e5e5" : "#1a1a1a",
                        color: selectedTicker === t ? "#0a0a0a" : "#888",
                        border: "1px solid",
                        borderColor: selectedTicker === t ? "#e5e5e5" : "#2a2a2a",
                      }}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-1 overflow-x-auto" style={{ scrollbarWidth: "none" }}>
                <span className="text-xs shrink-0 mr-1 font-mono" style={{ color: "#444" }}>
                  WATCHLIST
                </span>
                {WATCHLIST.map((t) => {
                  const instrBase = t.replace(/=F$/, "").replace(/-USD$/, "");
                  const hasFlag = flags.some((f) => f.instrument === instrBase);
                  const flagSeverity = flags.find((f) => f.instrument === instrBase)?.severity;
                  const chipBg = flagSeverity === "high"
                    ? "#7f1d1d"
                    : flagSeverity === "medium"
                    ? "#78350f"
                    : hasFlag
                    ? "#1f2937"
                    : "transparent";
                  const isActive = selectedTicker === t;
                  return (
                    <button
                      key={t}
                      onClick={() => handleChipClick(t)}
                      className="px-2 py-0.5 rounded text-xs font-mono shrink-0"
                      style={{
                        background: isActive ? "#e5e5e5" : chipBg,
                        color: isActive ? "#0a0a0a" : hasFlag ? "#e5e5e5" : "#666",
                        border: "1px solid",
                        borderColor: isActive ? "#e5e5e5" : hasFlag ? "#333" : "#1f1f1f",
                      }}
                    >
                      {instrBase}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Chart */}
          <div className="flex-1 overflow-hidden">
            <ArgusChart
              instrument={selectedTicker}
              flags={flags}
              timeRange={timeRange}
              initialBars={selectedBars ?? undefined}
            />
          </div>
        </main>

        {/* Right — tabbed flags / analyze */}
        <aside
          className="w-1/4 flex flex-col border-l"
          style={{ borderColor: "#1f1f1f", background: "#0d0d0d" }}
        >
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
                allFlags.map((flag) => {
                  const fullTicker = SHORT_TO_TICKER[flag.instrument] ?? flag.instrument;
                  return (
                    <button
                      key={flag.id}
                      onClick={() => handleChipClick(fullTicker)}
                      style={{
                        display: "block",
                        width: "100%",
                        textAlign: "left",
                        background: selectedTicker === fullTicker ? "#161616" : "transparent",
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
                  );
                })
              )}
            </div>
          )}

          {/* ANALYZE tab */}
          {activeTab === "ANALYZE" && (
            <div className="flex-1 flex flex-col overflow-hidden">
              {/* Query input — sticky at top */}
              <div className="shrink-0 px-3 pt-3 pb-2 border-b" style={{ borderColor: "#1f1f1f" }}>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (queryInput.trim()) {
                      submitQuery(queryInput.trim());
                      setQueryInput("");
                    }
                  }}
                  className="flex gap-2"
                >
                  <input
                    type="text"
                    value={queryInput}
                    onChange={(e) => setQueryInput(e.target.value)}
                    disabled={isQueryStreaming}
                    placeholder="Ask Argus anything..."
                    className="flex-1 min-w-0 px-2 py-1.5 text-xs rounded border bg-transparent"
                    style={{
                      borderColor: "#2a2a2a",
                      color: "#e5e5e5",
                      outline: "none",
                      opacity: isQueryStreaming ? 0.5 : 1,
                    }}
                  />
                  <button
                    type="submit"
                    disabled={isQueryStreaming || !queryInput.trim()}
                    className="px-3 py-1.5 text-xs font-semibold rounded shrink-0"
                    style={{
                      background: isQueryStreaming || !queryInput.trim() ? "#1a1a1a" : "#2a2a2a",
                      color: isQueryStreaming || !queryInput.trim() ? "#444" : "#e5e5e5",
                      cursor: isQueryStreaming || !queryInput.trim() ? "not-allowed" : "pointer",
                    }}
                  >
                    Ask
                  </button>
                </form>
                {rateLimited && (
                  <p className="mt-1.5 text-xs font-mono" style={{ color: "#b45309" }}>
                    Please wait a moment before asking again.
                  </p>
                )}
              </div>

              {/* Scrollable body */}
              <div className="flex-1 overflow-y-auto flex flex-col p-3 gap-3">
                {/* Active streaming Q&A */}
                {isQueryStreaming && (
                  <div>
                    <p className="text-xs font-mono mb-1" style={{ color: "#555" }}>
                      Q: {pendingQuestion}
                    </p>
                    <div
                      className="text-xs font-mono leading-relaxed whitespace-pre-wrap"
                      style={{ color: "#ccc" }}
                    >
                      {streamingAnswer || "..."}
                      <span className="cursor-blink">|</span>
                    </div>
                  </div>
                )}

                {/* Q&A history — newest at top */}
                {queryHistory.map((qa) => (
                  <div key={qa.id} className="pb-2" style={{ borderBottom: "1px solid #1a1a1a" }}>
                    <p className="text-xs font-mono mb-1" style={{ color: "#555" }}>
                      Q: {qa.question}
                    </p>
                    <p
                      className="text-xs font-mono leading-relaxed whitespace-pre-wrap"
                      style={{ color: "#ccc" }}
                    >
                      {qa.answer}
                    </p>
                    <p className="text-xs mt-1 font-mono" style={{ color: "#333" }}>
                      {formatTs(qa.timestamp)}
                    </p>
                  </div>
                ))}

                {/* Divider before document analysis */}
                <div className="shrink-0 pt-1">
                  <div className="border-t mb-2" style={{ borderColor: "#2a2a2a" }} />
                  <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "#333" }}>
                    Analyze Document
                  </span>
                </div>

                {/* Document analysis history accordion */}
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

                {/* Document analysis form */}
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

                {(isStreaming || response) && (
                  <div
                    className="text-xs font-mono leading-relaxed whitespace-pre-wrap rounded p-3"
                    style={{ background: "#111", color: "#ccc" }}
                  >
                    {isStreaming && !response ? "Argus is reading..." : response}
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
            </div>
          )}
        </aside>
      </div>

      {/* Kalshi probability strip */}
      <KalshiStrip selectedInstrument={shortTicker} />
    </div>
  );
}
