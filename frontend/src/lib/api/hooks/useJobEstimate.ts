"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "../client";
import type { JobCreate, JobEstimate } from "../schema";

export interface JobEstimateState {
  data: JobEstimate | null;
  isLoading: boolean;
  error: Error | null;
}

/**
 * Debounced POST /jobs/estimate. Recomputes whenever the draft changes and a
 * `ready` gate is true (e.g. required fields present), waiting `delayMs` after
 * the last edit before firing. In-flight requests are superseded so only the
 * latest draft's result lands. Returns null until the first estimate resolves.
 */
export function useJobEstimate(
  draft: JobCreate | null,
  ready = true,
  delayMs = 500,
): JobEstimateState {
  const [state, setState] = useState<JobEstimateState>({
    data: null,
    isLoading: false,
    error: null,
  });
  const reqId = useRef(0);
  const key = draft ? JSON.stringify(draft) : "";

  useEffect(() => {
    if (!draft || !ready) {
      setState((s) => ({ ...s, isLoading: false, error: null }));
      return;
    }

    const myReq = ++reqId.current;
    setState((s) => ({ ...s, isLoading: true, error: null }));

    const timer = setTimeout(async () => {
      try {
        const { data, response } = await api.POST("/api/v1/jobs/estimate", {
          body: draft,
        });
        if (myReq !== reqId.current) return; // superseded
        if (!response.ok || !data) {
          throw new Error(`Estimate failed (${response.status})`);
        }
        setState({ data, isLoading: false, error: null });
      } catch (err) {
        if (myReq !== reqId.current) return;
        setState((s) => ({
          ...s,
          isLoading: false,
          error: err instanceof Error ? err : new Error(String(err)),
        }));
      }
    }, delayMs);

    return () => clearTimeout(timer);
    // key captures the draft contents; ready/delay tracked directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ready, delayMs]);

  return state;
}
