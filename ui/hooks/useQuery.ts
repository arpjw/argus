"use client";

import { useState, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type QAPair = {
  id: string;
  question: string;
  answer: string;
  timestamp: Date;
};

type UseQueryReturn = {
  submit: (question: string) => void;
  history: QAPair[];
  streamingAnswer: string;
  pendingQuestion: string;
  isStreaming: boolean;
  rateLimited: boolean;
};

export function useQuery(): UseQueryReturn {
  const [history, setHistory] = useState<QAPair[]>([]);
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [rateLimited, setRateLimited] = useState(false);

  const submit = useCallback(
    async (question: string) => {
      if (!question.trim() || isStreaming) return;

      setStreamingAnswer("");
      setPendingQuestion(question);
      setIsStreaming(true);
      setRateLimited(false);

      let accumulated = "";

      try {
        const _apiKey = process.env.NEXT_PUBLIC_ARGUS_API_KEY ?? "";
        const _apiKeyParam = _apiKey ? `&api_key=${_apiKey}` : "";
        const res = await fetch(
          `${API_BASE}/query?question=${encodeURIComponent(question)}${_apiKeyParam}`
        );

        if (res.status === 429) {
          setRateLimited(true);
          return;
        }

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const reader = res.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let buffer = "";
        let currentEvent = "";

        outer: while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (line.startsWith("event: ")) {
              currentEvent = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              if (currentEvent === "done") {
                setHistory((prev) =>
                  [
                    {
                      id: `${Date.now()}-${Math.random()}`,
                      question,
                      answer: accumulated,
                      timestamp: new Date(),
                    },
                    ...prev,
                  ].slice(0, 5)
                );
                setStreamingAnswer("");
                setPendingQuestion("");
                break outer;
              }
              try {
                const msg = JSON.parse(line.slice(6));
                if (msg.type === "token") {
                  accumulated += msg.text;
                  setStreamingAnswer(accumulated);
                }
              } catch {}
              currentEvent = "";
            } else if (line === "") {
              currentEvent = "";
            }
          }
        }
      } catch {
        if (accumulated) {
          setHistory((prev) =>
            [
              {
                id: `${Date.now()}-${Math.random()}`,
                question,
                answer: accumulated,
                timestamp: new Date(),
              },
              ...prev,
            ].slice(0, 5)
          );
        }
        setStreamingAnswer("");
        setPendingQuestion("");
      } finally {
        setIsStreaming(false);
      }
    },
    [isStreaming]
  );

  return { submit, history, streamingAnswer, pendingQuestion, isStreaming, rateLimited };
}
