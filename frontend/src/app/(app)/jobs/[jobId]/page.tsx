"use client";

import { useState, useMemo, useEffect } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Pause,
  Square,
  ArrowRight,
  Clock,
  Hourglass,
  AlertTriangle,
  Layers,
} from "lucide-react";
import {
  Panel,
  PanelHeader,
  StatusChip,
  MetricCard,
  MicroLabel,
  ProgressBar,
  Button,
  CopyButton,
  ConfirmDialog,
  EmptyState,
  Skeleton,
  useToast,
} from "@/components/ui";
import {
  useJob,
  useJobStream,
  useJobEvents,
  usePauseJob,
  useCancelJob,
  useQueueHealth,
} from "@/lib/api/hooks";
import { useSession } from "@/lib/auth/session";
import { formatNumber, formatDuration } from "@/lib/format";
import { resolveStatus } from "@/lib/status";
import type { JobStatus, JobTotals } from "@/lib/api/schema";
import { StageTrack } from "./_components/StageTrack";
import { QueueGrid } from "./_components/QueueGrid";
import { EventLog } from "./_components/EventLog";

/**
 * §20 Job Run Monitor — the live command view for a single mining run.
 *
 * SSE DRIVES THE LIVE COUNTERS: useJobStream(jobId) opens the EventSource to
 * /api/jobs/{id}/events and patches the React-Query cache in place — appending
 * each JobEvent to queryKeys.jobs.events(jobId) and merging numeric payload
 * keys into the cached Job.totals_json. This component reads that same cache via
 * useJob() (for totals/progress/status) and useJobEvents() (for the log + stage
 * derivation), so every streamed counter re-renders the MetricCards, Stage
 * Track, and Event Log without any manual refetch. The stream self-closes on a
 * terminal event and falls back to JSON polling if SSE fails.
 */

const ACTIVE: JobStatus[] = ["running", "queued", "paused"];

/** Live-ticking elapsed clock; freezes when the run is no longer active. */
function useElapsed(startedAt: string | null, active: boolean): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  if (!startedAt) return null;
  const start = Date.parse(startedAt);
  if (!Number.isFinite(start)) return null;
  return Math.max(0, now - start);
}

/** Naive ETA from elapsed + progress (linear extrapolation). */
function estimateEta(elapsedMs: number | null, progress: number): number | null {
  if (elapsedMs == null || progress <= 0 || progress >= 100) return null;
  const total = elapsedMs / (progress / 100);
  return Math.max(0, total - elapsedMs);
}

function HeaderStat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-muted/70">{icon}</span>
      <div className="flex flex-col">
        <MicroLabel>{label}</MicroLabel>
        <span className="font-mono text-sm tabular-nums text-ink">{value}</span>
      </div>
    </div>
  );
}

const COUNTER_DEFS: {
  key: keyof JobTotals;
  label: string;
  tone?: "accent" | "danger" | "review";
}[] = [
  { key: "total_companies", label: "Companies" },
  { key: "total_contacts", label: "Contacts" },
  { key: "emails_found", label: "Emails Found" },
  { key: "verified_emails", label: "Verified", tone: "accent" },
  { key: "review_emails", label: "Review", tone: "review" },
  { key: "invalid_emails", label: "Invalid", tone: "danger" },
];

