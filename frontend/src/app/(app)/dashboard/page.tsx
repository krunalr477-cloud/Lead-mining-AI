"use client";

import { useMemo } from "react";
import Link from "next/link";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Activity,
  BarChart3,
  Database,
  ExternalLink,
  Gauge,
  Layers,
  MapPin,
  Plus,
  ShieldCheck,
  Sheet,
  Target,
} from "lucide-react";
import {
  Panel,
  MetricCard,
  MicroLabel,
  Button,
  StatusChip,
  ProgressBar,
  DataTable,
  EmptyState,
  Skeleton,
} from "@/components/ui";
import {
  useDashboardSummary,
  useFunnel,
  useSourcePerformance,
  useCampaignPerformance,
  useQueueHealth,
  useSheetsStatus,
  useJobs,
  useCompanyMap,
} from "@/lib/api/hooks";
import type {
  JobListItem,
  SourcePerformance,
  CampaignPerformance,
} from "@/lib/api/schema";
import {
  formatNumber,
  formatPercent,
  formatCurrency,
  formatRelative,
} from "@/lib/format";
import { FunnelChartWrapper } from "@/components/charts/funnel";
import { BarsChart } from "@/components/charts/stacked-bars";
import { DonutChart, type DonutDatum } from "@/components/charts/donut";
import { CHART } from "@/components/charts/theme";
import { DashboardMap } from "./dashboard-map";

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY ?? "";
const HAS_MAPS = MAPS_KEY.trim().length > 0;

/* Human labels for the 12 backend queues + the sources. */
const QUEUE_LABELS: Record<string, string> = {
  google_maps_jobs: "Google Maps",
  website_scrape_jobs: "Website Scrape",
  directory_source_jobs: "Directories",
  facebook_signal_jobs: "Facebook Signals",
  job_signal_jobs: "Job Signals",
  enrichment_jobs: "Enrichment",
  validation_jobs: "Validation",
  spreadsheet_sync_jobs: "Sheets Sync",
  campaign_jobs: "Campaigns",
  bounce_check_jobs: "Bounce Check",
  export_jobs: "Exports",
  audit_jobs: "Audit",
};

const SOURCE_LABELS: Record<string, string> = {
  google_maps: "Google Maps",
  company_websites: "Websites",
  directories: "Directories",
  facebook_signals: "Facebook",
  facebook: "Facebook",
  job_signals: "Job Signals",
};

function sourceLabel(name: string): string {
  return SOURCE_LABELS[name] ?? name.replace(/_/g, " ");
}

const POSTURE_COLOR: Record<string, string> = {
  green: CHART.accent,
  official: CHART.accent,
  amber: CHART.warn,
  gated: CHART.warn,
  red: CHART.danger,
  disabled: CHART.danger,
};

/* ── Panel header helper ─────────────────────────────────────────────── */

function PanelTitle({
  icon: Icon,
  kicker,
  title,
  actions,
}: {
  icon: React.ComponentType<{ className?: string }>;
  kicker: string;
  title: string;
  actions?: React.ReactNode;
}) {
  return (
    <Panel.Header actions={actions}>
      <div className="flex items-center gap-2">
        <Icon className="size-3.5 text-muted" />
        <MicroLabel className="text-accent/80">{kicker}</MicroLabel>
      </div>
      <h2 className="text-sm font-semibold text-ink">{title}</h2>
    </Panel.Header>
  );
}

/* ── Active jobs table ───────────────────────────────────────────────── */

