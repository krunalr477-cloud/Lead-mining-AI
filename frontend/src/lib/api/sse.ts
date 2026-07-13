"use client";

import { useEffect } from "react";
import {
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { API_BASE } from "./client";
import { queryKeys } from "./keys";
import type { Job, JobEvent } from "./schema";

/** Max events retained per job in the cache (ring-buffer cap). */
const MAX_EVENTS = 500;

/** Stage -> approximate progress %, used when an event lacks explicit progress. */
const STAGE_PROGRESS: Record<string, number> = {
  resolving_location: 5,
  discovering: 15,
  deduping: 30,
  extracting: 45,
  enriching: 60,
  validating: 75,
  sales_ready: 88,
  syncing: 95,
  done: 100,
};

function isTerminalStage(stage: string | null): boolean {
  return stage === "done";
}

/**
 * Append an event to the capped events cache and patch the Job detail's
 * progress/status from the event's stage + payload. Idempotent on seq.
 *
 * `seed: true` (historical replay on mount) only appends to the events cache:
 * the job detail is already fresh from useJob, and replaying a stored "done"
 * event must not re-trigger the terminal invalidations on every page view.
 */
function applyEvent(
  qc: QueryClient,
  jobId: string,
  ev: JobEvent,
  opts?: { seed?: boolean },
) {
  // 1) Append to the capped events log.
  qc.setQueryData<JobEvent[]>(queryKeys.jobs.events(jobId), (prev) => {
    const list = prev ?? [];
    if (list.length && list[list.length - 1].seq >= ev.seq) {
      // Out-of-order/duplicate (e.g. reconnect replay) — dedupe by seq.
      if (list.some((e) => e.seq === ev.seq)) return list;
    }
    const next = [...list, ev].sort((a, b) => a.seq - b.seq);
    return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
  });

  if (opts?.seed) return;

  // 2) Patch the Job detail's progress + status from stage/payload.
  qc.setQueryData<Job | undefined>(queryKeys.jobs.detail(jobId), (prev) => {
    if (!prev) return prev;
    const next: Job = { ...prev };

    const stageProgress = ev.stage ? STAGE_PROGRESS[ev.stage] : undefined;
    if (stageProgress != null && stageProgress > next.progress_percent) {
      next.progress_percent = stageProgress;
    }

    // Counter payloads carry running totals; merge whatever keys are present.
    if (ev.payload && typeof ev.payload === "object") {
      const p = ev.payload as Record<string, unknown>;
      const totals = { ...next.totals_json };
      let touched = false;
      for (const k of Object.keys(totals) as (keyof typeof totals)[]) {
        if (typeof p[k] === "number") {
          totals[k] = p[k] as number;
          touched = true;
        }
      }
      if (touched) next.totals_json = totals;
    }

    if (isTerminalStage(ev.stage)) {
      next.status = "completed";
      next.progress_percent = 100;
    } else if (ev.level === "error") {
      next.status = "failed";
    }

    return next;
  });

  // 3) On terminal stage, refresh list + results once.
  if (isTerminalStage(ev.stage) || ev.level === "error") {
    qc.invalidateQueries({ queryKey: queryKeys.jobs.all() });
    qc.invalidateQueries({ queryKey: queryKeys.jobs.results(jobId) });
  }
}

/**
 * Subscribe to a job's live event stream and patch the React Query cache.
 *
 * - Opens EventSource(/api/jobs/{id}/events); parses each `data:` line as a
 *   typed JobEvent (flat log row: seq/stage/level/message/payload).
 * - Patches Job detail progress/totals/status and appends to a capped events
 *   array under queryKeys.jobs.events(jobId).
 * - Auto-reconnects with exponential backoff, honoring Last-Event-ID via the
 *   `?since=<seq>` cursor (EventSource also sets the Last-Event-Id header from
 *   the `id:` fields automatically, but we pass `since` explicitly for the
 *   polling fallback).
 * - After repeated EventSource failures, falls back to JSON polling
 *   (?format=json&since=<seq>).
 * - Closes when the job reaches a terminal state or enabled flips false.
 */
export function useJobStream(jobId: string | null | undefined, enabled = true) {
  const queryClient = useQueryClient();

  // ── Seed stored events on mount, for ANY job status ──────────────────────
  // Completed/failed jobs never open the live stream (enabled=false), but their
  // events are persisted server-side — fetch them once so the Event Log and
  // Stage Track render history instead of "Waiting for events…". Incremental
  // via after_seq when the user watched part of the run live. All writes go
  // through applyEvent's seq-dedupe, so a concurrent SSE stream can't race it.
  useEffect(() => {
    if (!jobId || typeof window === "undefined") return;
    let cancelled = false;
    const cached =
      queryClient.getQueryData<JobEvent[]>(queryKeys.jobs.events(jobId)) ?? [];
    const afterSeq = cached.length ? cached[cached.length - 1].seq : 0;
    const url =
      `${API_BASE}/jobs/${encodeURIComponent(jobId)}/events` +
      `?format=json&after_seq=${afterSeq}`;
    fetch(url, { credentials: "include", headers: { Accept: "application/json" } })
      .then((res) => (res.ok ? (res.json() as Promise<JobEvent[]>) : []))
      .then((rows) => {
        if (cancelled || !Array.isArray(rows)) return;
        for (const row of rows) applyEvent(queryClient, jobId, row, { seed: true });
      })
      .catch(() => {
        // Best-effort: live SSE/polling still covers active jobs.
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, queryClient]);

  useEffect(() => {
    if (!jobId || !enabled || typeof window === "undefined") return;

    let closed = false;
    let source: EventSource | null = null;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let backoff = 1000;
    let sseErrors = 0;
    let lastSeq = 0;

    const base = `${API_BASE}/jobs/${encodeURIComponent(jobId)}/events`;

    const stopSse = () => {
      if (source) {
        source.close();
        source = null;
      }
    };

    const finishIfTerminal = (ev: JobEvent) => {
      if (isTerminalStage(ev.stage) || ev.level === "error") {
        closed = true;
        stopSse();
        if (pollTimer) clearTimeout(pollTimer);
      }
    };

    const handle = (ev: JobEvent) => {
      if (ev.seq > lastSeq) lastSeq = ev.seq;
      applyEvent(queryClient, jobId, ev);
      finishIfTerminal(ev);
    };

    // ── JSON polling fallback ──────────────────────────────────────────
    const poll = async () => {
      if (closed) return;
      try {
        const url = `${base}?format=json&after_seq=${lastSeq}`;
        const res = await fetch(url, { credentials: "include" });
        if (res.ok) {
          const rows = (await res.json()) as JobEvent[];
          for (const row of rows) if (row.seq > lastSeq) handle(row);
        }
      } catch {
        // ignore; retry on the next tick
      }
      if (!closed) pollTimer = setTimeout(poll, 2000);
    };

    const startPolling = () => {
      stopSse();
      if (!closed && !pollTimer) poll();
    };

    // ── SSE with backoff reconnect ─────────────────────────────────────
    const connect = () => {
      if (closed) return;
      const url = lastSeq > 0 ? `${base}?after_seq=${lastSeq}` : base;
      try {
        source = new EventSource(url, { withCredentials: true });
      } catch {
        startPolling();
        return;
      }

      const onMessage = (e: MessageEvent) => {
        sseErrors = 0;
        backoff = 1000;
        let ev: JobEvent;
        try {
          ev = JSON.parse(e.data) as JobEvent;
        } catch {
          return;
        }
        handle(ev);
      };

      source.addEventListener("message", onMessage);
      source.onerror = () => {
        stopSse();
        if (closed) return;
        sseErrors += 1;
        if (sseErrors >= 4) {
          // Give up on SSE; switch to polling.
          startPolling();
          return;
        }
        const delay = Math.min(backoff, 15000);
        backoff *= 2;
        pollTimer = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      closed = true;
      stopSse();
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [jobId, enabled, queryClient]);
}

/**
 * Read-only accessor for the SSE-populated events cache. `useJobStream` writes
 * into queryKeys.jobs.events(jobId); this subscribes any component to that same
 * cache entry so the Event Log / Stage Track re-render as rows stream in.
 * No queryFn — the data is push-populated — so it never fetches on its own.
 */
export function useJobEvents(jobId: string | null | undefined): JobEvent[] {
  const { data } = useQuery<JobEvent[]>({
    enabled: !!jobId,
    queryKey: queryKeys.jobs.events(jobId ?? ""),
    queryFn: () => [],
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return data ?? [];
}
