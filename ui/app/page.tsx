"use client";

import { useState } from "react";
import { useArgusStream, type Flag } from "../hooks/useArgusStream";
import { useAnalysis } from "../hooks/useAnalysis";

const SEVERITY_BADGE: Record<Flag["severity"], string> = {
  high: "bg-red-700 text-red-100",
  medium: "bg-amber-700 text-amber-100",
  low: "bg-zinc-700 text-zinc-300",
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
  const { flags, narrative, lastUpdated, status } = useArgusStream();
  const { analyze, response, isStreaming, error } = useAnalysis();

  const [activeTab, setActiveTab] = useState<"FLAGS" | "ANALYZE">("FLAGS");
  const [label, setLabel] = useState("");
  const [inputText, setInputText] = useState("");
  const [history, setHistory] = useState<AnalysisEntry[]>([]);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

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
        {/* Left — narrative */}
        <aside
          className="w-1/4 flex flex-col p-4 overflow-y-auto border-r"
          style={{ borderColor: "#1f1f1f", background: "#0d0d0d" }}
        >
          <p className="text-xs font-semibold uppercase tracking-widest mb-3" style={{ color: "#555" }}>
            Narrative
          </p>
          {status === "connecting" && !narrative ? (
            <p className="text-sm" style={{ color: "#555" }}>
              Connecting to Argus...
            </p>
          ) : (
            <p className="text-sm leading-relaxed" style={{ color: "#ccc" }}>
              {narrative || "Awaiting synthesis..."}
            </p>
          )}
        </aside>

        {/* Center — chart placeholder */}
        <main
          className="w-1/2 flex items-center justify-center"
          style={{ background: "#0a0a0a" }}
        >
          <div
            className="border rounded px-8 py-6 text-sm"
            style={{ borderColor: "#2a2a2a", color: "#444" }}
          >
            Chart coming in ARG-12
          </div>
        </main>

        {/* Right — tabbed flags / analyze */}
        <aside
          className="w-1/4 flex flex-col border-l"
          style={{ borderColor: "#1f1f1f", background: "#0d0d0d" }}
        >
          {/* Tab headers */}
          <div className="flex border-b shrink-0" style={{ borderColor: "#1f1f1f" }}>
            {(["FLAGS", "ANALYZE"] as const).map((tab) => (
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
                {tab}
              </button>
            ))}
          </div>

          {/* FLAGS tab */}
          {activeTab === "FLAGS" && (
            <div className="flex-1 p-4 overflow-y-auto">
              {flags.length === 0 ? (
                <p className="text-sm" style={{ color: "#555" }}>
                  {status === "connecting" ? "Connecting to Argus..." : "No flags."}
                </p>
              ) : (
                <ul className="flex flex-col gap-3">
                  {flags.map((flag, i) => (
                    <li
                      key={i}
                      className="flex flex-col gap-1 border rounded p-3"
                      style={{ borderColor: "#1f1f1f" }}
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={`text-xs px-1.5 py-0.5 rounded font-semibold ${SEVERITY_BADGE[flag.severity]}`}
                        >
                          {flag.severity}
                        </span>
                        <span className="text-xs font-semibold" style={{ color: "#e5e5e5" }}>
                          {flag.instrument}
                        </span>
                        <span className="text-xs" style={{ color: "#888" }}>
                          {flag.type}
                        </span>
                      </div>
                      <p className="text-xs leading-relaxed" style={{ color: "#999" }}>
                        {flag.rationale}
                      </p>
                    </li>
                  ))}
                </ul>
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
    </div>
  );
}