const jobColumns: ColumnDef<JobListItem, unknown>[] = [
  {
    accessorKey: "name",
    header: "Job",
    meta: { mobilePriority: "high" },
    cell: ({ row }) => (
      <Link
        href={`/jobs/${row.original.id}`}
        className="font-medium text-ink hover:text-accent"
      >
        {row.original.name}
      </Link>
    ),
  },
  {
    accessorKey: "status",
    header: "Status",
    meta: { mobilePriority: "high" },
    cell: ({ getValue }) => <StatusChip status={getValue() as string} />,
  },
  {
    id: "location",
    header: "Location",
    meta: { mobilePriority: "low" },
    cell: ({ row }) => {
      const { city, state } = row.original;
      return (
        <span className="text-muted">
          {[city, state].filter(Boolean).join(", ") || "—"}
        </span>
      );
    },
  },
  {
    accessorKey: "progress_percent",
    header: "Progress",
    meta: { mobilePriority: "high", align: "left" },
    cell: ({ row }) => {
      const pct = row.original.progress_percent ?? 0;
      const running = row.original.status === "running";
      return (
        <div className="flex min-w-[120px] items-center gap-2">
          <ProgressBar
            value={pct}
            variant={running ? "info" : "accent"}
            indeterminate={running && pct === 0}
            className="w-24"
          />
          <span className="font-mono text-xs tabular-nums text-muted">
            {Math.round(pct)}%
          </span>
        </div>
      );
    },
  },
];

/* ── Page ────────────────────────────────────────────────────────────── */

