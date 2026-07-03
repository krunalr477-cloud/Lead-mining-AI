"use client";

import { useMemo, useState } from "react";
import { ListChecks, Search } from "lucide-react";
import {
  Panel,
  Toolbar,
  Input,
  Select,
  EmptyState,
} from "@/components/ui";
import { useOutreachQueue, useCampaigns } from "@/lib/api/hooks";
import { OutreachQueueTable } from "@/components/outreach/OutreachQueueTable";

/**
 * §20 Outreach Queue — a global DataTable of every queued/sent message across
 * campaigns, filterable by campaign and send status. Degrades to an EmptyState
 * when no outreach endpoint exists yet (the hook returns [] on 404).
 */

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "queued", label: "Queued" },
  { value: "sent", label: "Sent" },
  { value: "delivered", label: "Delivered" },
  { value: "opened", label: "Opened" },
  { value: "clicked", label: "Clicked" },
  { value: "replied", label: "Replied" },
  { value: "hard_bounce", label: "Hard bounce" },
  { value: "soft_bounce", label: "Soft bounce" },
  { value: "blocked", label: "Blocked" },
  { value: "unsubscribed", label: "Unsubscribed" },
];

export default function OutreachPage() {
  const [campaignId, setCampaignId] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");

  const { data: campaigns } = useCampaigns();
  const { data: rows, isLoading } = useOutreachQueue({
    campaign_id: campaignId || undefined,
    status: status || undefined,
  });

  const campaignOptions = useMemo(
    () => [
      { value: "", label: "All campaigns" },
      ...(campaigns ?? []).map((c) => ({ value: c.id, label: c.name })),
    ],
    [campaigns],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows ?? [];
    return (rows ?? []).filter((r) =>
      [r.contact_name ?? "", r.email, r.company ?? "", r.subject]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [rows, search]);

  return (
    <div className="flex flex-col gap-4">
      <Toolbar>
        <Input
          leading={<Search className="size-4" />}
          placeholder="Search recipient, email, company…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full sm:w-72"
        />
        <Select
          options={campaignOptions}
          value={campaignId}
          onChange={(e) => setCampaignId(e.target.value)}
          className="w-full sm:w-56"
        />
        <Select
          options={STATUS_OPTIONS}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="w-full sm:w-44"
        />
      </Toolbar>

      <Panel flush>
        {!isLoading && (rows ?? []).length === 0 ? (
          <EmptyState
            icon={ListChecks}
            kicker="Queue empty"
            title="No messages in the outreach queue"
            description="Launch a campaign to populate the queue, or the outreach endpoint may not be available yet. This screen degrades gracefully until then."
          />
        ) : (
          <OutreachQueueTable rows={filtered} loading={isLoading} />
        )}
      </Panel>
    </div>
  );
}
