"use client";

import { cn } from "@/lib/cn";
import { MicroLabel, StatusChip } from "@/components/ui";
import { formatNumber } from "@/lib/format";
import type {
  QueueHealth,
  SourceRunSummary,
  WorkersHealth,
} from "@/lib/api/schema";

/**
 * PIPELINE ACTIVITY — real per-source work from GET /jobs/{id}/sources
 * (runs, found → imported, retries, last error) plus a worker-liveness chip
 * from GET /workers/health. Replaces the old 12-row queue grid, which always
 * read zero because the pipeline runs monolithically in one worker task.
 */

const SOURCE_LABEL: Record<string, string> = {
  google_maps: "Google Maps",
  company_websites: "Website Crawl",
  directories: "Directories",
  yellow_pages: "Yellow Pages",
  clutch: "Clutch",
  facebook_signals: "Facebook Signals",
  serp_jobs: "Hiring Signals",
  indeed: "Indeed",
  linkedin: "LinkedIn",
};

function labelOf(key: string): string {
  return SOURCE_LABEL[key] ?? key.replace(/_/g, " ");
}

function chipFor(s: SourceRunSummary): { variant: "accent" | "danger" | "warn" | "info" | "muted"; label: string } {
  if (s.in_progress > 0) return { variant: "info", label: "RUNNING" };
  if (s.failed > 0 && s.completed === 0) return { variant: "danger", label: "FAILED" };
  if (s.failed > 0) return { variant: "warn", label: "PARTIAL" };
  if (s.runs > 0 && s.skipped === s.runs) return { variant: "muted", label: "SKIPPED" };
  return { variant: "accent", label: "DONE" };
}

export function PipelineActivity({
  sources,
  sourcesLoading,
  workers,
  queues,
  jobStatus,
}: {
  sources: SourceRunSummary[] | null | undefined;
  sourcesLoading: boolean;
  workers: WorkersHealth | null | undefined;
  queues: QueueHealth | null | undefined;
  jobStatus: string | undefined;
}) {
  const rows = sources ?? [];
  const workerKnown = workers != null;
  const workerUp = workers?.up === true;
  const backlog = queues?.total_pending ?? null;

  return (
    <div className="flex flex-col">
      {/* Worker / backlog chip row */}
      <div className="mb-3 flex flex-wrap items-center gap-2 px-1">
        {workerKnown && (
          <StatusChip
            variant={workerUp ? "accent" : "danger"}
            label={workerUp ? "WORKER UP" : "WORKER DOWN"}
          />
        )}
        {backlog != null && (
          <span className="font-mono text-[11px] uppercase tracking-wider text-muted">
            Queue backlog:{" "}
            <span className={cn("tabular-nums", backlog > 0 ? "text-info" : "text-muted")}>
              {formatNumber(backlog)}
            </span>
          </span>
        )}
      </div>
      {workerKnown && !workerUp && jobStatus === "queued" && (
        <p className="mb-3 px-1 text-xs text-warn">
          No worker is running — this job will stay queued until a worker starts.
        </p>
      )}

      {/* Per-source rows */}
      <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-4 px-1 pb-2">
        <MicroLabel>Source</MicroLabel>
        <MicroLabel className="text-right">Found → Imported</MicroLabel>
        <MicroLabel className="hidden text-right sm:block">Runs</MicroLabel>
        <MicroLabel className="hidden text-right sm:block">Retries</MicroLabel>
      </div>

      {sourcesLoading && rows.length === 0 && (
        <div className="flex flex-col gap-1.5 px-1">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-6 animate-pulse rounded bg-[var(--color-panel-strong)]"
            />
          ))}
        </div>
      )}

      {!sourcesLoading && rows.length === 0 && (
        <p className="px-1 py-3 text-sm text-muted">
          No per-source activity was recorded for this run.
        </p>
      )}

      <div className="flex flex-col">
        {rows.map((s) => {
          const chip = chipFor(s);
          return (
            <div key={s.source_name} className="border-t border-border px-1 py-1.5">
              <div className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-4">
                <span className="flex min-w-0 items-center gap-2 text-sm text-ink">
                  <span className="truncate">{labelOf(s.source_name)}</span>
                  <StatusChip variant={chip.variant} label={chip.label} hideDot />
                </span>
                <span className="text-right font-mono text-sm tabular-nums text-ink/90">
                  {formatNumber(s.records_found)}
                  <span className="text-muted"> → </span>
                  {formatNumber(s.records_imported)}
                </span>
                <span className="hidden text-right font-mono text-sm tabular-nums text-muted sm:block">
                  {formatNumber(s.runs)}
                </span>
                <span className="hidden text-right font-mono text-sm tabular-nums sm:block">
                  <span className={s.retries > 0 ? "text-warn" : "text-muted"}>
                    {s.retries > 0 ? formatNumber(s.retries) : "—"}
                  </span>
                </span>
              </div>
              {s.last_error && (
                <p className="mt-0.5 truncate font-mono text-[11px] text-danger/80">
                  {s.last_error}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
