"use client";

import { use, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Pause, Play, Ban, Send } from "lucide-react";
import {
  Panel,
  PanelHeader,
  MetricCard,
  StatusChip,
  Button,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  MicroLabel,
  ConfirmDialog,
  EmptyState,
  Skeleton,
  useToast,
} from "@/components/ui";
import { BarsChart } from "@/components/charts/stacked-bars";
import {
  useCampaign,
  useCampaignQueue,
  usePause,
  useResume,
  useCancel,
} from "@/lib/api/hooks";
import { formatNumber, formatPercent, formatDuration } from "@/lib/format";
import { OutreachQueueTable } from "@/components/outreach/OutreachQueueTable";
import { EligibilitySummary } from "@/components/outreach/EligibilitySummary";
import { UnsubscribeFooter } from "@/components/outreach/UnsubscribeFooter";

/**
 * §13 / §20 Campaign detail — tabbed Overview (stat cards + performance chart) /
 * Recipients (outreach queue) / Settings (read-only compose + eligibility) with
 * Pause/Resume/Cancel controls. Degrades gracefully when the endpoint 404s.
 */

const PERF_SERIES = [
  { key: "value", label: "Count" },
];

export default function CampaignDetailPage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const toast = useToast();

  const { data: campaign, isLoading } = useCampaign(campaignId);
  const { data: queue, isLoading: queueLoading } = useCampaignQueue(campaignId);

  const pause = usePause();
  const resume = useResume();
  const cancel = useCancel();
  const [cancelOpen, setCancelOpen] = useState(false);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!campaign) {
    return (
      <Panel>
        <EmptyState
          icon={Send}
          kicker="Not available"
          title="Campaign not found"
          description="This campaign could not be loaded — the campaigns API may not be available yet, or the campaign was removed."
          action={
            <Button asChild variant="secondary">
              <Link href="/campaigns">
                <ArrowLeft className="size-4" />
                Back to campaigns
              </Link>
            </Button>
          }
        />
      </Panel>
    );
  }

  const status = String(campaign.status);
  const canPause = ["sending", "queued", "scheduled"].includes(status);
  const canResume = status === "paused";
  const canCancel = !["completed", "cancelled", "failed"].includes(status);

  const s = campaign.stats;
  const perfData = [
    { label: "Sent", value: s.sent },
    { label: "Delivered", value: s.delivered },
    { label: "Opened", value: s.opened },
    { label: "Clicked", value: s.clicked },
    { label: "Replied", value: s.replied },
    { label: "Bounced", value: s.bounced },
  ];

  async function run(
    action: "pause" | "resume" | "cancel",
    fn: () => Promise<unknown>,
  ) {
    try {
      await fn();
      toast.success(`Campaign ${action}d`);
    } catch (e) {
      toast.error(`Could not ${action} campaign`, e instanceof Error ? e.message : undefined);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <Link
            href="/campaigns"
            className="inline-flex w-fit items-center gap-1 text-xs text-muted transition-colors hover:text-ink"
          >
            <ArrowLeft className="size-3.5" />
            Campaigns
          </Link>
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold text-ink">{campaign.name}</h1>
            <StatusChip status={campaign.status} />
          </div>
          <span className="font-mono text-[11px] text-muted">
            {campaign.from_account ?? "—"} · {campaign.id.slice(0, 8)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {canPause && (
            <Button
              variant="secondary"
              size="sm"
              loading={pause.isPending}
              onClick={() => run("pause", () => pause.mutateAsync(campaign.id))}
            >
              <Pause className="size-4" />
              Pause
            </Button>
          )}
          {canResume && (
            <Button
              size="sm"
              loading={resume.isPending}
              onClick={() => run("resume", () => resume.mutateAsync(campaign.id))}
            >
              <Play className="size-4" />
              Resume
            </Button>
          )}
          {canCancel && (
            <Button variant="danger" size="sm" onClick={() => setCancelOpen(true)}>
              <Ban className="size-4" />
              Cancel
            </Button>
          )}
        </div>
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="recipients">Recipients</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>

        {/* ── Overview ─────────────────────────────────────────────────── */}
        <TabsContent value="overview">
          <div className="flex flex-col gap-4">
            <Panel>
              <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
                <MetricCard label="Recipients" value={formatNumber(s.recipients)} />
                <MetricCard label="Sent" value={formatNumber(s.sent)} />
                <MetricCard label="Delivered" value={formatNumber(s.delivered)} />
                <MetricCard
                  label="Open rate"
                  value={formatPercent(s.open_rate ?? 0, { fromRatio: (s.open_rate ?? 0) <= 1 })}
                />
                <MetricCard
                  label="Reply rate"
                  value={formatPercent(s.reply_rate ?? 0, { fromRatio: (s.reply_rate ?? 0) <= 1 })}
                />
                <MetricCard
                  label="Bounce rate"
                  value={formatPercent(s.bounce_rate ?? 0, { fromRatio: (s.bounce_rate ?? 0) <= 1 })}
                  delta={{ value: "", direction: "flat", invert: true }}
                />
              </div>
            </Panel>

            <Panel>
              <PanelHeader>Performance</PanelHeader>
              <div className="mt-3">
                <BarsChart
                  data={perfData}
                  categoryKey="label"
                  series={PERF_SERIES}
                  height={280}
                  layout="horizontal"
                />
              </div>
            </Panel>

            {typeof campaign.estimated_completion_seconds === "number" &&
              campaign.estimated_completion_seconds > 0 && (
                <Panel>
                  <div className="flex items-center justify-between gap-3">
                    <MicroLabel>Estimated completion</MicroLabel>
                    <span className="font-mono text-sm text-ink">
                      ~{formatDuration(campaign.estimated_completion_seconds * 1000)}
                    </span>
                  </div>
                </Panel>
              )}
          </div>
        </TabsContent>

        {/* ── Recipients ───────────────────────────────────────────────── */}
        <TabsContent value="recipients">
          <Panel flush>
            <OutreachQueueTable
              rows={queue ?? []}
              loading={queueLoading}
              hideCompany={false}
              emptyTitle="No recipients queued yet"
              emptyDescription="This campaign has no per-message queue rows. Launch it to begin sending, or the queue endpoint may not be available yet."
            />
          </Panel>
        </TabsContent>

        {/* ── Settings (read-only) ─────────────────────────────────────── */}
        <TabsContent value="settings">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel className="flex flex-col gap-4">
              <PanelHeader>Message</PanelHeader>
              <div className="flex flex-col gap-1">
                <MicroLabel>Subject</MicroLabel>
                <p className="text-sm font-medium text-ink">{campaign.subject}</p>
              </div>
              <div className="flex flex-col gap-1">
                <MicroLabel>Body</MicroLabel>
                <pre className="whitespace-pre-wrap rounded-[8px] border border-border bg-[var(--color-surface-1)] p-3 font-mono text-[13px] leading-relaxed text-muted">
                  {campaign.body}
                </pre>
                <UnsubscribeFooter />
              </div>
              <div className="flex flex-wrap gap-2">
                <StatusChip
                  variant={campaign.ai_opener_enabled ? "review" : "muted"}
                  label={campaign.ai_opener_enabled ? "AI opener on" : "AI opener off"}
                />
                {campaign.tracking.opens && <StatusChip variant="info" label="Track opens" />}
                {campaign.tracking.clicks && <StatusChip variant="info" label="Track clicks" />}
                {campaign.tracking.replies && <StatusChip variant="info" label="Track replies" />}
                {campaign.tracking.bounces && <StatusChip variant="info" label="Track bounces" />}
              </div>
            </Panel>

            <div className="flex flex-col gap-4">
              <Panel className="flex flex-col gap-3">
                <PanelHeader>Rate limits</PanelHeader>
                <SettingRow label="Per hour" value={`${formatNumber(campaign.rate_limit.per_hour)}/h`} />
                <SettingRow label="Per day" value={`${formatNumber(campaign.rate_limit.per_day)}/d`} />
                <SettingRow
                  label="Send window"
                  value={
                    campaign.rate_limit.window_start
                      ? `${campaign.rate_limit.window_start}–${campaign.rate_limit.window_end ?? ""} ${campaign.rate_limit.timezone ?? ""}`
                      : "Anytime"
                  }
                />
                <SettingRow label="From account" value={campaign.from_account ?? "—"} mono />
              </Panel>

              {campaign.eligibility && (
                <Panel>
                  <PanelHeader>Eligibility</PanelHeader>
                  <div className="mt-3">
                    <EligibilitySummary data={campaign.eligibility} compact />
                  </div>
                </Panel>
              )}
            </div>
          </div>
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        destructive
        kicker="Cancel campaign"
        title="Cancel this campaign?"
        description="Queued messages that have not yet been sent will be stopped. Already-sent messages are unaffected. This cannot be undone."
        confirmLabel="Cancel campaign"
        cancelLabel="Keep running"
        loading={cancel.isPending}
        onConfirm={async () => {
          setCancelOpen(false);
          await run("cancel", () => cancel.mutateAsync(campaign.id));
        }}
      />
    </div>
  );
}

function SettingRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <MicroLabel>{label}</MicroLabel>
      <span className={mono ? "font-mono text-[12px] text-ink" : "text-sm text-ink"}>
        {value}
      </span>
    </div>
  );
}