export default function JobMonitorPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = params.jobId;
  const toast = useToast();
  const session = useSession();

  const { data: job, isLoading, isError } = useJob(jobId);
  const status = job?.status;
  const isActive = status ? ACTIVE.includes(status) : false;

  // Open the SSE stream only while the run can still emit events.
  useJobStream(jobId, isActive);
  const events = useJobEvents(jobId);

  // Queue health polls on its own interval; slow it once the run is done.
  const { data: queues, isLoading: queuesLoading } = useQueueHealth(
    isActive ? 4000 : 20000,
  );

  const pause = usePauseJob();
  const cancel = useCancelJob();
  const [confirmPause, setConfirmPause] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  const canRun = session.can("job.run");

  const elapsed = useElapsed(job?.started_at ?? null, isActive);
  const eta = useMemo(
    () => estimateEta(elapsed, job?.progress_percent ?? 0),
    [elapsed, job?.progress_percent],
  );

  const doPause = () => {
    pause.mutate(jobId, {
      onSuccess: () => toast.info("Job paused"),
      onError: (e) => toast.error("Could not pause", e.message),
    });
    setConfirmPause(false);
  };

  const doCancel = () => {
    cancel.mutate(jobId, {
      onSuccess: () => toast.warn("Job cancelled"),
      onError: (e) => toast.error("Could not cancel", e.message),
    });
    setConfirmCancel(false);
  };

  if (isError) {
    return (
      <EmptyState
        icon={AlertTriangle}
        kicker="Mine · Monitor"
        title="Job not found"
        description="This mining run could not be loaded. It may have been removed."
        action={
          <Button size="sm" variant="secondary" asChild>
            <Link href="/jobs">Back to Job History</Link>
          </Button>
        }
      />
    );
  }

  const meta = resolveStatus(status);
  const isCompleted = status === "completed";
  const progress = job?.progress_percent ?? 0;

  return (
    <div className="flex flex-col gap-4">
      {/* ── HEADER STRIP ─────────────────────────────────────────────── */}
      <Panel>
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <MicroLabel className="text-accent/80">Mine · Monitor</MicroLabel>
                {job && <StatusChip status={status} />}
              </div>
              {isLoading || !job ? (
                <Skeleton className="h-7 w-64" />
              ) : (
                <h1 className="truncate text-xl font-semibold text-ink">
                  {job.name}
                </h1>
              )}
              <div className="flex items-center gap-1">
                <MicroLabel className="text-muted/70">JOB_ID</MicroLabel>
                <span className="font-mono text-[11px] text-muted">{jobId}</span>
                <CopyButton value={jobId} />
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              {isCompleted ? (
                <Button size="sm" asChild>
                  <Link href={`/jobs/${jobId}/results`}>
                    View Results <ArrowRight className="size-4" />
                  </Link>
                </Button>
              ) : (
                <>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={!canRun || !isActive || status === "paused" || pause.isPending}
                    loading={pause.isPending}
                    onClick={() => setConfirmPause(true)}
                    title={canRun ? undefined : "Requires job-run permission"}
                  >
                    <Pause className="size-4" /> Pause
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={!canRun || !isActive || cancel.isPending}
                    loading={cancel.isPending}
                    onClick={() => setConfirmCancel(true)}
                    title={canRun ? undefined : "Requires job-run permission"}
                  >
                    <Square className="size-4" /> Cancel
                  </Button>
                </>
              )}
            </div>
          </div>

          {/* Overall progress + elapsed/ETA */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <MicroLabel>Overall progress</MicroLabel>
              <span
                className="font-mono text-sm tabular-nums"
                style={{ color: meta.color }}
              >
                {Math.round(progress)}%
              </span>
            </div>
            <ProgressBar
              value={progress}
              variant={meta.variant}
              indeterminate={isActive && progress === 0}
            />
          </div>

          <div className="flex flex-wrap gap-x-8 gap-y-3">
            <HeaderStat
              icon={<Clock className="size-4" />}
              label="Elapsed"
              value={elapsed == null ? "—" : formatDuration(elapsed)}
            />
            <HeaderStat
              icon={<Hourglass className="size-4" />}
              label="ETA"
              value={
                isCompleted
                  ? "Done"
                  : eta == null
                    ? "—"
                    : `~${formatDuration(eta)}`
              }
            />
            <HeaderStat
              icon={<Layers className="size-4" />}
              label="Sales-ready"
              value={formatNumber(job?.totals_json.sales_ready_count ?? 0)}
            />
          </div>
        </div>
      </Panel>

      {/* ── STAGE TRACK ──────────────────────────────────────────────── */}
      <Panel>
        <PanelHeader>
          <MicroLabel>Pipeline stages</MicroLabel>
        </PanelHeader>
        {job ? (
          <StageTrack events={events} jobStatus={job.status} />
        ) : (
          <Skeleton className="h-16 w-full" />
        )}
      </Panel>

      {/* ── LIVE COUNTERS ────────────────────────────────────────────── */}
      <Panel>
        <PanelHeader
          actions={
            isActive ? (
              <span className="inline-flex items-center gap-1.5">
                <span className="size-1.5 animate-pulse rounded-full bg-accent shadow-[0_0_6px_var(--color-accent)]" />
                <MicroLabel className="text-accent">Live</MicroLabel>
              </span>
            ) : null
          }
        >
          <MicroLabel>Counters</MicroLabel>
        </PanelHeader>
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
          {COUNTER_DEFS.map((c) => (
            <MetricCard
              key={c.key}
              label={c.label}
              value={
                <span
                  style={
                    c.tone
                      ? {
                          color:
                            c.tone === "accent"
                              ? "var(--color-accent)"
                              : c.tone === "danger"
                                ? "var(--color-danger)"
                                : "var(--color-review)",
                        }
                      : undefined
                  }
                >
                  {formatNumber(job?.totals_json[c.key] ?? 0)}
                </span>
              }
            />
          ))}
        </div>
      </Panel>

      {/* ── QUEUE GRID + EVENT LOG ───────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Panel>
          <PanelHeader>
            <MicroLabel>Queue health</MicroLabel>
          </PanelHeader>
          <QueueGrid data={queues} loading={queuesLoading} />
        </Panel>

        <Panel>
          <EventLog events={events} />
        </Panel>
      </div>

      <ConfirmDialog
        open={confirmPause}
        onOpenChange={setConfirmPause}
        kicker="Pause run"
        title="Pause this mining job?"
        description="In-flight stages finish, then the pipeline halts. You can resume later from Job History."
        confirmLabel="Pause job"
        onConfirm={doPause}
        loading={pause.isPending}
      />
      <ConfirmDialog
        open={confirmCancel}
        onOpenChange={setConfirmCancel}
        destructive
        kicker="Cancel run"
        title="Cancel this mining job?"
        description="This stops the run and cannot be undone. Partial results already synced are kept."
        confirmLabel="Cancel job"
        onConfirm={doCancel}
        loading={cancel.isPending}
      />
    </div>
  );
}
