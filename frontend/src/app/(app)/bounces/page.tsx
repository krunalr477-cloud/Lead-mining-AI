"use client";

import { useMemo, useState } from "react";
import { Inbox, RefreshCw, Search, ShieldBan, ShieldCheck } from "lucide-react";
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
  MicroLabel,
  useToast,
} from "@/components/ui";
import {
  useBounces,
  usePollBounces,
  useSuppressions,
  useCampaigns,
} from "@/lib/api/hooks";
import type { BounceRow, Suppression } from "@/lib/api/schema";
import { formatDateTime, formatNumber, truncate } from "@/lib/format";
import { resolveStatus } from "@/lib/status";

/**
 * §14 / §20 Bounce & Reply Monitor. A DataTable of bounces + replies detected by
 * inbox polling — email, campaign, SMTP status code, bounce classification,
 * reason, detected time — with per-row suppress/unsuppress actions and a
 * "Poll now" trigger. Suppression state is joined from /suppressions so contact
 * status updates are reflected. Degrades gracefully on 404.
 */

const TYPE_OPTIONS = [
  { value: "", label: "All events" },
  { value: "bounce", label: "Bounces" },
  { value: "reply", label: "Replies" },
];

/** Map an event/bounce type to a StatusChip. */
function EventChip({ row }: { row: BounceRow }) {
  if (row.event_type === "reply") return <StatusChip variant="accent" label="Reply" />;
  const meta = resolveStatus(row.bounce_type ?? "unknown");
  return <StatusChip variant={meta.variant} label={meta.label} />;
}

