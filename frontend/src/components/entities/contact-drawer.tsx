"use client";

import {
  ArrowUpRight,
  ExternalLink,
  Link2,
  Mail,
  RefreshCw,
  User as UserIcon,
} from "lucide-react";
import Link from "next/link";
import { Drawer } from "@/components/ui/Drawer";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { StatusChip } from "@/components/ui/StatusChip";
import { CopyButton } from "@/components/ui/CopyButton";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import {
  useContact,
  useContactHistory,
  usePatchContact,
  useRevalidateContact,
} from "@/lib/api/hooks";
import { useDemoMode } from "@/lib/demo";
import type { ContactDetail, ValidationRow } from "@/lib/api/schema";
import { formatDateTime, formatRelative } from "@/lib/format";
import { formatConfidencePct, sourceLabel } from "@/lib/entities";
import { EditableField } from "./editable-field";
import { ValidationGlyph } from "./validation-glyph";

interface ContactDrawerProps {
  contactId: string;
  open: boolean;
  onClose: () => void;
  /** When true, default the drawer to the History tab (validation deep-link). */
  defaultTab?: "profile" | "history";
}

export function ContactDrawer({
  contactId,
  open,
  onClose,
  defaultTab = "profile",
}: ContactDrawerProps) {
  const { data, isLoading, isError } = useContact(contactId);
  const revalidate = useRevalidateContact();

  return (
    <Drawer open={open} onOpenChange={(o) => !o && onClose()}>
      <Drawer.Content
        kicker="Contact"
        title={data?.full_name ?? "Contact"}
        width="lg"
        actions={
          <div className="flex items-center gap-1.5">
            <Button
              size="sm"
              variant="secondary"
              disabled={revalidate.isPending}
              onClick={() => revalidate.mutate(contactId)}
            >
              <RefreshCw
                className={revalidate.isPending ? "size-3.5 animate-spin" : "size-3.5"}
              />
              Revalidate
            </Button>
            <CopyButton value={contactId} label="ID" />
          </div>
        }
      >
        {isLoading ? (
          <ContactSkeleton />
        ) : isError || !data ? (
          <EmptyState
            icon={UserIcon}
            title="Couldn't load contact"
            description="The contact detail failed to load. Close and retry."
          />
        ) : (
          <ContactBody contact={data} defaultTab={defaultTab} />
        )}
      </Drawer.Content>
    </Drawer>
  );
}

