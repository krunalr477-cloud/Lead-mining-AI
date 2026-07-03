"use client";

import { useMemo } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  RefreshCw,
  Sheet,
  Table2,
} from "lucide-react";
import { Panel, PanelHeader, PanelSection } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { MetricCard } from "@/components/ui/MetricCard";
import { StatusChip } from "@/components/ui/StatusChip";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { CopyButton } from "@/components/ui/CopyButton";
import { useToast } from "@/components/ui/Toast";
import {
  useSheetsStatus,
  useSyncSheets,
  useConnectSheets,
} from "@/lib/api/hooks";
import { useDemoMode } from "@/lib/demo";
import { useSession } from "@/lib/auth/session";
import { formatNumber, formatRelative } from "@/lib/format";

/** The canonical tabs (spec §20 Sheets), used to order the grid. */
const TAB_ORDER = [
  "Mining_Jobs",
  "Companies",
  "Contacts",
  "Email_Validation",
  "Sales_Ready_Leads",
  "Outreach_Queue",
  "Campaigns",
  "Bounce_Log",
  "Suppression_List",
  "Data_Source_Audit",
  "Audit_Log",
];

function orderedTabs(tabs: Record<string, number>): [string, number][] {
  const known = TAB_ORDER.filter((t) => t in tabs).map(
    (t) => [t, tabs[t]] as [string, number],
  );
  const extra = Object.entries(tabs).filter(([t]) => !TAB_ORDER.includes(t));
  return [...known, ...extra];
}

