"use client";

import { useState, useCallback } from "react";

const ANALYZE_URL = "http://localhost:8000/analyze";

type UseAnalysisReturn = {
  analyze: (text: string, label: string) => Promise<string>;
  response: string;
  isStreaming: boolean;
  error: string | null;
};

export function useAnalysis(): UseAnalysisReturn {
  const [response, setResponse] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = useCallback(async (text: string, label: string): Promise<string> => {
    setResponse("");
    setError(null);
    setIsStreaming(true);

    let accumulated = "";

    try {
      const res = await fetch(ANALYZE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, label }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const msg = JSON.parse(line.slice(6));
            if (msg.done) {
              return accumulated;
            }
            if (msg.token) {
              accumulated += msg.token;
              setResponse(accumulated);
            }
            if (msg.error) {
              setError(msg.error);
              return accumulated;
            }
          } catch {
            // ignore malformed SSE frames
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsStreaming(false);
    }

    return accumulated;
  }, []);

  return { analyze, response, isStreaming, error };
}
