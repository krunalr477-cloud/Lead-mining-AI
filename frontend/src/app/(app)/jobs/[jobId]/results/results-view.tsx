"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { ColumnDef } from "@tanstack/react-table";
import {
  ChevronLeft,
  ChevronRight,
  Map as MapIcon,
  Minus,
  Table2,
} from "lucide-react";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { MetricCard } from "@/components/ui/MetricCard";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { Toolbar } from "@/components/ui/Toolbar";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Button } from "@/components/ui/Button";
import { DataTable } from "@/components/ui/DataTable";
import { StatusChip } from "@/components/ui/StatusChip";
import { ComplianceBadge } from "@/components/ui/ComplianceBadge";
import { CopyButton } from "@/components/ui/CopyButton";
import { EmptyState } from "@/components/ui/EmptyState";
import { useToast } from "@/components/ui/Toast";
import { useCompanyMap, useContacts, useJob, useRevalidate } from "@/lib/api/hooks";
import type { Company, Contact } from "@/lib/api/schema";
import { formatNumber } from "@/lib/format";
import { formatRating, sourceLabel, toCompliancePosture } from "@/lib/entities";
import { useEntityLinks } from "@/components/entities/use-entity-links";
import { ResultsMap } from "./results-map";

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY ?? "";
const HAS_MAPS = MAPS_KEY.trim().length > 0;
const PAGE_SIZE = 50;

/** A flattened company+contact row for the results table. */
interface Row {
  contact: Contact;
  company: Company | undefined;
}

/** A verified email status is one whose final decision is VERIFIED. */
function isVerified(status: string | null | undefined): boolean {
  return (status ?? "").toUpperCase() === "VERIFIED";
}

type MetricKey = "companies" | "contacts" | "emails" | "verified" | "review" | "invalid";
type ViewMode = "raw" | "sales";

