"use client";

import { useMemo } from "react";
import { ListChecks } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable, EmptyState, StatusChip, CopyButton } from "@/components/ui";
import type { OutreachQueueRow } from "@/lib/api/schema";
import { formatDateTime, truncate } from "@/lib/format";

interface OutreachQueueTableProps {
  rows: OutreachQueueRow[];
  loading?: boolean;
  /** Hide the company column (e.g. inside a single-campaign detail). */
  hideCompany?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
}

/** Boolean flag → small chip (present) or muted dash. */
function FlagChip({ on, label, variant }: { on: boolean; label: string; variant: "accent" | "danger" | "warn" }) {
  return on ? (
    <StatusChip variant={variant} label={label} />
  ) : (
    <span className="text-muted/40">—</span>
  );
}

/**
 * Shared outreach-queue DataTable used by the Outreach Queue screen and the
 * campaign-detail Recipients tab. One row per email message.
 */
export function OutreachQueueTable({
  rows,
  loading,
  hideCompany,
  emptyTitle = "No queued messages",
  emptyDescription = "Once a campaign launches, each recipient's message appears here with its send status and Gmail message ID.",
}: OutreachQueueTableProps) {
  const columns = useMemo<ColumnDef<OutreachQueueRow, unknown>[]>(() => {
    const cols: ColumnDef<OutreachQueueRow, unknown>[] = [
      {
        id: "contact",
        header: "Contact",
        accessorFn: (r) => r.contact_name ?? r.email,
        cell: ({ row }) => (
          <span className="flex flex-col leading-tight">
            <span className="text-sm text-ink">{row.original.contact_name ?? "—"}</span>
            <span className="font-mono text-[11px] text-muted">{row.original.email}</span>
          </span>
        ),
      },
    ];

    if (!hideCompany) {
      cols.push({
        id: "company",
        header: "Company",
        accessorFn: (r) => r.company,
        cell: ({ row }) => (
          <span className="text-sm text-muted">{truncate(row.original.company ?? "—", 24)}</span>
        ),
        meta: { mobilePriority: "low" },
      });
    }

    cols.push(
      {
        id: "subject",
        header: "Subject",
        accessorFn: (r) => r.subject,
        cell: ({ row }) => (
          <span className="text-sm text-muted">{truncate(row.original.subject, 36)}</span>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "send_status",
        header: "Status",
        accessorFn: (r) => r.send_status,
        cell: ({ row }) => <StatusChip status={row.original.send_status} />,
      },
      {
        id: "scheduled_at",
        header: "Scheduled",
        accessorFn: (r) => r.scheduled_at,
        cell: ({ row }) => (
          <span className="font-mono text-[11px] text-muted">
            {row.original.scheduled_at ? formatDateTime(row.original.scheduled_at) : "—"}
          </span>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "sent_at",
        header: "Sent",
        accessorFn: (r) => r.sent_at,
        cell: ({ row }) => (
          <span className="font-mono text-[11px] text-muted">
            {row.original.sent_at ? formatDateTime(row.original.sent_at) : "—"}
          </span>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "gmail_message_id",
        header: "Gmail ID",
        accessorFn: (r) => r.gmail_message_id,
        cell: ({ row }) =>
          row.original.gmail_message_id ? (
            <span className="inline-flex items-center gap-1">
              <span className="font-mono text-[11px] text-muted">
                {row.original.gmail_message_id.slice(0, 12)}
              </span>
              <CopyButton value={row.original.gmail_message_id} />
            </span>
          ) : (
            <span className="text-muted/40">—</span>
          ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "signals",
        header: "Signals",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-wrap items-center gap-1">
            <FlagChip on={row.original.opened} label="Opened" variant="accent" />
            <FlagChip on={row.original.replied} label="Replied" variant="accent" />
            <FlagChip on={row.original.bounced} label="Bounced" variant="danger" />
            <FlagChip on={row.original.suppressed} label="Suppressed" variant="warn" />
          </div>
        ),
        meta: { mobilePriority: "medium" },
      },
    );

    return cols;
  }, [hideCompany]);

  return (
    <DataTable
      columns={columns}
      data={rows}
      loading={loading}
      getRowId={(r) => r.queue_id}
      emptyState={
        <EmptyState
          icon={ListChecks}
          kicker="Empty queue"
          title={emptyTitle}
          description={emptyDescription}
        />
      }
    />
  );
}
