"use client";

import { useEffect, useRef, useState } from "react";

export type Flag = {
  instrument: string;
  type: string;
  severity: "low" | "medium" | "high";
  rationale: string;
};

export type FlagEntry = {
  id: string;
  timestamp: Date;
  instrument: string;
  type: string;
  severity: "low" | "medium" | "high";
  rationale: string;
};

export type FeedEntry = {
  id: string;
  timestamp: Date;
  narrative: string;
  flagCount: number;
  highCount: number;
  mediumCount: number;
  lowCount: number;
};

type StreamState = {
  flags: Flag[];
  allFlags: FlagEntry[];
  narrative: string;
  entries: FeedEntry[];
  lastUpdated: Date | null;
  status: "connecting" | "live" | "error";
};

const STREAM_URL = "http://localhost:8000/stream";
const MAX_BACKOFF = 30_000;

export function useArgusStream(): StreamState {
  const [state, setState] = useState<StreamState>({
    flags: [],
    allFlags: [],
    narrative: "",
    entries: [],
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
            const flags: Flag[] = data.flags ?? [];
            const cycleTs = new Date();
            const highCount = flags.filter((f) => f.severity === "high").length;
            const mediumCount = flags.filter((f) => f.severity === "medium").length;
            const lowCount = flags.filter((f) => f.severity === "low").length;
            const newEntry: FeedEntry = {
              id: `${Date.now()}-${Math.random()}`,
              timestamp: cycleTs,
              narrative: data.narrative ?? "",
              flagCount: flags.length,
              highCount,
              mediumCount,
              lowCount,
            };
            const newFlagEntries: FlagEntry[] = flags.map((f, i) => ({
              id: `${cycleTs.getTime()}-${i}`,
              timestamp: cycleTs,
              instrument: f.instrument,
              type: f.type,
              severity: f.severity,
              rationale: f.rationale,
            }));
            setState((s) => ({
              flags,
              allFlags: [...newFlagEntries, ...s.allFlags].slice(0, 200),
              narrative: data.narrative ?? "",
              lastUpdated: cycleTs,
              status: "live",
              entries: [newEntry, ...s.entries].slice(0, 50),
            }));
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