export function ResultsView({ jobId }: { jobId: string }) {
  const router = useRouter();
  const toast = useToast();
  const { openCompany, openContact } = useEntityLinks();

  const { data: job } = useJob(jobId);
  const { data: companyMap = {} } = useCompanyMap(jobId);
  const revalidate = useRevalidate();

  // ── Controls ──
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [cityFilter, setCityFilter] = useState("");
  const [view, setView] = useState<ViewMode>("raw");
  const [surface, setSurface] = useState<"table" | "map">("table");
  const [activeMetric, setActiveMetric] = useState<MetricKey | null>(null);
  const [page, setPage] = useState(0);

  const totals = job?.totals_json;

  // Server-paged contacts. Status/search are refined client-side (backend
  // status filter uses the 4 canonical buckets; we want the richer set), but
  // sales_ready + role + city hit the server where supported.
  const { data: contacts = [], isLoading, isFetching } = useContacts({
    job_id: jobId,
    role: roleFilter || undefined,
    sales_ready: view === "sales" ? true : undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  // Build rows, join company identity, then apply client-side refinements.
  const rows = useMemo<Row[]>(() => {
    let list: Row[] = contacts.map((c) => ({
      contact: c,
      company: c.company_id ? companyMap[c.company_id] : undefined,
    }));

    // Sales-ready view MUST exclude non-verified rows.
    if (view === "sales") {
      list = list.filter(
        (r) => r.contact.sales_ready && isVerified(r.contact.final_email_status),
      );
    }

    if (statusFilter) {
      list = list.filter(
        (r) => (r.contact.final_email_status ?? "") === statusFilter,
      );
    }
    if (cityFilter) {
      list = list.filter((r) => r.company?.city === cityFilter);
    }
    if (sourceFilter) {
      list = list.filter((r) =>
        (r.company?.source_urls ?? []).some((u) =>
          u.toLowerCase().includes(sourceFilter.toLowerCase()),
        ) || (r.contact.source_type ?? "").toLowerCase() === sourceFilter.toLowerCase(),
      );
    }
    if (activeMetric) {
      list = list.filter((r) => metricMatches(activeMetric, r));
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((r) => {
        const c = r.contact;
        return (
          (c.full_name ?? "").toLowerCase().includes(q) ||
          (c.email ?? "").toLowerCase().includes(q) ||
          (r.company?.canonical_name ?? "").toLowerCase().includes(q) ||
          (r.company?.domain ?? "").toLowerCase().includes(q)
        );
      });
    }
    return list;
  }, [contacts, companyMap, view, statusFilter, cityFilter, sourceFilter, activeMetric, search]);

  // Distinct filter options derived from the loaded company map.
  const { cityOptions, roleOptions, sourceOptions } = useMemo(() => {
    const cities = new Set<string>();
    const sources = new Set<string>();
    for (const c of Object.values(companyMap)) {
      if (c.city) cities.add(c.city);
      for (const u of c.source_urls ?? []) {
        // keep the coarse source slug from the url host when possible
        if (u.includes("maps.google")) sources.add("google_maps");
        else if (u.includes("facebook")) sources.add("facebook");
        else sources.add("directories");
      }
    }
    const roles = new Set<string>();
    for (const c of contacts) if (c.role_category) roles.add(c.role_category);
    return {
      cityOptions: [...cities].sort(),
      roleOptions: [...roles].sort(),
      sourceOptions: [...sources].sort(),
    };
  }, [companyMap, contacts]);

  const columns = useMemo<ColumnDef<Row, unknown>[]>(
    () => [
      {
        id: "company",
        header: "Company",
        cell: ({ row }) => {
          const c = row.original.company;
          return (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                if (row.original.contact.company_id)
                  openCompany(row.original.contact.company_id);
              }}
              className="flex flex-col text-left lm-focus"
            >
              <span className="truncate font-medium text-ink hover:text-accent">
                {c?.canonical_name ?? "—"}
              </span>
              {c?.domain && (
                <span className="truncate font-mono text-[11px] text-muted">
                  {c.domain}
                </span>
              )}
            </button>
          );
        },
      },
      {
        id: "city",
        header: "City",
        meta: { mobilePriority: "low" },
        cell: ({ row }) => (
          <span className="text-ink/80">{row.original.company?.city ?? "—"}</span>
        ),
      },
      {
        id: "rating",
        header: "Rating",
        meta: { mobilePriority: "low", align: "right" },
        cell: ({ row }) => {
          const r = formatRating(row.original.company?.google_rating);
          return <span className="font-mono text-ink/80">{r}</span>;
        },
      },
      {
        id: "contact",
        header: "Contact",
        cell: ({ row }) => (
          <span className="text-ink">
            {row.original.contact.full_name ?? "—"}
          </span>
        ),
      },
      {
        id: "role",
        header: "Role",
        meta: { mobilePriority: "medium" },
        cell: ({ row }) => (
          <span className="text-ink/80">
            {row.original.contact.designation ??
              row.original.contact.role_category ??
              "—"}
          </span>
        ),
      },
      {
        id: "email",
        header: "Email",
        cell: ({ row }) => {
          const email = row.original.contact.email;
          if (!email) return <span className="text-muted">—</span>;
          return (
            <span className="flex items-center gap-1">
              <span className="truncate font-mono text-[13px] text-ink/90">
                {email}
              </span>
              <CopyButton value={email} />
            </span>
          );
        },
      },
      {
        id: "validation",
        header: "Validation",
        meta: { mobilePriority: "medium" },
        cell: ({ row }) => {
          const s = row.original.contact.final_email_status;
          return s ? <StatusChip status={s} /> : <span className="text-muted">—</span>;
        },
      },
      {
        id: "source",
        header: "Source",
        meta: { mobilePriority: "low" },
        cell: ({ row }) => {
          const c = row.original.company;
          const posture = toCompliancePosture(c?.compliance_posture);
          return (
            <div className="flex flex-wrap items-center gap-1">
              <ComplianceBadge
                posture={posture}
                note={
                  c?.source_urls?.length
                    ? `Discovered via ${c.source_urls.length} source(s)`
                    : undefined
                }
              />
            </div>
          );
        },
      },
      {
        id: "sales_ready",
        header: "Sales-ready",
        meta: { align: "center", mobilePriority: "medium" },
        cell: ({ row }) => {
          const ready =
            row.original.contact.sales_ready &&
            isVerified(row.original.contact.final_email_status);
          return ready ? (
            <span className="inline-flex text-accent" aria-label="Sales-ready">
              ✓
            </span>
          ) : (
            <Minus className="mx-auto size-3.5 text-muted/50" aria-label="Not sales-ready" />
          );
        },
      },
    ],
    [openCompany],
  );

  const metrics: { key: MetricKey; label: string; value: number | undefined }[] = [
    { key: "companies", label: "Companies", value: totals?.total_companies },
    { key: "contacts", label: "Contacts", value: totals?.total_contacts },
    { key: "emails", label: "Emails found", value: totals?.emails_found },
    { key: "verified", label: "Verified", value: totals?.verified_emails },
    { key: "review", label: "Review", value: totals?.review_emails },
    { key: "invalid", label: "Invalid", value: totals?.invalid_emails },
  ];

  const onRevalidate = (selected: Row[]) => {
    const ids = selected.map((r) => r.contact.id);
    revalidate.mutate(
      { contact_ids: ids },
      {
        onSuccess: () => toast.info(`Revalidating ${ids.length} contact(s)`),
        onError: () => toast.error("Revalidation failed"),
      },
    );
  };

  const surfaceOptions = HAS_MAPS
    ? ([
        { value: "table", label: "Table" },
        { value: "map", label: "Map" },
      ] as const)
    : null;

  return (
    <div className="flex flex-col gap-5">
      {/* Summary metric cards — clicking filters the table */}
      <Panel>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {metrics.map((m) => {
            const active = activeMetric === m.key;
            return (
              <button
                key={m.key}
                type="button"
                onClick={() => {
                  setActiveMetric(active ? null : m.key);
                  setPage(0);
                }}
                className={
                  "rounded-[10px] border p-3 text-left transition-colors " +
                  (active
                    ? "border-[var(--color-accent)]/50 bg-[color-mix(in_srgb,var(--color-accent)_8%,transparent)]"
                    : "border-transparent hover:border-border hover:bg-[var(--color-surface-1)]")
                }
              >
                <MetricCard label={m.label} value={formatNumber(m.value)} />
              </button>
            );
          })}
        </div>
      </Panel>

      <Panel>
        <PanelHeader
          actions={
            <div className="flex items-center gap-2">
              <SegmentedControl<ViewMode>
                size="sm"
                options={[
                  { value: "raw", label: "Raw mined" },
                  { value: "sales", label: "Sales-ready" },
                ]}
                value={view}
                onChange={(v) => {
                  setView(v);
                  setPage(0);
                }}
              />
              {surfaceOptions && (
                <SegmentedControl<"table" | "map">
                  size="sm"
                  options={surfaceOptions as unknown as { value: "table" | "map"; label: string }[]}
                  value={surface}
                  onChange={setSurface}
                />
              )}
            </div>
          }
        >
          <h2 className="text-base font-semibold text-ink">Mined leads</h2>
          {job?.name && <MicroLabel>{job.name}</MicroLabel>}
        </PanelHeader>

        <Toolbar className="mb-4">
          <Input
            placeholder="Search company or contact…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full max-w-xs"
          />
          {sourceOptions.length > 0 && (
            <Select
              placeholder="Source"
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              options={[
                { value: "", label: "All sources" },
                ...sourceOptions.map((s) => ({ value: s, label: sourceLabel(s) })),
              ]}
            />
          )}
          <Select
            placeholder="Validation"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            options={[
              { value: "", label: "All statuses" },
              { value: "VERIFIED", label: "Verified" },
              { value: "REVIEW", label: "Review" },
              { value: "INVALID", label: "Invalid" },
              { value: "PENDING", label: "Pending" },
              { value: "MX_FAILED", label: "MX failed" },
              { value: "CATCH_ALL_REVIEW", label: "Catch-all" },
              { value: "DISPOSABLE_REJECTED", label: "Disposable" },
              { value: "ROLE_BASED_REJECTED", label: "Role-based" },
            ]}
          />
          {roleOptions.length > 0 && (
            <Select
              placeholder="Role"
              value={roleFilter}
              onChange={(e) => {
                setRoleFilter(e.target.value);
                setPage(0);
              }}
              options={[
                { value: "", label: "All roles" },
                ...roleOptions.map((r) => ({ value: r, label: r })),
              ]}
            />
          )}
          {cityOptions.length > 0 && (
            <Select
              placeholder="City"
              value={cityFilter}
              onChange={(e) => setCityFilter(e.target.value)}
              options={[
                { value: "", label: "All cities" },
                ...cityOptions.map((c) => ({ value: c, label: c })),
              ]}
            />
          )}
        </Toolbar>

        {surface === "map" && HAS_MAPS ? (
          <ResultsMap
            apiKey={MAPS_KEY}
            companies={rows
              .map((r) => r.company)
              .filter((c): c is Company => Boolean(c))}
            onSelect={openCompany}
          />
        ) : (
          <>
            <DataTable<Row>
              columns={columns}
              data={rows}
              loading={isLoading}
              getRowId={(r) => r.contact.id}
              onRowClick={(r) => openContact(r.contact.id)}
              enableSelection
              emptyState={
                <EmptyState
                  compact
                  icon={Table2}
                  title="No matching leads"
                  description={
                    view === "sales"
                      ? "No verified sales-ready contacts on this page. Switch to Raw mined or clear filters."
                      : "No contacts match the current filters."
                  }
                />
              }
              bulkActions={(selected) => (
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={revalidate.isPending}
                    onClick={() => onRevalidate(selected)}
                  >
                    Revalidate
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      toast.info(`Exporting ${selected.length} lead(s)`)
                    }
                  >
                    Export selection
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      router.push(
                        `/campaigns/new?contacts=${selected
                          .map((r) => r.contact.id)
                          .join(",")}`,
                      )
                    }
                  >
                    Add to campaign
                  </Button>
                </div>
              )}
            />

            {/* Server pager (bare arrays, no total-count header) */}
            <div className="mt-4 flex items-center justify-between">
              <MicroLabel>
                Page {page + 1} · showing {rows.length}
                {isFetching ? " · loading…" : ""}
              </MicroLabel>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  <ChevronLeft className="size-3.5" />
                  Prev
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={contacts.length < PAGE_SIZE}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                  <ChevronRight className="size-3.5" />
                </Button>
              </div>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}

function metricMatches(metric: MetricKey, r: Row): boolean {
  const s = (r.contact.final_email_status ?? "").toUpperCase();
  switch (metric) {
    case "companies":
    case "contacts":
      return true;
    case "emails":
      return Boolean(r.contact.email);
    case "verified":
      return s === "VERIFIED";
    case "review":
      return s.includes("REVIEW") || s === "CATCH_ALL_REVIEW" || s === "RISK_REVIEW";
    case "invalid":
      return (
        Boolean(r.contact.email) &&
        s !== "VERIFIED" &&
        !s.includes("REVIEW") &&
        s !== "PENDING" &&
        s !== ""
      );
    default:
      return true;
  }
}
