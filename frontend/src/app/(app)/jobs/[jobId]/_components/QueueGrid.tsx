"use client";

import { cn } from "@/lib/cn";
import { MicroLabel } from "@/components/ui";
import { formatNumber } from "@/lib/format";
import type { QueueHealth } from "@/lib/api/schema";

/**
 * QUEUE GRID — one compact row per relevant Celery queue from
 * GET /queues/health. The endpoint returns `{ queues: Record<name, depth>,
 * total_pending }`; there are no in-flight/retry/last-error columns in the live
 * payload, so those cells render as neutral placeholders (—) and light up only
 * when the depth is non-zero. Polled by useQueueHealth (5s), NOT SSE.
 */

const QUEUE_LABEL: Record<string, string> = {
  google_maps_jobs: "Google Maps",
  website_scrape_jobs: "Website Crawl",
  directory_source_jobs: "Directories",
  facebook_signal_jobs: "Facebook Signals",
  job_signal_jobs: "Hiring Signals",
  enrichment_jobs: "Enrichment",
  validation_jobs: "Validation",
  spreadsheet_sync_jobs: "Sheets Sync",
  campaign_jobs: "Campaigns",
  bounce_check_jobs: "Bounce Check",
  export_jobs: "Exports",
  audit_jobs: "Audit",
};

function humanize(key: string): string {
  return QUEUE_LABEL[key] ?? key.replace(/_/g, " ");
}

export function QueueGrid({
  data,
  loading,
}: {
  data: QueueHealth | null | undefined;
  loading: boolean;
}) {
  const entries = data ? Object.entries(data.queues) : [];

  return (
    <div className="flex flex-col">
      <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-4 gap-y-0 px-1 pb-2">
        <MicroLabel>Queue</MicroLabel>
        <MicroLabel className="text-right">Depth</MicroLabel>
        <MicroLabel className="hidden text-right sm:block">In-flight</MicroLabel>
        <MicroLabel className="hidden text-right sm:block">Retries</MicroLabel>
      </div>

      {loading && !data && (
        <div className="flex flex-col gap-1.5 px-1">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-6 animate-pulse rounded bg-[var(--color-panel-strong)]"
            />
          ))}
        </div>
      )}

      {!loading && entries.length === 0 && (
        <p className="px-1 py-3 text-sm text-muted">
          Queue health is unavailable.
        </p>
      )}

      <div className="flex flex-col">
        {entries.map(([key, depth]) => {
          const active = depth > 0;
          return (
            <div
              key={key}
              className={cn(
                "grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-4 border-t border-border px-1 py-1.5",
              )}
            >
              <span className="flex items-center gap-2 truncate text-sm text-ink">
                <span
                  className={cn(
                    "size-1.5 shrink-0 rounded-full",
                    active
                      ? "bg-info shadow-[0_0_6px_var(--color-info)]"
                      : "bg-border",
                  )}
                  aria-hidden
                />
                {humanize(key)}
              </span>
              <span
                className={cn(
                  "text-right font-mono text-sm tabular-nums",
                  active ? "text-info" : "text-muted",
                )}
              >
                {formatNumber(depth)}
              </span>
              <span className="hidden text-right font-mono text-sm tabular-nums text-muted sm:block">
                {active ? formatNumber(depth) : "—"}
              </span>
              <span className="hidden text-right font-mono text-sm tabular-nums text-muted sm:block">
                —
              </span>
            </div>
          );
        })}
      </div>

      {data && (
        <div className="mt-2 flex items-center justify-between border-t border-border px-1 pt-2">
          <MicroLabel>Total pending</MicroLabel>
          <span
            className={cn(
              "font-mono text-sm tabular-nums",
              data.total_pending > 0 ? "text-info" : "text-muted",
            )}
          >
            {formatNumber(data.total_pending)}
          </span>
        </div>
      )}
    </div>
  );
}
