"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { ScrollText, Search } from "lucide-react";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { DataTable } from "@/components/ui/DataTable";
import { Input } from "@/components/ui/Input";
import { EmptyState } from "@/components/ui/EmptyState";
import { useAudit } from "@/lib/api/hooks";
import { formatDateTime } from "@/lib/format";
import type { AuditEntry } from "@/lib/api/schema";

function summarize(entry: AuditEntry): string {
  if (entry.summary) return entry.summary;
  const parts: string[] = [];
  if (entry.before !== undefined && entry.before !== null) {
    parts.push(`from ${JSON.stringify(entry.before)}`);
  }
  if (entry.after !== undefined && entry.after !== null) {
    parts.push(`to ${JSON.stringify(entry.after)}`);
  }
  return parts.join(" ") || "—";
}

export default function AuditSettingsPage() {
  const [q, setQ] = useState("");
  const { data: entries = [], isLoading } = useAudit();

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return entries;
    return entries.filter((e) =>
      [e.actor, e.actor_name, e.action, e.entity_type, e.entity_id, e.summary]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(needle)),
    );
  }, [entries, q]);

  const columns = useMemo<ColumnDef<AuditEntry, unknown>[]>(
    () => [
      {
        id: "actor",
        header: "Actor",
        accessorFn: (r) => r.actor_name ?? r.actor ?? "—",
        cell: (c) => <span className="text-sm text-ink">{String(c.getValue())}</span>,
      },
      {
        accessorKey: "action",
        header: "Action",
        cell: (c) => (
          <span className="font-mono text-xs uppercase text-accent">{String(c.getValue())}</span>
        ),
        meta: { mono: true },
      },
      {
        id: "entity",
        header: "Entity",
        accessorFn: (r) => r.entity_type ?? "—",
        cell: (c) => {
          const r = c.row.original;
          return (
            <div className="flex flex-col">
              <span className="text-sm text-ink">{r.entity_type ?? "—"}</span>
              {r.entity_id ? (
                <span className="font-mono text-[10px] text-muted">{r.entity_id}</span>
              ) : null}
            </div>
          );
        },
        meta: { mobilePriority: "medium" },
      },
      {
        id: "change",
        header: "Change",
        accessorFn: (r) => summarize(r),
        cell: (c) => (
          <span className="block max-w-md truncate text-xs text-muted" title={String(c.getValue())}>
            {String(c.getValue())}
          </span>
        ),
        meta: { mobilePriority: "low" },
      },
      {
        accessorKey: "created_at",
        header: "When",
        cell: (c) => (
          <span className="text-xs text-muted">{formatDateTime(c.getValue() as string | null)}</span>
        ),
        meta: { mobilePriority: "medium" },
      },
    ],
    [],
  );

  return (
    <Panel flush>
      <PanelHeader
        className="px-4 pt-4 sm:px-5"
        actions={
          <div className="w-full max-w-xs sm:w-64">
            <Input
              leading={<Search className="size-4" />}
              placeholder="Search actor, action, entity…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
        }
      >
        <MicroLabel className="text-accent/70">Settings</MicroLabel>
        <h2 className="text-base font-semibold text-ink">Audit Logs</h2>
      </PanelHeader>

      <DataTable<AuditEntry>
        columns={columns}
        data={filtered}
        loading={isLoading}
        getRowId={(r) => r.id}
        emptyState={
          <EmptyState
            icon={ScrollText}
            kicker={q ? "No matches" : "No audit entries"}
            title={q ? "Nothing matches your search" : "No audit activity yet"}
            description={
              q
                ? "Try a different actor, action, or entity."
                : "Every mutation — jobs, sheets sync, source sign-off, settings, users — is recorded here with actor, before/after values, and timestamp."
            }
          />
        }
      />
    </Panel>
  );
}
