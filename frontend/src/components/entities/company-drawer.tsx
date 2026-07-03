"use client";

import {
  Building2,
  ExternalLink,
  Globe,
  MapPin,
  Phone,
  Star,
  Users,
} from "lucide-react";
import { Drawer } from "@/components/ui/Drawer";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { StatusChip } from "@/components/ui/StatusChip";
import { ComplianceBadge } from "@/components/ui/ComplianceBadge";
import { CopyButton } from "@/components/ui/CopyButton";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useCompany } from "@/lib/api/hooks";
import type { CompanyDetail, ContactBrief } from "@/lib/api/schema";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import {
  formatRating,
  sourceLabel,
  toCompliancePosture,
} from "@/lib/entities";
import { useEntityLinks } from "./use-entity-links";

interface CompanyDrawerProps {
  companyId: string;
  open: boolean;
  onClose: () => void;
}

export function CompanyDrawer({ companyId, open, onClose }: CompanyDrawerProps) {
  const { data, isLoading, isError } = useCompany(companyId);
  const { openContact } = useEntityLinks();

  return (
    <Drawer open={open} onOpenChange={(o) => !o && onClose()}>
      <Drawer.Content
        kicker="Company"
        title={data?.canonical_name ?? "Company"}
        width="lg"
        actions={<CopyButton value={companyId} label="ID" />}
      >
        {isLoading ? (
          <CompanySkeleton />
        ) : isError || !data ? (
          <EmptyState
            icon={Building2}
            title="Couldn't load company"
            description="The company detail failed to load. Close and retry."
          />
        ) : (
          <CompanyBody company={data} onOpenContact={openContact} />
        )}
      </Drawer.Content>
    </Drawer>
  );
}