export default function DashboardPage() {
  const summary = useDashboardSummary();
  const funnel = useFunnel();
  const sources = useSourcePerformance();
  const campaigns = useCampaignPerformance();
  const queues = useQueueHealth();
  const sheets = useSheetsStatus();
  const jobsQ = useJobs();

  const s = summary.data;

  const activeJobs = useMemo(
    () =>
      (jobsQ.data ?? []).filter(
        (j) => j.status === "running" || j.status === "queued",
      ),
    [jobsQ.data],
  );

  // Newest job overall — feeds the map preview + the keyless fallback link.
  const newestJob = useMemo(() => {
    const list = jobsQ.data ?? [];
    if (!list.length) return null;
    return [...list].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0];
  }, [jobsQ.data]);

  const companyMap = useCompanyMap(HAS_MAPS ? newestJob?.id : undefined);
  const mapCompanies = useMemo(
    () => Object.values(companyMap.data ?? {}),
    [companyMap.data],
  );

  /* Funnel data (backend already ships display-ready labels + counts). */
  const funnelData = funnel.data?.stages ?? [];

  /* Campaign performance rows for the grouped bars. */
  const campaignRows = useMemo(
    () =>
      (campaigns.data ?? []).map((c: CampaignPerformance) => ({
        name: c.name.length > 18 ? `${c.name.slice(0, 17)}…` : c.name,
        Sent: c.sent,
        Delivered: c.delivered,
        Opened: c.opened,
        Clicked: c.clicked,
        Replied: c.replied,
        Bounced: c.bounced,
      })),
    [campaigns.data],
  );

  /* Source breakdown donut — imported records per source. */
  const sourceDonut = useMemo<DonutDatum[]>(
    () =>
      (sources.data ?? [])
        .map((src: SourcePerformance) => ({
          label: sourceLabel(src.source_name),
          value: src.records_imported,
          color: POSTURE_COLOR[src.compliance_posture],
        }))
        .filter((d) => d.value > 0),
    [sources.data],
  );

  /* Validation rejection breakdown donut. */
  const rejectionDonut = useMemo<DonutDatum[]>(() => {
    const r = s?.validation_rejection_reasons;
    if (!r) return [];
    const rows: DonutDatum[] = [
      { label: "Syntax", value: r.syntax, color: CHART.danger },
      { label: "Disposable", value: r.disposable, color: CHART.warn },
      { label: "Role-based", value: r.role_based, color: CHART.review },
      { label: "MX", value: r.mx, color: CHART.info },
      { label: "LLM", value: r.llm, color: CHART.accent },
      { label: "Provider", value: r.provider, color: CHART.muted },
    ];
    return rows.filter((d) => d.value > 0);
  }, [s]);

  const queueEntries = useMemo(
    () => Object.entries(queues.data?.queues ?? {}),
    [queues.data],
  );

  const metricsLoading = summary.isLoading;

  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-5 p-4 sm:p-6">
      {/* ── Header ───────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <MicroLabel className="text-accent/80">Overview</MicroLabel>
          <h1 className="text-xl font-semibold text-ink">Command Center</h1>
          <p className="text-sm text-muted">
            Live mining, validation, and outreach across your tenant.
          </p>
        </div>
        <Button asChild size="sm">
          <Link href="/jobs/new">
            <Plus className="size-4" />
            New Mining Job
          </Link>
        </Button>
      </div>

      {/* ── Top metrics strip ────────────────────────────────────────── */}
      <Panel>
        <PanelTitle icon={Gauge} kicker="Pipeline" title="Headline Metrics" />
        {metricsLoading ? (
          <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
            {Array.from({ length: 12 }).map((_, i) => (
              <div key={i} className="flex flex-col gap-2">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-7 w-20" />
              </div>
            ))}
          </div>
        ) : s ? (
          <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
            <MetricCard label="Companies" value={formatNumber(s.companies_mined)} />
            <MetricCard label="Contacts" value={formatNumber(s.contacts_found)} />
            <MetricCard label="Emails Found" value={formatNumber(s.emails_found)} />
            <MetricCard
              label="Verified"
              value={formatNumber(s.verified_emails)}
            />
            <MetricCard label="In Review" value={formatNumber(s.review_emails)} />
            <MetricCard label="Invalid" value={formatNumber(s.invalid_emails)} />
            <MetricCard
              label="Sales-Ready"
              value={formatNumber(s.sales_ready_leads)}
            />
            <MetricCard label="Emails Sent" value={formatNumber(s.emails_sent)} />
            <MetricCard label="Delivered" value={formatNumber(s.delivered)} />
            <MetricCard label="Open Rate" value={formatPercent(s.open_rate)} />
            <MetricCard label="Click Rate" value={formatPercent(s.click_rate)} />
            <MetricCard label="Reply Rate" value={formatPercent(s.reply_rate)} />
            <MetricCard
              label="Bounce Rate"
              value={formatPercent(s.bounce_rate)}
            />
            <MetricCard
              label="API Requests"
              value={formatNumber(s.api_requests)}
            />
            <MetricCard
              label="Est. Cost"
              value={formatCurrency(s.estimated_api_cost_usd)}
            />
            <MetricCard
              label="Active Jobs"
              value={formatNumber(s.active_jobs)}
              hint={s.failed_jobs > 0 ? `${s.failed_jobs} failed` : undefined}
            />
          </div>
        ) : (
          <EmptyState
            compact
            icon={Gauge}
            title="Metrics not available yet"
            description="The dashboard summary endpoint isn't reachable. It will populate once the backend is live."
          />
        )}
      </Panel>

      {/* ── Funnel + Active jobs ──────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel>
          <PanelTitle icon={Layers} kicker="Live Funnel" title="Mine → Verify → Send" />
          {funnel.isLoading ? (
            <Skeleton className="h-[260px] w-full" />
          ) : funnelData.length ? (
            <FunnelChartWrapper data={funnelData} height={260} />
          ) : (
            <EmptyState
              compact
              icon={Layers}
              title="No funnel data yet"
              description="Run a mining job to populate the pipeline funnel."
            />
          )}
        </Panel>

        <Panel flush>
          <div className="p-4 sm:p-5">
            <PanelTitle
              icon={Activity}
              kicker="In Flight"
              title="Active Jobs"
              actions={
                <Link
                  href="/jobs"
                  className="font-mono text-[11px] uppercase tracking-wider text-muted hover:text-accent"
                >
                  All jobs
                </Link>
              }
            />
          </div>
          {jobsQ.isLoading || activeJobs.length > 0 ? (
            <DataTable
              columns={jobColumns}
              data={activeJobs}
              loading={jobsQ.isLoading}
              getRowId={(r) => r.id}
              skeletonRows={3}
            />
          ) : (
            <EmptyState
              compact
              icon={Activity}
              title="No active jobs"
              description="Queued and running jobs appear here with live progress."
              action={
                <Button asChild size="sm" variant="secondary">
                  <Link href="/jobs/new">Start a job</Link>
                </Button>
              }
            />
          )}
        </Panel>
      </div>

      {/* ── Campaign performance ──────────────────────────────────────── */}
      <Panel>
        <PanelTitle
          icon={Target}
          kicker="Outreach"
          title="Campaign Performance"
          actions={
            <Link
              href="/campaigns"
              className="font-mono text-[11px] uppercase tracking-wider text-muted hover:text-accent"
            >
              Campaigns
            </Link>
          }
        />
        {campaigns.isLoading ? (
          <Skeleton className="h-[260px] w-full" />
        ) : campaignRows.length ? (
          <BarsChart
            data={campaignRows}
            categoryKey="name"
            height={280}
            series={[
              { key: "Sent", label: "Sent", color: CHART.muted },
              { key: "Delivered", label: "Delivered", color: CHART.accent },
              { key: "Opened", label: "Opened", color: CHART.info },
              { key: "Clicked", label: "Clicked", color: CHART.review },
              { key: "Replied", label: "Replied", color: CHART.accent2 },
              { key: "Bounced", label: "Bounced", color: CHART.danger },
            ]}
          />
        ) : (
          <EmptyState
            compact
            icon={Target}
            title="No campaign data yet"
            description="Launch a campaign to see sent, delivered, open, click, reply and bounce rates here."
          />
        )}
      </Panel>

      {/* ── Source + Validation breakdowns ────────────────────────────── */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel>
          <PanelTitle icon={BarChart3} kicker="Sources" title="Source Breakdown" />
          {sources.isLoading ? (
            <Skeleton className="h-[240px] w-full" />
          ) : sourceDonut.length ? (
            <DonutChart
              data={sourceDonut}
              centerLabel="Imported"
              height={220}
            />
          ) : (
            <EmptyState
              compact
              icon={BarChart3}
              title="No source data yet"
              description="Records imported per source appear here after a run."
            />
          )}
        </Panel>

        <Panel>
          <PanelTitle
            icon={ShieldCheck}
            kicker="Validation"
            title="Rejection Breakdown"
          />
          {summary.isLoading ? (
            <Skeleton className="h-[240px] w-full" />
          ) : rejectionDonut.length ? (
            <DonutChart
              data={rejectionDonut}
              centerLabel="Rejected"
              height={220}
            />
          ) : (
            <EmptyState
              compact
              icon={ShieldCheck}
              title="No rejections"
              description="Validation rejection reasons (syntax, disposable, role, MX, LLM, provider) will break down here."
            />
          )}
        </Panel>
      </div>

      {/* ── Map preview + Source performance ──────────────────────────── */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel>
          <PanelTitle
            icon={MapPin}
            kicker="Geography"
            title="Mining Map"
            actions={
              newestJob ? (
                <Link
                  href={`/jobs/${newestJob.id}/results`}
                  className="font-mono text-[11px] uppercase tracking-wider text-muted hover:text-accent"
                >
                  Open results
                </Link>
              ) : undefined
            }
          />
          {HAS_MAPS ? (
            companyMap.isLoading ? (
              <Skeleton className="h-[300px] w-full" />
            ) : (
              <DashboardMap
                apiKey={MAPS_KEY}
                companies={mapCompanies}
                height={300}
              />
            )
          ) : (
            <div className="flex h-[300px] flex-col items-center justify-center gap-3 rounded-[12px] border border-dashed border-border bg-[var(--color-surface-1)] text-center">
              <MapPin className="size-6 text-muted" />
              <div className="flex flex-col gap-1">
                <p className="text-sm text-ink">Map preview unavailable</p>
                <p className="max-w-xs text-xs text-muted">
                  Set{" "}
                  <code className="font-mono text-[11px] text-muted">
                    NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY
                  </code>{" "}
                  to render clustered company markers.
                </p>
              </div>
              {newestJob && (
                <Button asChild size="sm" variant="secondary">
                  <Link href={`/jobs/${newestJob.id}/results`}>
                    View newest results
                    <ExternalLink className="size-3.5" />
                  </Link>
                </Button>
              )}
            </div>
          )}
        </Panel>

        <Panel>
          <PanelTitle
            icon={Database}
            kicker="Sources"
            title="Source Health"
          />
          {sources.isLoading ? (
            <div className="flex flex-col gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (sources.data ?? []).length ? (
            <ul className="flex flex-col divide-y divide-border">
              {(sources.data ?? []).map((src) => {
                const total = src.records_found || 1;
                const importRate = (src.records_imported / total) * 100;
                return (
                  <li
                    key={src.source_name}
                    className="flex flex-col gap-1.5 py-2.5 first:pt-0 last:pb-0"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="flex items-center gap-2 text-sm text-ink">
                        <span
                          className="inline-block size-2 rounded-full"
                          style={{
                            backgroundColor:
                              POSTURE_COLOR[src.compliance_posture] ??
                              CHART.muted,
                          }}
                        />
                        {sourceLabel(src.source_name)}
                      </span>
                      <span className="font-mono text-xs tabular-nums text-muted">
                        {formatNumber(src.records_imported)}/
                        {formatNumber(src.records_found)}
                      </span>
                    </div>
                    <ProgressBar
                      value={importRate}
                      variant={src.failed_runs > 0 ? "warn" : "accent"}
                    />
                    <div className="flex items-center gap-3">
                      <MicroLabel>{src.runs} runs</MicroLabel>
                      {src.failed_runs > 0 && (
                        <MicroLabel className="text-danger/90">
                          {src.failed_runs} failed
                        </MicroLabel>
                      )}
                      {src.skipped_runs > 0 && (
                        <MicroLabel className="text-warn/90">
                          {src.skipped_runs} skipped
                        </MicroLabel>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState
              compact
              icon={Database}
              title="No source runs yet"
              description="Per-source run health appears here after mining."
            />
          )}
        </Panel>
      </div>

      {/* ── Queue health + Sheets sync ────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel>
          <PanelTitle
            icon={Layers}
            kicker="Workers"
            title="Queue Health"
            actions={
              queues.data ? (
                <StatusChip
                  variant={queues.data.total_pending > 0 ? "info" : "muted"}
                  label={`${formatNumber(queues.data.total_pending)} pending`}
                />
              ) : undefined
            }
          />
          {queues.isLoading ? (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {Array.from({ length: 12 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : queueEntries.length ? (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {queueEntries.map(([name, depth]) => (
                <div
                  key={name}
                  className="flex flex-col gap-1 rounded-[10px] border border-border bg-[var(--color-surface-1)] px-3 py-2"
                >
                  <MicroLabel className="truncate">
                    {QUEUE_LABELS[name] ?? name}
                  </MicroLabel>
                  <span
                    className="font-mono text-lg font-semibold tabular-nums"
                    style={{
                      color: depth > 0 ? CHART.info : CHART.muted,
                    }}
                  >
                    {formatNumber(depth)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              compact
              icon={Layers}
              title="Queue health unavailable"
              description="Per-queue depth for the 12 Celery queues appears here."
            />
          )}
        </Panel>

        <Panel>
          <PanelTitle
            icon={Sheet}
            kicker="Sync"
            title="Google Sheets"
            actions={
              sheets.data ? (
                <StatusChip
                  status={sheets.data.connected ? "connected" : "draft"}
                  label={sheets.data.connected ? "Connected" : "Not connected"}
                />
              ) : undefined
            }
          />
          {sheets.isLoading ? (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : sheets.data ? (
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-3 gap-3">
                <MetricCard
                  label="Last Sync"
                  value={
                    <span className="text-base">
                      {sheets.data.last_synced_at
                        ? formatRelative(sheets.data.last_synced_at)
                        : "Never"}
                    </span>
                  }
                />
                <MetricCard
                  label="Pending"
                  value={formatNumber(sheets.data.pending_rows)}
                />
                <MetricCard
                  label="Failed"
                  value={formatNumber(sheets.data.failed_rows)}
                />
              </div>
              <Panel.Section divided>
                <MicroLabel className="mb-2 block">Tabs</MicroLabel>
                <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
                  {Object.entries(sheets.data.tabs).map(([tab, count]) => (
                    <div
                      key={tab}
                      className="flex items-center justify-between gap-3 text-xs"
                    >
                      <span className="truncate text-muted">
                        {tab.replace(/_/g, " ")}
                      </span>
                      <span className="font-mono tabular-nums text-ink">
                        {formatNumber(count)}
                      </span>
                    </div>
                  ))}
                </div>
              </Panel.Section>
            </div>
          ) : (
            <EmptyState
              compact
              icon={Sheet}
              title="Sheets sync unavailable"
              description="Connect Google Sheets to mirror leads into a live spreadsheet."
            />
          )}
        </Panel>
      </div>
    </div>
  );
}
