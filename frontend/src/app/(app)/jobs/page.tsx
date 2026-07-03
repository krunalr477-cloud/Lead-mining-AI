"use client";

import { useMemo, useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Radar, Search, Plus, AlertTriangle } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Panel,
  Toolbar,
  DataTable,
  EmptyState,
  StatusChip,
  ComplianceBadge,
  MicroLabel,
  Input,
  Select,
  Button,
  type CompliancePosture,
} from "@/components/ui";
import { useJobs } from "@/lib/api/hooks";
import type { JobListItem } from "@/lib/api/schema";
import { formatDate, formatNumber, truncate } from "@/lib/format";

/**
 * §16 Job History & Search — a searchable, auditable DataTable of every mining
 * run. Filters (company type, status, source, date range, created-by) run
 * client-side against the useJobs() list; the free-text search box is debounced
 * and matches name / job id / location / company type. Rows link to the Job Run
 * Monitor at /jobs/{id}.
 */

/** Map a selected_source string to a compliance posture for its mini badge. */
const SOURCE_POSTURE: Record<string, CompliancePosture> = {
  google_maps: "official",
  company_websites: "official",
  directories: "gated",
  facebook_signals: "gated",
  job_signals: "gated",
  linkedin: "disabled",
};

const SOURCE_LABEL: Record<string, string> = {
  google_maps: "Maps",
  company_websites: "Sites",
  directories: "Dir",
  facebook_signals: "FB",
  job_signals: "Jobs",
  linkedin: "LI",
};

function sourcePosture(source: string): CompliancePosture {
  return SOURCE_POSTURE[source] ?? "gated";
}

function useDebounced<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