export default function BouncesPage() {
  const toast = useToast();
  const [campaignId, setCampaignId] = useState("");
  const [eventType, setEventType] = useState("");
  const [search, setSearch] = useState("");

  const { data: bounces, isLoading } = useBounces({
    campaign_id: campaignId || undefined,
    event_type: (eventType || undefined) as "bounce" | "reply" | undefined,
  });
  const { data: campaigns } = useCampaigns();
  const { suppressions, suppress, unsuppress } = useSuppressions();
  const poll = usePollBounces();

  // Suppression lookup by lowercased email so we reflect current contact status
  // even when the bounce row's own `suppressed` flag is stale.
  const suppressedByEmail = useMemo(() => {
    const map = new Map<string, Suppression>();
    for (const s of suppressions) map.set(s.email.toLowerCase(), s);
    return map;
  }, [suppressions]);

  const campaignOptions = useMemo(
    () => [
      { value: "", label: "All campaigns" },
      ...(campaigns ?? []).map((c) => ({ value: c.id, label: c.name })),
    ],
    [campaigns],
  );

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return bounces ?? [];
    return (bounces ?? []).filter((r) =>
      [r.email, r.campaign_name ?? "", r.reason ?? "", r.smtp_status_code ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [bounces, search]);

  function isSuppressed(r: BounceRow) {
    return r.suppressed || suppressedByEmail.has(r.email.toLowerCase());
  }

  async function handleSuppress(r: BounceRow) {
    try {
      await suppress.mutateAsync({
        email: r.email,
        reason: r.reason ?? `${r.bounce_type ?? r.event_type} via bounce monitor`,
      });
      toast.success("Email suppressed", `${r.email} will not receive further sends.`);
    } catch (e) {
      toast.error("Could not suppress", e instanceof Error ? e.message : undefined);
    }
  }

  async function handleUnsuppress(r: BounceRow) {
    const s = suppressedByEmail.get(r.email.toLowerCase());
    if (!s) return;
    try {
      await unsuppress.mutateAsync(s.id);
      toast.success("Suppression removed", `${r.email} may be contacted again.`);
    } catch (e) {
      toast.error("Could not unsuppress", e instanceof Error ? e.message : undefined);
    }
  }

  const columns = useMemo<ColumnDef<BounceRow, unknown>[]>(
    () => [
      {
        id: "email",
        header: "Email",
        accessorFn: (r) => r.email,
        cell: ({ row }) => (
          <span className="flex flex-col leading-tight">
            <span className="font-mono text-[12px] text-ink">{row.original.email}</span>
            {isSuppressed(row.original) && (
              <span className="font-mono text-[10px] uppercase tracking-wider text-danger">
                Suppressed
              </span>
            )}
          </span>
        ),
      },
      {
        id: "campaign",
        header: "Campaign",
        accessorFn: (r) => r.campaign_name,
        cell: ({ row }) => (
          <span className="text-sm text-muted">
            {truncate(row.original.campaign_name ?? "—", 22)}
          </span>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "type",
        header: "Type",
        accessorFn: (r) => r.bounce_type ?? r.event_type,
        cell: ({ row }) => <EventChip row={row.original} />,
      },
      {
        id: "smtp",
        header: "SMTP",
        accessorFn: (r) => r.smtp_status_code,
        cell: ({ row }) => (
          <span className="font-mono text-[12px] text-muted">
            {row.original.smtp_status_code ?? "—"}
          </span>
        ),
        meta: { align: "right", mobilePriority: "medium" },
      },
      {
        id: "reason",
        header: "Reason",
        accessorFn: (r) => r.reason,
        cell: ({ row }) => (
          <span className="text-sm text-muted">{truncate(row.original.reason ?? "—", 40)}</span>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "detected",
        header: "Detected",
        accessorFn: (r) => r.detected_at,
        cell: ({ row }) => (
          <span className="font-mono text-[11px] text-muted">
            {formatDateTime(row.original.detected_at)}
          </span>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        id: "action",
        header: "Action",
        enableSorting: false,
        cell: ({ row }) =>
          isSuppressed(row.original) ? (
            <Button
              variant="ghost"
              size="sm"
              loading={unsuppress.isPending}
              onClick={() => handleUnsuppress(row.original)}
            >
              <ShieldCheck className="size-4" />
              Unsuppress
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              loading={suppress.isPending}
              onClick={() => handleSuppress(row.original)}
            >
              <ShieldBan className="size-4" />
              Suppress
            </Button>
          ),
        meta: { align: "right" },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [suppressedByEmail, suppress.isPending, unsuppress.isPending],
  );

  const bounceCount = (bounces ?? []).filter((b) => b.event_type === "bounce").length;
  const replyCount = (bounces ?? []).filter((b) => b.event_type === "reply").length;

  return (
    <div className="flex flex-col gap-4">
      <Toolbar
        actions={
          <Button
            variant="secondary"
            loading={poll.isPending}
            onClick={async () => {
              try {
                const res = await poll.mutateAsync();
                toast.success(
                  "Inbox polled",
                  `${formatNumber(res.detected)} new events (${formatNumber(res.bounces)} bounces, ${formatNumber(res.replies)} replies).`,
                );
              } catch (e) {
                toast.error("Poll failed", e instanceof Error ? e.message : undefined);
              }
            }}
          >
            <RefreshCw className="size-4" />
            Poll now
          </Button>
        }
      >
        <Input
          leading={<Search className="size-4" />}
          placeholder="Search email, reason, code…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full sm:w-64"
        />
        <Select
          options={campaignOptions}
          value={campaignId}
          onChange={(e) => setCampaignId(e.target.value)}
          className="w-full sm:w-52"
        />
        <Select
          options={TYPE_OPTIONS}
          value={eventType}
          onChange={(e) => setEventType(e.target.value)}
          className="w-full sm:w-40"
        />
      </Toolbar>

      <div className="flex flex-wrap items-center gap-4 rounded-[10px] border border-border bg-panel px-4 py-2.5">
        <div className="flex items-center gap-2">
          <MicroLabel>Bounces</MicroLabel>
          <span className="font-mono text-sm tabular-nums text-danger">{formatNumber(bounceCount)}</span>
        </div>
        <div className="h-4 w-px bg-border" />
        <div className="flex items-center gap-2">
          <MicroLabel>Replies</MicroLabel>
          <span className="font-mono text-sm tabular-nums text-accent">{formatNumber(replyCount)}</span>
        </div>
        <div className="h-4 w-px bg-border" />
        <div className="flex items-center gap-2">
          <MicroLabel>Suppressed</MicroLabel>
          <span className="font-mono text-sm tabular-nums text-muted">{formatNumber(suppressions.length)}</span>
        </div>
      </div>

      <Panel flush>
        <DataTable
          columns={columns}
          data={rows}
          loading={isLoading}
          getRowId={(r) => r.id}
          emptyState={
            <EmptyState
              icon={Inbox}
              kicker="All clear"
              title="No bounces or replies detected"
              description="Inbox polling surfaces delivery failures and replies here, with SMTP classification and one-click suppression. Use 'Poll now' to check immediately, or the bounces endpoint may not be available yet."
              action={
                <Button
                  variant="secondary"
                  loading={poll.isPending}
                  onClick={() => poll.mutate()}
                >
                  <RefreshCw className="size-4" />
                  Poll now
                </Button>
              }
            />
          }
        />
      </Panel>
    </div>
  );
}