function ContactBody({
  contact,
  defaultTab,
}: {
  contact: ContactDetail;
  defaultTab: "profile" | "history";
}) {
  const patch = usePatchContact();
  const { demoMode } = useDemoMode();
  const { data: history } = useContactHistory(contact.id);

  const save = (field: "owner_user_id" | "notes" | "next_action") =>
    (value: string) =>
      patch.mutate({ contactId: contact.id, patch: { [field]: value || null } });

  const checks = contact.validation_checks ?? [];
  const latest = checks[0];

  return (
    <div className="flex flex-col gap-5">
      {/* Identity header */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {contact.designation && (
            <span className="rounded-full border border-border bg-[var(--color-surface-1)] px-2 py-0.5 text-xs text-ink/90">
              {contact.designation}
            </span>
          )}
          {contact.seniority && (
            <MicroLabel className="rounded-full border border-border px-2 py-0.5">
              {contact.seniority}
            </MicroLabel>
          )}
          {contact.department && (
            <MicroLabel className="rounded-full border border-border px-2 py-0.5">
              {contact.department}
            </MicroLabel>
          )}
          {contact.primary_contact && (
            <MicroLabel className="rounded-full border border-[var(--color-accent)]/40 px-2 py-0.5 text-accent">
              Primary
            </MicroLabel>
          )}
          {contact.sales_ready && (
            <MicroLabel className="rounded-full border border-[var(--color-accent)]/40 px-2 py-0.5 text-accent">
              Sales-ready
            </MicroLabel>
          )}
        </div>

        {/* Email + validation status + confidence */}
        <div className="flex flex-col gap-2 rounded-[10px] border border-border bg-[var(--color-surface-1)] p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Mail className="size-3.5 text-muted" />
            {contact.email ? (
              <>
                <span className="min-w-0 truncate font-mono text-sm text-ink">
                  {contact.email}
                </span>
                <CopyButton value={contact.email} />
              </>
            ) : (
              <span className="text-sm text-muted">No email resolved</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {contact.final_email_status && (
              <StatusChip status={contact.final_email_status} />
            )}
            {contact.confidence_score != null && (
              <span className="inline-flex items-center gap-1 text-xs text-muted">
                <MicroLabel as="span">Confidence</MicroLabel>
                <span className="font-mono text-ink/90">
                  {formatConfidencePct(contact.confidence_score)}
                </span>
              </span>
            )}
            {contact.last_verified_at && (
              <span className="text-xs text-muted">
                Verified {formatRelative(contact.last_verified_at)}
              </span>
            )}
          </div>
          {latest?.final_reason && (
            <p className="text-xs text-muted">{latest.final_reason}</p>
          )}
        </div>

        {/* social links */}
        {(contact.linkedin_url || contact.phone) && (
          <div className="flex flex-wrap items-center gap-3 text-xs">
            {contact.linkedin_url && (
              <a
                href={contact.linkedin_url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1 text-info hover:underline"
              >
                <Link2 className="size-3.5" />
                LinkedIn
                <ExternalLink className="size-3" />
              </a>
            )}
            {contact.phone && (
              <span className="inline-flex items-center gap-1 font-mono text-ink/90">
                {contact.phone}
                <CopyButton value={contact.phone} />
              </span>
            )}
          </div>
        )}
      </div>

      <Tabs defaultValue={defaultTab === "history" ? "history" : "profile"}>
        <TabsList>
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="history">
            History ({history?.length ?? checks.length})
          </TabsTrigger>
        </TabsList>

        {/* ── Profile: disposition + provenance ── */}
        <TabsContent value="profile">
          <div className="flex flex-col gap-4">
            {/* Inline sales disposition — optimistic patch, syncs to Sheet */}
            <div className="flex flex-col gap-3 rounded-[10px] border border-border p-3">
              <MicroLabel className="text-accent/80">Sales disposition</MicroLabel>
              <EditableField
                label="Owner"
                value={contact.owner_user_id}
                onSave={save("owner_user_id")}
                placeholder="Assign an owner…"
                mono
                saving={patch.isPending}
                hint="Syncs to the Google Sheet on save"
              />
              <EditableField
                label="Sales notes"
                value={contact.notes}
                onSave={save("notes")}
                placeholder="Add a note…"
                multiline
                saving={patch.isPending}
                hint="Syncs to the Google Sheet on save"
              />
              <EditableField
                label="Next action"
                value={
                  (contact as ContactDetail & { next_action?: string | null })
                    .next_action ?? null
                }
                onSave={save("next_action")}
                placeholder="e.g. Send intro email…"
                saving={patch.isPending}
                hint="Syncs to the Google Sheet on save"
              />
            </div>

            {/* Per-stage validation mini-timeline */}
            {latest && (
              <div className="flex flex-col gap-2.5 rounded-[10px] border border-border p-3">
                <div className="flex items-center justify-between">
                  <MicroLabel>Validation stages</MicroLabel>
                  <Link
                    href="/validation"
                    className="inline-flex items-center gap-0.5 font-mono text-[11px] uppercase tracking-wider text-info hover:underline"
                  >
                    Pipeline
                    <ArrowUpRight className="size-3" />
                  </Link>
                </div>
                <StageTimeline row={latest} />
                {latest.final_status && (
                  <div className="flex items-center gap-2 pt-1">
                    <MicroLabel>Final</MicroLabel>
                    <StatusChip status={latest.final_status} />
                  </div>
                )}
              </div>
            )}

            {/* Enrichment provenance */}
            <div className="flex flex-col gap-2 rounded-[10px] border border-border p-3">
              <MicroLabel>Enrichment provenance</MicroLabel>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <ProvItem
                  label="Source"
                  value={sourceLabel(contact.source_type)}
                />
                <ProvItem
                  label="Provider"
                  value={
                    contact.enrichment_provider
                      ? sourceLabel(contact.enrichment_provider)
                      : "—"
                  }
                  mock={demoMode && !!contact.enrichment_provider}
                />
                <ProvItem label="Status" value={contact.enrichment_status} />
                <ProvItem
                  label="Discovered"
                  value={formatDateTime(contact.created_at)}
                />
              </dl>
            </div>
          </div>
        </TabsContent>

        {/* ── History: full validation feed ── */}
        <TabsContent value="history">
          <ValidationHistoryList rows={history ?? checks} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function StageTimeline({ row }: { row: ValidationRow }) {
  const stages: { key: string; label: string; status: string | null }[] = [
    { key: "syntax", label: "Syntax", status: row.syntax_status },
    { key: "disposable", label: "Disposable", status: row.disposable_status },
    { key: "role", label: "Role", status: row.role_based_status },
    { key: "mx", label: "MX", status: row.mx_status },
    {
      key: "llm",
      label: "LLM",
      status: row.llm_score != null ? "pass" : "pending",
    },
    { key: "mv", label: "Provider", status: row.millionverifier_status },
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
      {stages.map((s) => (
        <div key={s.key} className="flex flex-col items-center gap-1">
          <ValidationGlyph
            status={s.status}
            tip={
              s.key === "llm" && row.llm_reason
                ? `LLM ${row.llm_score}: ${row.llm_reason}`
                : s.key === "mv" && row.millionverifier_status
                  ? `Provider: ${row.millionverifier_status}`
                  : `${s.label}: ${s.status ?? "pending"}`
            }
          />
          <MicroLabel className="text-[10px]">{s.label}</MicroLabel>
        </div>
      ))}
    </div>
  );
}

function ValidationHistoryList({ rows }: { rows: ValidationRow[] }) {
  if (!rows.length) {
    return (
      <EmptyState
        compact
        title="No validation history"
        description="This contact hasn't been through the validation pipeline yet."
      />
    );
  }
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map((r) => (
        <li
          key={r.id}
          className="rounded-[10px] border border-border bg-[var(--color-surface-1)] p-3"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            {r.final_status && <StatusChip status={r.final_status} />}
            <span className="font-mono text-[11px] text-muted">
              {formatDateTime(r.verified_at ?? r.created_at)}
              {r.retry_count > 0 ? ` · retry ${r.retry_count}` : ""}
            </span>
          </div>
          <div className="mt-2">
            <StageTimeline row={r} />
          </div>
          {r.final_reason && (
            <p className="mt-2 text-xs text-muted">{r.final_reason}</p>
          )}
        </li>
      ))}
    </ul>
  );
}

function ProvItem({
  label,
  value,
  mock,
}: {
  label: string;
  value: string | null | undefined;
  mock?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <MicroLabel>{label}</MicroLabel>
      <span className="flex items-center gap-1.5 text-sm text-ink/90">
        {value?.trim() ? value : "—"}
        {mock && (
          <span className="rounded border border-[var(--color-warn)]/40 px-1 font-mono text-[10px] uppercase tracking-wider text-[var(--color-warn)]">
            Mock
          </span>
        )}
      </span>
    </div>
  );
}

function ContactSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2">
        <Skeleton className="h-6 w-20 rounded-full" />
        <Skeleton className="h-6 w-16 rounded-full" />
      </div>
      <Skeleton className="h-20 w-full rounded-[10px]" />
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-40 w-full rounded-[10px]" />
    </div>
  );
}
