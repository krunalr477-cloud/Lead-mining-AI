"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Send, Plus, Search } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Panel,
  Toolbar,
  DataTable,
  EmptyState,
  StatusChip,
  Input,
  Select,
  Button,
} from "@/components/ui";
import { useCampaigns } from "@/lib/api/hooks";
import type { Campaign } from "@/lib/api/schema";
import { formatNumber, formatPercent, truncate } from "@/lib/format";

/**
 * §13 Campaign list. A DataTable of every outreach campaign with headline send
 * metrics and a status chip. "New Campaign" launches the two-pane builder. The
 * endpoint may 404 while the backend is being built — the table degrades to an
 * EmptyState rather than crashing (useCampaigns returns [] on 404).
 */

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "scheduled", label: "Scheduled" },
  { value: "queued", label: "Queued" },
  { value: "sending", label: "Sending" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

/** Rate metric cell — a percent under the raw count. */
function RateCell({ count, rate }: { count: number; rate?: number }) {
  return (
    <span className="flex flex-col leading-tight">
      <span className="font-mono text-sm tabular-nums text-ink">
        {formatNumber(count)}
      </span>
      {typeof rate === "number" && (
        <span className="font-mono text-[10px] tabular-nums text-muted">
          {formatPercent(rate, { fromRatio: rate <= 1 })}
        </span>
      )}
    </span>
  );
}

export default function CampaignsPage() {
  const router = useRouter();
  const { data: campaigns, isLoading } = useCampaigns();

  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (campaigns ?? []).filter((c) => {
      if (status && c.status !== status) return false;
      if (q) {
        const hay = [c.name, c.from_account ?? "", c.job_name ?? "", c.id]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [campaigns, search, status]);

  const columns = useMemo<ColumnDef<Campaign, unknown>[]>(
    () => [
      {
        id: "name",
        header: "Campaign",
        accessorFn: (r) => r.name,
        cell: ({ row }) => (
          <span className="flex flex-col leading-tight">
            <span className="font-medium text-ink">{row.original.name}</span>
            <span className="font-mono text-[10px] text-muted">
              {row.original.id.slice(0, 8)}
            </span>
          </span>
        ),
      },
      {
        id: "job",
        header: "Audience",
        accessorFn: (r) => r.job_name ?? r.job_id,
        cell: ({ row }) => (
          <span className="text-sm text-muted">
            {truncate(row.original.job_name ?? row.original.job_id ?? "—", 24)}
          </span>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "from",
        header: "From",
        accessorFn: (r) => r.from_account,
        cell: ({ row }) => (
          <span className="font-mono text-[11px] text-muted">
            {truncate(row.original.from_account ?? "—", 22)}
          </span>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "recipients",
        header: "Recipients",
        accessorFn: (r) => r.stats.recipients,
        cell: ({ row }) => (
          <span className="font-mono text-sm tabular-nums text-ink">
            {formatNumber(row.original.stats.recipients)}
          </span>
        ),
        meta: { align: "right", mobilePriority: "medium" },
      },
      {
        id: "sent",
        header: "Sent",
        accessorFn: (r) => r.stats.sent,
        cell: ({ row }) => (
          <span className="font-mono text-sm tabular-nums text-ink">
            {formatNumber(row.original.stats.sent)}
          </span>
        ),
        meta: { align: "right", mobilePriority: "medium" },
      },
      {
        id: "delivered",
        header: "Delivered",
        accessorFn: (r) => r.stats.delivered,
        cell: ({ row }) => (
          <span className="font-mono text-sm tabular-nums text-ink">
            {formatNumber(row.original.stats.delivered)}
          </span>
        ),
        meta: { align: "right", mobilePriority: "low" },
      },
      {
        id: "open",
        header: "Open",
        accessorFn: (r) => r.stats.opened,
        cell: ({ row }) => (
          <RateCell count={row.original.stats.opened} rate={row.original.stats.open_rate} />
        ),
        meta: { align: "right", mobilePriority: "low" },
      },
      {
        id: "click",
        header: "Click",
        accessorFn: (r) => r.stats.clicked,
        cell: ({ row }) => (
          <RateCell count={row.original.stats.clicked} rate={row.original.stats.click_rate} />
        ),
        meta: { align: "right", mobilePriority: "low" },
      },
      {
        id: "reply",
        header: "Reply",
        accessorFn: (r) => r.stats.replied,
        cell: ({ row }) => (
          <RateCell count={row.original.stats.replied} rate={row.original.stats.reply_rate} />
        ),
        meta: { align: "right", mobilePriority: "low" },
      },
      {
        id: "bounce",
        header: "Bounce",
        accessorFn: (r) => r.stats.bounced,
        cell: ({ row }) => (
          <RateCell count={row.original.stats.bounced} rate={row.original.stats.bounce_rate} />
        ),
        meta: { align: "right", mobilePriority: "low" },
      },
      {
        id: "status",
        header: "Status",
        accessorFn: (r) => r.status,
        cell: ({ row }) => <StatusChip status={row.original.status} />,
        meta: { align: "right" },
      },
    ],
    [],
  );

  return (
    <div className="flex flex-col gap-4">
      <Toolbar
        actions={
          <Button asChild>
            <Link href="/campaigns/new">
              <Plus className="size-4" />
              New Campaign
            </Link>
          </Button>
        }
      >
        <Input
          leading={<Search className="size-4" />}
          placeholder="Search campaigns…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full sm:w-64"
        />
        <Select
          options={STATUS_OPTIONS}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="w-full sm:w-44"
        />
      </Toolbar>

      <Panel flush>
        <DataTable
          columns={columns}
          data={rows}
          loading={isLoading}
          getRowId={(r) => r.id}
          onRowClick={(r) => router.push(`/campaigns/${r.id}`)}
          emptyState={
            <EmptyState
              icon={Send}
              kicker="No campaigns yet"
              title="Build your first outreach campaign"
              description="Target verified contacts from a mining job, compose a templated email, and launch with rate limits and tracking."
              action={
                <Button asChild>
                  <Link href="/campaigns/new">
                    <Plus className="size-4" />
                    New Campaign
                  </Link>
                </Button>
              }
            />
          }
        />
      </Panel>
    </div>
  );
}
