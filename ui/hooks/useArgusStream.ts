"use client";

import { useEffect, useRef, useState } from "react";

export type Flag = {
  instrument: string;
  type: string;
  severity: "low" | "medium" | "high";
  rationale: string;
};

type StreamState = {
  flags: Flag[];
  narrative: string;
  lastUpdated: Date | null;
  status: "connecting" | "live" | "error";
};

const STREAM_URL = "http://localhost:8000/stream";
const MAX_BACKOFF = 30_000;

export function useArgusStream(): StreamState {
  const [state, setState] = useState<StreamState>({
    flags: [],
    narrative: "",
    lastUpdated: null,
    status: "connecting",
  });

  const backoffRef = useRef(5_000);
  const esRef = useRef<EventSource | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    function connect() {
      const es = new EventSource(STREAM_URL);
      esRef.current = es;

      setState((s) => ({ ...s, status: "connecting" }));

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "synthesis") {
            backoffRef.current = 5_000;
            setState({
              flags: data.flags ?? [],
              narrative: data.narrative ?? "",
              lastUpdated: new Date(),
              status: "live",
            });
          }
          // keepalive: no state change
        } catch {
          // malformed message — ignore
        }
      };

      es.onerror = () => {
        es.close();
        esRef.current = null;
        setState((s) => ({ ...s, status: "error" }));

        const delay = backoffRef.current;
        backoffRef.current = Math.min(delay * 2, MAX_BACKOFF);

        retryTimerRef.current = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      esRef.current?.close();
      esRef.current = null;
      if (retryTimerRef.current !== null) {
        clearTimeout(retryTimerRef.current);
      }
    };
  }, []);

  return state;
}