const DATE_OPTIONS = [
  { value: "", label: "Any time" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
];

const DATE_WINDOW_MS: Record<string, number> = {
  "24h": 24 * 60 * 60 * 1000,
  "7d": 7 * 24 * 60 * 60 * 1000,
  "30d": 30 * 24 * 60 * 60 * 1000,
};

export default function JobHistoryPage() {
  const router = useRouter();
  const { data: jobs, isLoading } = useJobs();

  const [search, setSearch] = useState("");
  const [companyType, setCompanyType] = useState("");
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [dateRange, setDateRange] = useState("");
  const debouncedSearch = useDebounced(search, 250);

  // "now" is sourced from a slow interval (an external clock) rather than read
  // during render, so the date-range filter stays pure. Minute-level staleness
  // is irrelevant for day-scale ranges; the ticker only runs while a range is
  // selected.
  const [nowTs, setNowTs] = useState(0);
  useEffect(() => {
    if (!dateRange) return;
    const tick = () => setNowTs(Date.now());
    const seed = setTimeout(tick, 0);
    const id = setInterval(tick, 30_000);
    return () => {
      clearTimeout(seed);
      clearInterval(id);
    };
  }, [dateRange]);

  // Distinct filter option sets derived from the loaded jobs.
  const { typeOptions, sourceOptions } = useMemo(() => {
    const types = new Set<string>();
    const sources = new Set<string>();
    for (const j of jobs ?? []) {
      if (j.company_type) types.add(j.company_type);
      for (const s of j.selected_sources) sources.add(s);
    }
    return {
      typeOptions: [
        { value: "", label: "All types" },
        ...[...types].sort().map((t) => ({ value: t, label: t })),
      ],
      sourceOptions: [
        { value: "", label: "All sources" },
        ...[...sources]
          .sort()
          .map((s) => ({ value: s, label: SOURCE_LABEL[s] ?? s })),
      ],
    };
  }, [jobs]);

  const rows = useMemo(() => {
    const q = debouncedSearch.trim().toLowerCase();
    const window = DATE_WINDOW_MS[dateRange];

    return (jobs ?? []).filter((j) => {
      if (companyType && j.company_type !== companyType) return false;
      if (status && j.status !== status) return false;
      if (source && !j.selected_sources.includes(source)) return false;
      if (window && nowTs) {
        const t = Date.parse(j.created_at);
        if (Number.isFinite(t) && nowTs - t > window) return false;
      }
      if (q) {
        const hay = [
          j.name,
          j.id,
          j.company_type ?? "",
          j.city ?? "",
          j.state ?? "",
          j.country ?? "",
          j.created_by ?? "",
        ]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [jobs, debouncedSearch, companyType, status, source, dateRange, nowTs]);

  const columns = useMemo<ColumnDef<JobListItem, unknown>[]>(
    () => [
      {
        id: "id",
        header: "Job ID",
        accessorFn: (r) => r.id,
        cell: ({ row }) => (
          <span className="font-mono text-[11px] text-muted">
            {row.original.id.slice(0, 8)}
          </span>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "name",
        header: "Name",
        accessorFn: (r) => r.name,
        cell: ({ row }) => (
          <span className="font-medium text-ink">{row.original.name}</span>
        ),
        meta: { mobilePriority: "high", mono: false },
      },
      {
        id: "created_by",
        header: "Created by",
        accessorFn: (r) => r.created_by ?? "",
        cell: ({ row }) => (
          <span className="font-mono text-[11px] text-muted">
            {row.original.created_by
              ? row.original.created_by.slice(0, 8)
              : "—"}
          </span>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "date",
        header: "Date",
        accessorFn: (r) => Date.parse(r.created_at) || 0,
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-muted">
            {formatDate(row.original.created_at)}
          </span>
        ),
        meta: { mobilePriority: "medium" },
      },
      {
        id: "location",
        header: "Location",
        accessorFn: (r) => `${r.city ?? ""} ${r.state ?? ""}`,
        cell: ({ row }) => {
          const { city, state, country } = row.original;
          const parts = [city, state ?? country].filter(Boolean);
          return (
            <span className="whitespace-nowrap text-muted">
              {parts.length ? truncate(parts.join(", "), 28) : "—"}
            </span>
          );
        },
        meta: { mobilePriority: "low", mono: false },
      },
      {
        id: "sources",
        header: "Sources",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-wrap items-center gap-1">
            {row.original.selected_sources.slice(0, 4).map((s) => (
              <ComplianceBadge
                key={s}
                posture={sourcePosture(s)}
                note={`${SOURCE_LABEL[s] ?? s} — ${sourcePosture(s)} source`}
                className="!px-1.5 !text-[10px]"
              />
            ))}
          </div>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "status",
        header: "Status",
        accessorFn: (r) => r.status,
        cell: ({ row }) => <StatusChip status={row.original.status} />,
        meta: { mobilePriority: "high" },
      },
      {
        id: "companies",
        header: "Companies",
        accessorFn: (r) => r.totals_json.total_companies,
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-ink">
            {formatNumber(row.original.totals_json.total_companies)}
          </span>
        ),
        meta: { mobilePriority: "medium", align: "right" },
      },
      {
        id: "contacts",
        header: "Contacts",
        accessorFn: (r) => r.totals_json.total_contacts,
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-muted">
            {formatNumber(row.original.totals_json.total_contacts)}
          </span>
        ),
        meta: { mobilePriority: "low", align: "right" },
      },
      {
        id: "verified",
        header: "Verified",
        accessorFn: (r) => r.totals_json.verified_emails,
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-accent">
            {formatNumber(row.original.totals_json.verified_emails)}
          </span>
        ),
        meta: { mobilePriority: "low", align: "right" },
      },
      {
        id: "sales_ready",
        header: "Sales-ready",
        accessorFn: (r) => r.totals_json.sales_ready_count,
        cell: ({ row }) => (
          <span className="font-mono tabular-nums font-semibold text-accent">
            {formatNumber(row.original.totals_json.sales_ready_count)}
          </span>
        ),
        meta: { mobilePriority: "medium", align: "right" },
      },
      {
        id: "campaign",
        header: "Campaign",
        enableSorting: false,
        cell: () => <span className="text-muted">—</span>,
        meta: { mobilePriority: "low" },
      },
      {
        id: "duration",
        header: "Duration",
        enableSorting: false,
        cell: () => <span className="font-mono text-[11px] text-muted">—</span>,
        meta: { mobilePriority: "low", align: "right" },
      },
      {
        id: "errors",
        header: "Errors",
        accessorFn: (r) => r.status,
        cell: ({ row }) =>
          row.original.status === "failed" ? (
            <span className="inline-flex items-center gap-1 font-mono text-[11px] text-danger">
              <AlertTriangle className="size-3" /> Failed
            </span>
          ) : (
            <span className="text-muted">—</span>
          ),
        meta: { mobilePriority: "low", align: "right" },
      },
    ],
    [],
  );

  const hasAny = (jobs?.length ?? 0) > 0;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <MicroLabel className="text-accent/80">Mine</MicroLabel>
        <div className="flex items-center gap-2">
          <Radar className="size-5 text-muted" aria-hidden />
          <h1 className="text-xl font-semibold text-ink">Job History</h1>
        </div>
        <p className="text-sm text-muted">
          Every mining run — searchable and auditable.
        </p>
      </div>

      <Panel flush>
        <div className="p-4 sm:p-5">
          <Toolbar
            actions={
              <Button size="sm" asChild>
                <Link href="/jobs/new">
                  <Plus className="size-4" /> New Mining Job
                </Link>
              </Button>
            }
          >
            <div className="w-full min-w-[180px] max-w-xs flex-1">
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search name, ID, location…"
                leading={<Search className="size-4" />}
                aria-label="Search jobs"
              />
            </div>
            <Select
              options={typeOptions}
              value={companyType}
              onChange={(e) => setCompanyType(e.target.value)}
              aria-label="Company type"
              className="h-9 w-auto"
            />
            <Select
              options={STATUS_OPTIONS}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              aria-label="Status"
              className="h-9 w-auto"
            />
            <Select
              options={sourceOptions}
              value={source}
              onChange={(e) => setSource(e.target.value)}
              aria-label="Source"
              className="h-9 w-auto"
            />
            <Select
              options={DATE_OPTIONS}
              value={dateRange}
              onChange={(e) => setDateRange(e.target.value)}
              aria-label="Date range"
              className="h-9 w-auto"
            />
          </Toolbar>
        </div>

        <div className="border-t border-border">
          <DataTable<JobListItem>
            columns={columns}
            data={rows}
            loading={isLoading}
            getRowId={(r) => r.id}
            onRowClick={(r) => router.push(`/jobs/${r.id}`)}
            emptyState={
              hasAny ? (
                <EmptyState
                  compact
                  kicker="No matches"
                  title="No jobs match these filters"
                  description="Broaden the search text or clear a filter to see more runs."
                />
              ) : (
                <EmptyState
                  icon={Radar}
                  kicker="Mine"
                  title="No mining jobs yet"
                  description="Launch your first mining run to populate the searchable job history."
                  action={
                    <Button size="sm" asChild>
                      <Link href="/jobs/new">
                        <Plus className="size-4" /> New Mining Job
                      </Link>
                    </Button>
                  }
                />
              )
            }
          />
        </div>
      </Panel>
    </div>
  );
}