function CompanyBody({
  company,
  onOpenContact,
}: {
  company: CompanyDetail;
  onOpenContact: (id: string) => void;
}) {
  const rating = formatRating(company.google_rating);
  const posture = toCompliancePosture(company.compliance_posture);

  return (
    <div className="flex flex-col gap-5">
      {/* Identity header */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {company.domain && (
            <a
              href={company.website ?? `https://${company.domain}`}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 font-mono text-xs text-info hover:underline"
            >
              <Globe className="size-3.5" />
              {company.domain}
              <ExternalLink className="size-3" />
            </a>
          )}
          {rating !== "—" && (
            <span className="inline-flex items-center gap-1 text-sm text-ink/90">
              <Star className="size-3.5 text-[var(--color-warn)]" fill="currentColor" />
              <span className="font-mono">{rating}</span>
              {company.google_reviews != null && (
                <span className="text-xs text-muted">
                  ({formatNumber(company.google_reviews)})
                </span>
              )}
            </span>
          )}
          {company.website_status && (
            <StatusChip status={company.website_status} />
          )}
        </div>

        {/* per-source compliance badges */}
        <div className="flex flex-wrap items-center gap-1.5">
          {company.sources.length > 0 ? (
            company.sources.map((s) => (
              <ComplianceBadge
                key={s.id}
                posture={toCompliancePosture(s.compliance_posture, s.access_method)}
                note={`${sourceLabel(s.source_name)} · ${s.access_method} · first seen ${formatDate(
                  s.first_seen_at,
                )}`}
              />
            ))
          ) : (
            <ComplianceBadge posture={posture} />
          )}
        </div>
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="contacts">
            Contacts ({company.contacts.length})
          </TabsTrigger>
          <TabsTrigger value="evidence">
            Evidence ({company.sources.length})
          </TabsTrigger>
          <TabsTrigger value="signals">
            Signals ({company.hiring_signals.length})
          </TabsTrigger>
        </TabsList>

        {/* ── Overview ── */}
        <TabsContent value="overview">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
            <Detail
              icon={MapPin}
              label="Address"
              value={[company.address, [company.city, company.state, company.postal_code]
                .filter(Boolean)
                .join(", "), company.country]
                .filter(Boolean)
                .join(" · ")}
            />
            <Detail icon={Phone} label="Phone" value={company.phone} mono copy />
            <Detail label="Industry" value={company.industry} />
            <Detail label="Company size" value={company.company_size} />
            <Detail
              label="Services"
              value={company.services.length ? company.services.join(", ") : null}
              full
            />
            <Detail
              label="Last refreshed"
              value={
                company.last_refreshed_at
                  ? formatDateTime(company.last_refreshed_at)
                  : null
              }
            />
            <Detail label="Dedupe status" value={company.dedupe_status} />
          </dl>
        </TabsContent>

        {/* ── Contacts mini-table -> stacks contact drawer ── */}
        <TabsContent value="contacts">
          {company.contacts.length === 0 ? (
            <EmptyState
              compact
              icon={Users}
              title="No contacts discovered"
              description="No people were resolved for this company yet."
            />
          ) : (
            <div className="flex flex-col divide-y divide-border/60 rounded-[10px] border border-border">
              {company.contacts.map((c) => (
                <ContactRow key={c.id} contact={c} onOpen={onOpenContact} />
              ))}
            </div>
          )}
        </TabsContent>

        {/* ── Evidence: per-source provenance ── */}
        <TabsContent value="evidence">
          {company.sources.length === 0 ? (
            <EmptyState compact title="No source evidence" />
          ) : (
            <ul className="flex flex-col gap-2.5">
              {company.sources.map((s) => (
                <li
                  key={s.id}
                  className="rounded-[10px] border border-border bg-[var(--color-surface-1)] p-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium text-ink">
                      {sourceLabel(s.source_name)}
                    </span>
                    <ComplianceBadge
                      posture={toCompliancePosture(
                        s.compliance_posture,
                        s.access_method,
                      )}
                    />
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
                    <span>
                      <MicroLabel as="span">Access</MicroLabel>{" "}
                      <span className="font-mono">{s.access_method}</span>
                    </span>
                    <span>
                      <MicroLabel as="span">First seen</MicroLabel>{" "}
                      {formatDate(s.first_seen_at)}
                    </span>
                  </div>
                  {s.source_url && (
                    <a
                      href={s.source_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="mt-1.5 inline-flex max-w-full items-center gap-1 truncate font-mono text-xs text-info hover:underline"
                    >
                      <ExternalLink className="size-3 shrink-0" />
                      <span className="truncate">{s.source_url}</span>
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
        </TabsContent>

        {/* ── Hiring signals ── */}
        <TabsContent value="signals">
          {company.hiring_signals.length === 0 ? (
            <EmptyState
              compact
              title="No hiring signals"
              description="No open roles or growth signals detected for this company."
            />
          ) : (
            <ul className="flex flex-col gap-2.5">
              {company.hiring_signals.map((h) => (
                <li
                  key={h.id}
                  className="rounded-[10px] border border-border bg-[var(--color-surface-1)] p-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium text-ink">
                      {h.job_title ?? "Role"}
                    </span>
                    <StatusChip status={h.signal_type} />
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
                    {h.location && <span>{h.location}</span>}
                    <span>{sourceLabel(h.source)}</span>
                    {h.posted_at && <span>{formatDate(h.posted_at)}</span>}
                  </div>
                  {h.source_url && (
                    <a
                      href={h.source_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="mt-1.5 inline-flex items-center gap-1 font-mono text-xs text-info hover:underline"
                    >
                      <ExternalLink className="size-3" />
                      View posting
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function ContactRow({
  contact,
  onOpen,
}: {
  contact: ContactBrief;
  onOpen: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(contact.id)}
      className="flex items-center justify-between gap-3 px-3 py-2.5 text-left transition-colors hover:bg-[var(--color-surface-1)] lm-focus"
    >
      <div className="flex min-w-0 flex-col">
        <span className="flex items-center gap-2 truncate text-sm text-ink">
          {contact.full_name ?? "Unknown"}
          {contact.primary_contact && (
            <MicroLabel className="text-accent/80">Primary</MicroLabel>
          )}
        </span>
        <span className="truncate text-xs text-muted">
          {contact.designation ?? contact.role_category ?? "—"}
          {contact.email ? ` · ${contact.email}` : ""}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {contact.sales_ready && (
          <MicroLabel className="text-accent">Sales-ready</MicroLabel>
        )}
        {contact.final_email_status && (
          <StatusChip status={contact.final_email_status} />
        )}
      </div>
    </button>
  );
}

function Detail({
  icon: Icon,
  label,
  value,
  mono,
  copy,
  full,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | null | undefined;
  mono?: boolean;
  copy?: boolean;
  full?: boolean;
}) {
  return (
    <div className={full ? "sm:col-span-2" : undefined}>
      <MicroLabel className="mb-1 flex items-center gap-1">
        {Icon && <Icon className="size-3" />}
        {label}
      </MicroLabel>
      <div className="flex items-center gap-1.5">
        <span
          className={mono ? "font-mono text-sm text-ink/90" : "text-sm text-ink/90"}
        >
          {value?.trim() ? value : "—"}
        </span>
        {copy && value && <CopyButton value={value} />}
      </div>
    </div>
  );
}

function CompanySkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-5 w-40" />
      <div className="flex gap-2">
        <Skeleton className="h-6 w-24 rounded-full" />
        <Skeleton className="h-6 w-24 rounded-full" />
      </div>
      <Skeleton className="h-9 w-full" />
      <div className="grid grid-cols-2 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex flex-col gap-1.5">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-4 w-28" />
          </div>
        ))}
      </div>
    </div>
  );
}
