"use client";

import { useMemo, useState } from "react";
import { Tooltip } from "radix-ui";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { Toolbar } from "@/components/ui/Toolbar";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { StatusChip } from "@/components/ui/StatusChip";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import {
  useContactMap,
  useJobs,
  useRevalidate,
  useValidationRows,
} from "@/lib/api/hooks";
import type { Contact, ValidationRow } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { formatConfidencePct } from "@/lib/entities";
import { useEntityLinks } from "@/components/entities/use-entity-links";
import {
  ValidationGlyph,
  ValidationLegend,
} from "@/components/entities/validation-glyph";

const STAGES: { key: keyof ValidationRow; label: string }[] = [
  { key: "syntax_status", label: "Syntax" },
  { key: "disposable_status", label: "Disposable" },
  { key: "role_based_status", label: "Role" },
  { key: "mx_status", label: "MX" },
];

interface JoinedRow {
  row: ValidationRow;
  contact: Contact | undefined;
}

function isReviewFinal(status: string | null | undefined): boolean {
  const s = (status ?? "").toUpperCase();
  return s.includes("REVIEW") || s === "PENDING" || s === "UNKNOWN_RETRY";
}

export function ValidationView({ initialJobId }: { initialJobId?: string }) {
  const toast = useToast();
  const { openContact } = useEntityLinks();
  const revalidate = useRevalidate();

  const { data: jobs = [] } = useJobs();
  const [jobId, setJobId] = useState(initialJobId ?? "");

  // Default to the first job with results once jobs load.
  const effectiveJobId = jobId || jobs[0]?.id || "";

  const { data: rawRows = [], isLoading } = useValidationRows(
    effectiveJobId || null,
    { limit: 200 },
  );
  const { data: contactMap = {} } = useContactMap(effectiveJobId || null);

  const [finalFilter, setFinalFilter] = useState("");
  const [onlyReview, setOnlyReview] = useState(false);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const rows = useMemo<JoinedRow[]>(() => {
    let list: JoinedRow[] = rawRows.map((r) => ({
      row: r,
      contact: contactMap[r.contact_id],
    }));
    if (onlyReview) list = list.filter((j) => isReviewFinal(j.row.final_status));
    if (finalFilter)
      list = list.filter((j) => (j.row.final_status ?? "") === finalFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (j) =>
          (j.contact?.email ?? "").toLowerCase().includes(q) ||
          (j.contact?.full_name ?? "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [rawRows, contactMap, onlyReview, finalFilter, search]);

  const selectedIds = Object.keys(selected).filter((k) => selected[k]);
  const allSelected = rows.length > 0 && rows.every((r) => selected[r.row.id]);

  const toggleAll = () => {
    if (allSelected) setSelected({});
    else setSelected(Object.fromEntries(rows.map((r) => [r.row.id, true])));
  };

  const finalStatusOptions = useMemo(() => {
    const set = new Set<string>();
    for (const r of rawRows) if (r.final_status) set.add(r.final_status);
    return [...set].sort();
  }, [rawRows]);

  const runRevalidate = () => {
    // Map selected validation-row ids -> their contact ids.
    const rowById = new Map(rawRows.map((r) => [r.id, r]));
    const contactIds = Array.from(
      new Set(
        selectedIds
          .map((id) => rowById.get(id)?.contact_id)
          .filter((v): v is string => Boolean(v)),
      ),
    );
    if (!contactIds.length) return;
    revalidate.mutate(
      { contact_ids: contactIds },
      {
        onSuccess: () => {
          toast.info(`Revalidating ${contactIds.length} contact(s)`);
          setSelected({});
        },
        onError: () => toast.error("Revalidation failed"),
      },
    );
  };

  const jobOptions = [
    { value: "", label: jobs.length ? "Select a job…" : "No jobs" },
    ...jobs.map((j) => ({ value: j.id, label: j.name })),
  ];

  return (
    <div className="flex flex-col gap-5">
      <Panel>
        <PanelHeader
          actions={
            <Button
              size="sm"
              variant="secondary"
              disabled={!selectedIds.length || revalidate.isPending}
              onClick={runRevalidate}
            >
              <RefreshCw
                className={revalidate.isPending ? "size-3.5 animate-spin" : "size-3.5"}
              />
              Revalidate{selectedIds.length ? ` (${selectedIds.length})` : ""}
            </Button>
          }
        >
          <h2 className="text-base font-semibold text-ink">Validation Pipeline</h2>
          <MicroLabel>Per-stage email verification</MicroLabel>
        </PanelHeader>

        <Toolbar className="mb-3">
          <Select
            value={effectiveJobId}
            onChange={(e) => {
              setJobId(e.target.value);
              setSelected({});
            }}
            options={jobOptions}
            className="min-w-[200px]"
          />
          <Input
            placeholder="Search email or name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full max-w-xs"
          />
          <Select
            value={finalFilter}
            onChange={(e) => setFinalFilter(e.target.value)}
            options={[
              { value: "", label: "All final statuses" },
              ...finalStatusOptions.map((s) => ({ value: s, label: s })),
            ]}
          />
          <button
            type="button"
            onClick={() => setOnlyReview((v) => !v)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors",
              onlyReview
                ? "border-[var(--color-review)]/50 text-[var(--color-review)]"
                : "border-border text-muted hover:text-ink",
            )}
            style={
              onlyReview
                ? {
                    backgroundColor:
                      "color-mix(in srgb, var(--color-review) 12%, transparent)",
                  }
                : undefined
            }
          >
            Only review
          </button>
        </Toolbar>

        <ValidationLegend className="mb-4" />

        {isLoading ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-11 w-full" />
            ))}
          </div>
        ) : !effectiveJobId ? (
          <EmptyState
            icon={ShieldCheck}
            title="Select a job"
            description="Choose a mining job to inspect its per-stage validation results."
          />
        ) : rows.length === 0 ? (
          <EmptyState
            compact
            icon={ShieldCheck}
            title="No validation rows"
            description="No email candidates match the current filters for this job."
          />
        ) : (
          <div className="overflow-x-auto lm-scroll">
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 z-10">
                <tr className="border-b border-border bg-[var(--color-surface-1)]">
                  <th className="sticky left-0 z-20 w-9 bg-[var(--color-surface-1)] px-3 py-2.5">
                    <input
                      type="checkbox"
                      aria-label="Select all"
                      className="lm-checkbox"
                      checked={allSelected}
                      ref={(el) => {
                        if (el)
                          el.indeterminate = !allSelected && selectedIds.length > 0;
                      }}
                      onChange={toggleAll}
                    />
                  </th>
                  <th className="sticky left-9 z-20 min-w-[220px] bg-[var(--color-surface-1)] px-3 py-2.5 text-left">
                    <MicroLabel as="span">Contact / Email</MicroLabel>
                  </th>
                  {STAGES.map((s) => (
                    <th key={s.key} className="px-3 py-2.5 text-center">
                      <MicroLabel as="span">{s.label}</MicroLabel>
                    </th>
                  ))}
                  <th className="px-3 py-2.5 text-center">
                    <MicroLabel as="span">LLM</MicroLabel>
                  </th>
                  <th className="px-3 py-2.5 text-center">
                    <MicroLabel as="span">Provider</MicroLabel>
                  </th>
                  <th className="px-3 py-2.5 text-left">
                    <MicroLabel as="span">Final</MicroLabel>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ row, contact }) => {
                  const isSel = Boolean(selected[row.id]);
                  return (
                    <tr
                      key={row.id}
                      onClick={() => openContact(row.contact_id)}
                      className={cn(
                        "cursor-pointer border-b border-border/60 transition-colors hover:bg-[var(--color-panel)]",
                        isSel &&
                          "bg-[color-mix(in_srgb,var(--color-accent)_8%,transparent)]",
                      )}
                    >
                      <td
                        className="sticky left-0 z-10 bg-[var(--color-surface-2)] px-3 py-3"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          aria-label="Select row"
                          className="lm-checkbox"
                          checked={isSel}
                          onChange={(e) =>
                            setSelected((prev) => ({
                              ...prev,
                              [row.id]: e.target.checked,
                            }))
                          }
                        />
                      </td>
                      <td className="sticky left-9 z-10 min-w-[220px] bg-[var(--color-surface-2)] px-3 py-3">
                        <div className="flex flex-col">
                          <span className="truncate text-ink">
                            {contact?.full_name ?? "Unknown contact"}
                          </span>
                          <span className="truncate font-mono text-[11px] text-muted">
                            {contact?.email ?? "—"}
                          </span>
                        </div>
                      </td>
                      {STAGES.map((s) => (
                        <td key={s.key} className="px-3 py-3 text-center">
                          <div className="flex justify-center">
                            <ValidationGlyph
                              status={row[s.key] as string}
                              tip={`${s.label}: ${row[s.key] ?? "pending"}`}
                            />
                          </div>
                        </td>
                      ))}
                      {/* LLM score + reason tooltip */}
                      <td className="px-3 py-3 text-center">
                        <LlmCell row={row} />
                      </td>
                      {/* MillionVerifier provider */}
                      <td className="px-3 py-3 text-center">
                        <div className="flex justify-center">
                          <ValidationGlyph
                            status={
                              row.millionverifier_status
                                ? mvGlyph(row.millionverifier_status)
                                : "skip"
                            }
                            tip={`Provider: ${row.millionverifier_status ?? "n/a"}`}
                          />
                        </div>
                      </td>
                      {/* Final decision */}
                      <td className="px-3 py-3">
                        {row.final_status ? (
                          <Tooltip.Root>
                            <Tooltip.Trigger asChild>
                              <span className="inline-flex cursor-help">
                                <StatusChip status={row.final_status} />
                              </span>
                            </Tooltip.Trigger>
                            {row.final_reason && (
                              <Tooltip.Portal>
                                <Tooltip.Content
                                  side="top"
                                  sideOffset={5}
                                  className="z-[70] max-w-xs rounded-[8px] border border-border bg-[var(--color-surface-2)] px-3 py-2 text-xs leading-relaxed text-muted shadow-[0_20px_50px_-20px_rgba(0,0,0,0.9)]"
                                >
                                  {row.final_reason}
                                  <Tooltip.Arrow className="fill-[var(--color-surface-2)]" />
                                </Tooltip.Content>
                              </Tooltip.Portal>
                            )}
                          </Tooltip.Root>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* Floating revalidate bar */}
      {selectedIds.length > 0 && (
        <div className="pointer-events-none sticky bottom-4 z-20 flex justify-center">
          <div className="pointer-events-auto flex items-center gap-3 rounded-full border border-border bg-[var(--color-surface-2)] px-4 py-2 shadow-[0_20px_50px_-20px_rgba(0,0,0,0.9)]">
            <MicroLabel className="text-accent">
              {selectedIds.length} selected
            </MicroLabel>
            <span className="h-4 w-px bg-border" />
            <Button
              size="sm"
              disabled={revalidate.isPending}
              onClick={runRevalidate}
            >
              <RefreshCw
                className={revalidate.isPending ? "size-3.5 animate-spin" : "size-3.5"}
              />
              Revalidate ({selectedIds.length})
            </Button>
            <button
              type="button"
              onClick={() => setSelected({})}
              className="font-mono text-[11px] uppercase tracking-wider text-muted hover:text-ink"
            >
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function LlmCell({ row }: { row: ValidationRow }) {
  if (row.llm_score == null) {
    return (
      <div className="flex justify-center">
        <ValidationGlyph status="skip" tip="LLM: not run" />
      </div>
    );
  }
  const score = Number(row.llm_score);
  const color =
    score >= 0.7
      ? "var(--color-accent)"
      : score >= 0.4
        ? "var(--color-warn)"
        : "var(--color-danger)";
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <span
          className="inline-flex cursor-help font-mono text-[13px]"
          style={{ color }}
        >
          {formatConfidencePct(row.llm_score)}
        </span>
      </Tooltip.Trigger>
      {row.llm_reason && (
        <Tooltip.Portal>
          <Tooltip.Content
            side="top"
            sideOffset={5}
            className="z-[70] max-w-xs rounded-[8px] border border-border bg-[var(--color-surface-2)] px-3 py-2 text-xs leading-relaxed text-muted shadow-[0_20px_50px_-20px_rgba(0,0,0,0.9)]"
          >
            {row.llm_reason}
            <Tooltip.Arrow className="fill-[var(--color-surface-2)]" />
          </Tooltip.Content>
        </Tooltip.Portal>
      )}
    </Tooltip.Root>
  );
}

/** MillionVerifier status string -> glyph kind. */
function mvGlyph(status: string): "pass" | "fail" | "review" | "skip" {
  const s = status.toLowerCase();
  if (s === "valid") return "pass";
  if (s === "invalid") return "fail";
  if (s === "catch_all" || s === "risk" || s === "unknown") return "review";
  return "skip";
}