export default function SheetsPage() {
  const { data, isLoading } = useSheetsStatus();
  const sync = useSyncSheets();
  const connect = useConnectSheets();
  const { demoMode, providers } = useDemoMode();
  const { can } = useSession();
  const { toast } = useToast();

  const canSync = can("sheets.sync");
  const isMock = providers.sheets !== "live";

  const tabs = useMemo(
    () => (data?.tabs ? orderedTabs(data.tabs) : []),
    [data],
  );

  const sheetUrl =
    data?.spreadsheet_id && !isMock
      ? `https://docs.google.com/spreadsheets/d/${data.spreadsheet_id}`
      : null;

  async function handleSync() {
    try {
      await sync.mutateAsync();
      toast({
        tone: "success",
        title: "Sync started",
        description: "Pending rows are being pushed to the sheet.",
      });
    } catch (e) {
      toast({ tone: "error", title: "Sync failed", description: (e as Error).message });
    }
  }

  async function handleConnect() {
    try {
      await connect.mutateAsync();
      toast({ tone: "success", title: "Spreadsheet connected" });
    } catch (e) {
      toast({ tone: "error", title: "Connect failed", description: (e as Error).message });
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <MicroLabel className="text-accent/70">Mine</MicroLabel>
          <h1 className="text-lg font-semibold text-ink">Google Sheets Sync</h1>
          <p className="text-sm text-muted">
            Sales-facing system of record — per-tab status, last sync, and failed-row recovery.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {sheetUrl ? (
            <Button asChild size="sm" variant="secondary">
              <a href={sheetUrl} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="size-4" /> Open Google Sheet
              </a>
            </Button>
          ) : null}
          {data?.connected && canSync ? (
            <Button size="sm" onClick={handleSync} disabled={sync.isPending}>
              <RefreshCw className={`size-4 ${sync.isPending ? "animate-spin" : ""}`} />
              Sync now
            </Button>
          ) : null}
        </div>
      </div>

      {isLoading ? (
        <Panel>
          <Skeleton className="h-24 w-full" />
        </Panel>
      ) : !data || !data.connected ? (
        <Panel>
          <EmptyState
            icon={Sheet}
            kicker="Not connected"
            title="No spreadsheet connected"
            description="Connect the tenant Google Spreadsheet to mirror mining jobs, companies, contacts, validation, sales-ready leads, and outreach into a live sales-facing workbook."
            action={
              canSync ? (
                <Button size="sm" onClick={handleConnect} disabled={connect.isPending}>
                  {connect.isPending ? "Connecting…" : "Connect spreadsheet"}
                </Button>
              ) : (
                <span className="text-xs text-muted">
                  Admin or Sales Manager required to connect.
                </span>
              )
            }
          />
        </Panel>
      ) : (
        <>
          {/* Connected spreadsheet + sync counters */}
          <Panel>
            <PanelHeader
              actions={
                <StatusChip
                  status={isMock ? "connected" : "live"}
                  label={isMock ? (demoMode ? "Demo mirror" : "Mock") : "Live"}
                />
              }
            >
              <MicroLabel className="text-accent/70">Connected spreadsheet</MicroLabel>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <code className="rounded-[6px] bg-panel-strong px-2 py-1 font-mono text-xs text-ink">
                  {data.spreadsheet_id ?? "—"}
                </code>
                {data.spreadsheet_id ? (
                  <CopyButton value={data.spreadsheet_id} label="Copy ID" />
                ) : null}
              </div>
            </PanelHeader>

            <PanelSection>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <MetricCard label="Total rows" value={formatNumber(data.row_count ?? 0)} />
                <MetricCard label="Tabs" value={formatNumber(tabs.length)} />
                <MetricCard
                  label="Pending rows"
                  value={formatNumber(data.pending_rows)}
                  hint={data.pending_rows > 0 ? "awaiting sync" : "all synced"}
                />
                <MetricCard
                  label="Failed rows"
                  value={formatNumber(data.failed_rows)}
                  hint={data.failed_rows > 0 ? "needs retry" : "none"}
                />
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
                <span className="flex items-center gap-2 text-muted">
                  <MicroLabel>Last synced</MicroLabel>
                  <span className="text-ink">
                    {data.last_synced_at ? formatRelative(data.last_synced_at) : "Never"}
                  </span>
                </span>
                {data.failed_rows > 0 && canSync ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={handleSync}
                    disabled={sync.isPending}
                  >
                    <RefreshCw className={`size-4 ${sync.isPending ? "animate-spin" : ""}`} />
                    Retry failed rows
                  </Button>
                ) : null}
              </div>
            </PanelSection>
          </Panel>

          {/* Per-tab grid */}
          <Panel>
            <PanelHeader>
              <MicroLabel className="text-accent/70">Tabs</MicroLabel>
              <h2 className="text-base font-semibold text-ink">Worksheet status</h2>
            </PanelHeader>
            <PanelSection>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {tabs.map(([name, count]) => (
                  <div
                    key={name}
                    className="flex items-center justify-between gap-3 rounded-[10px] border border-border bg-panel-strong px-3 py-2.5"
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <Table2 className="size-4 shrink-0 text-accent/70" />
                      <span className="truncate font-mono text-xs text-ink" title={name}>
                        {name}
                      </span>
                    </div>
                    <span className="shrink-0 font-mono text-sm tabular-nums text-muted">
                      {formatNumber(count)}
                    </span>
                  </div>
                ))}
              </div>
            </PanelSection>
          </Panel>

          {/* Sync health banner */}
          <Panel>
            <div className="flex items-start gap-3">
              {data.failed_rows > 0 ? (
                <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" />
              ) : (
                <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-accent" />
              )}
              <div className="text-sm">
                <p className="font-medium text-ink">
                  {data.failed_rows > 0
                    ? `${formatNumber(data.failed_rows)} row${data.failed_rows === 1 ? "" : "s"} failed to sync`
                    : "All rows in sync"}
                </p>
                <p className="text-muted">
                  {data.failed_rows > 0
                    ? "Use Retry failed rows to re-attempt. Failures are logged to the Audit_Log tab for review."
                    : demoMode
                      ? "Demo mirror reflects seeded data; no live Google write occurs in demo mode."
                      : "The spreadsheet mirrors the pipeline in near-real time."}
                </p>
              </div>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
