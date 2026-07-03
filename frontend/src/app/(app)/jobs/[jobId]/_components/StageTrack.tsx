"use client";

import { Fragment } from "react";
import { Check, X, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { MicroLabel } from "@/components/ui";
import type { JobEvent, JobStatus } from "@/lib/api/schema";

/**
 * Horizontal STAGE TRACK — the pipeline stages the backend emits (verified
 * against the live SSE stream) rendered as connected nodes with per-node state:
 *   pending | running (accent pulse) | done | failed
 * plus a mono counter pulled from that stage's event payload when present.
 */

interface StageDef {
  /** Backend stage key(s) that map to this node (SSE `stage` field). */
  keys: string[];
  label: string;
  /** payload key -> short counter caption, shown under the node when present. */
  counterKey?: string;
}

/**
 * The canonical pipeline. Backend stages seen live:
 *   resolving_location, discovering, deduping, extracting, enriching,
 *   validating, sales_ready, syncing, done.
 * Displayed as the spec's Discover → Dedupe → Crawl → Extract → Enrich →
 * Validate → Sync → Sales-Ready track (resolve folded into Discover).
 */
const STAGES: StageDef[] = [
  { keys: ["resolving_location", "discovering"], label: "Discover", counterKey: "found" },
  { keys: ["deduping"], label: "Dedupe", counterKey: "unique" },
  { keys: ["crawling"], label: "Crawl", counterKey: "crawled" },
  { keys: ["extracting"], label: "Extract", counterKey: "extracted" },
  { keys: ["enriching"], label: "Enrich", counterKey: "enriched" },
  { keys: ["validating"], label: "Validate", counterKey: "verified_emails" },
  { keys: ["syncing"], label: "Sync", counterKey: "synced" },
  { keys: ["sales_ready", "done"], label: "Sales-Ready", counterKey: "sales_ready_count" },
];

type StageState = "pending" | "running" | "done" | "failed";

/** Ordinal of a raw backend stage within the display track (or -1). */
function stageIndex(rawStage: string | null): number {
  if (!rawStage) return -1;
  return STAGES.findIndex((s) => s.keys.includes(rawStage));
}

function deriveStates(
  events: JobEvent[],
  jobStatus: JobStatus,
): { states: StageState[]; counters: (string | null)[] } {
  // Latest stage the stream has reached.
  let maxIdx = -1;
  let failedIdx = -1;
  const counters: (string | null)[] = STAGES.map(() => null);

  for (const ev of events) {
    const idx = stageIndex(ev.stage);
    if (idx < 0) continue;
    if (idx > maxIdx) maxIdx = idx;
    if (ev.level === "error") failedIdx = idx;
    // Capture a counter from the payload if this stage defines one.
    const key = STAGES[idx].counterKey;
    if (key && ev.payload && typeof ev.payload[key] === "number") {
      counters[idx] = String(ev.payload[key]);
    }
  }

  const terminalDone =
    jobStatus === "completed" ||
    events.some((e) => e.stage === "done");
  const isFailed = jobStatus === "failed" || failedIdx >= 0;
  const isActive = jobStatus === "running" || jobStatus === "queued";

  const states: StageState[] = STAGES.map((_, i) => {
    if (isFailed && i === failedIdx) return "failed";
    if (terminalDone) return "done";
    if (i < maxIdx) return "done";
    if (i === maxIdx) return isActive ? "running" : "done";
    return "pending";
  });

  return { states, counters };
}

const NODE_STYLE: Record<StageState, string> = {
  pending: "border-border bg-[var(--color-surface-1)] text-muted",
  running: "border-accent/60 bg-accent/10 text-accent",
  done: "border-accent/40 bg-accent/15 text-accent",
  failed: "border-danger/60 bg-danger/10 text-danger",
};

export function StageTrack({
  events,
  jobStatus,
}: {
  events: JobEvent[];
  jobStatus: JobStatus;
}) {
  const { states, counters } = deriveStates(events, jobStatus);

  return (
    <div className="overflow-x-auto lm-scroll">
      <div className="flex min-w-max items-start gap-0 pb-1">
        {STAGES.map((stage, i) => {
          const state = states[i];
          const counter = counters[i];
          const connectorDone = states[i] === "done";
          return (
            <Fragment key={stage.label}>
              <div className="flex flex-col items-center gap-2 px-1">
                <div
                  className={cn(
                    "flex size-9 items-center justify-center rounded-full border transition-colors",
                    NODE_STYLE[state],
                  )}
                >
                  {state === "done" && <Check className="size-4" />}
                  {state === "failed" && <X className="size-4" />}
                  {state === "running" && (
                    <Loader2 className="size-4 animate-spin" />
                  )}
                  {state === "pending" && (
                    <span className="font-mono text-[11px]">{i + 1}</span>
                  )}
                </div>
                <div className="flex flex-col items-center gap-0.5">
                  <MicroLabel
                    className={cn(
                      "whitespace-nowrap",
                      state === "running" && "text-accent",
                      state === "failed" && "text-danger",
                      state === "done" && "text-ink",
                    )}
                  >
                    {stage.label}
                  </MicroLabel>
                  <span
                    className={cn(
                      "font-mono text-[11px] tabular-nums",
                      counter ? "text-muted" : "text-transparent",
                    )}
                  >
                    {counter ?? "0"}
                  </span>
                </div>
              </div>
              {i < STAGES.length - 1 && (
                <div className="mt-4 h-px w-6 shrink-0 sm:w-10">
                  <div
                    className={cn(
                      "h-full w-full",
                      connectorDone ? "bg-accent/40" : "bg-border",
                    )}
                  />
                </div>
              )}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}
