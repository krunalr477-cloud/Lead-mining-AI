"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_BASE } from "./client";
import { queryKeys } from "./keys";
import type { Job, JobEvent } from "./schema";

/**
 * Subscribe to a job's live event stream (SSE) and patch the React Query cache
 * as events arrive. Minimal for the foundation: opens an EventSource, merges
 * progress/totals/status into the cached Job detail, and invalidates the list.
 *
 * The backend also serves ?format=json for a polling fallback; wiring that is
 * left for a later pass. EventSource sends the session cookie automatically
 * for same-origin requests (our /api rewrite keeps it same-origin).
 */
export function useJobStream(jobId: string | null | undefined, enabled = true) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!jobId || !enabled || typeof window === "undefined") return;

    const url = `${API_BASE}/jobs/${encodeURIComponent(jobId)}/events`;
    let source: EventSource;
    try {
      source = new EventSource(url, { withCredentials: true });
    } catch {
      return;
    }

    const onMessage = (ev: MessageEvent) => {
      let event: JobEvent;
      try {
        event = JSON.parse(ev.data) as JobEvent;
      } catch {
        return;
      }

      queryClient.setQueryData<Job | undefined>(
        queryKeys.jobs.detail(jobId),
        (prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            progress_percent: event.progress_percent ?? prev.progress_percent,
            status: event.status ?? prev.status,
            totals: event.totals ? { ...prev.totals, ...event.totals } : prev.totals,
          };
        },
      );

      // Terminal states: refresh the list view once.
      if (event.status && ["completed", "failed", "cancelled"].includes(event.status)) {
        queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all() });
      }
    };

    source.addEventListener("message", onMessage);
    source.onerror = () => {
      // Let the browser retry; a polling fallback can be added here later.
    };

    return () => {
      source.removeEventListener("message", onMessage);
      source.close();
    };
  }, [jobId, enabled, queryClient]);
}
