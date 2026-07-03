"use client";

import { AlertTriangle, ShieldCheck, Loader2 } from "lucide-react";
import { Panel, MetricCard, MicroLabel } from "@/components/ui";
import { formatNumber, formatCurrency } from "@/lib/format";
import type { JobEstimate, ComplianceWarning } from "@/lib/api/schema";

function runtimeLabel(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const mins = Math.round(seconds / 60);
  if (mins < 90) return `${mins}m`;
  const hrs = Math.round((mins / 60) * 10) / 10;
  return `${hrs}h`;
}

function postureColor(posture: string): string {
  const p = posture.toLowerCase();
  if (p === "red") return "var(--color-danger)";
  if (p === "amber") return "var(--color-warn)";
  return "var(--color-muted)";
}

export function EstimatePanel({
  estimate,
  isLoading,
  error,
  ready,
}: {
  estimate: JobEstimate | null;
  isLoading: boolean;
  error: Error | null;
  /** False until the minimum fields for an estimate are present. */
  ready: boolean;
}) {
  const warnings: ComplianceWarning[] = estimate?.compliance_warnings ?? [];
  const companies = estimate
    ? estimate.estimated_companies_min === estimate.estimated_companies_max
      ? formatNumber(estimate.estimated_companies_max)
      : `${formatNumber(estimate.estimated_companies_min)}–${formatNumber(
          estimate.estimated_companies_max,
        )}`
    : "—";

  return (
    <Panel>
      <Panel.Header
        actions={
          isLoading ? (
            <span className="inline-flex items-center gap-1.5 text-muted">
              <Loader2 className="size-3.5 animate-spin" />
              <MicroLabel>Estimating</MicroLabel>
            </span>
          ) : null
        }
      >
        <MicroLabel>Estimate &amp; Compliance</MicroLabel>
        <h2 className="text-sm font-medium text-ink">Run preview</h2>
      </Panel.Header>

      {!ready ? (
        <p className="py-2 text-xs leading-relaxed text-muted">
          Enter a job name and select at least one data source to preview the
          estimated scope, cost, and compliance posture for this run.
        </p>
      ) : (
        <>
          {error && (
            <p className="mb-3 text-xs text-danger">
              Couldn&apos;t compute an estimate — {error.message}
            </p>
          )}

          <div className="grid grid-cols-2 gap-x-4 gap-y-4">
            <MetricCard label="Est. companies" value={companies} />
            <MetricCard
              label="Est. API cost"
              value={estimate ? formatCurrency(estimate.estimated_cost_usd) : "—"}
            />
            <MetricCard
              label="Est. runtime"
              value={estimate ? runtimeLabel(estimate.estimated_runtime_seconds) : "—"}
            />
            <div className="flex flex-col gap-1.5">
              <MicroLabel>Sheet target</MicroLabel>
              <span
                className="truncate font-mono text-xs text-ink"
                title={estimate?.sheet_target ?? ""}
              >
                {estimate?.sheet_target ?? "—"}
              </span>
            </div>
          </div>

          <Panel.Section divided>
            <div className="mb-2 flex items-center gap-2">
              {warnings.length === 0 ? (
                <ShieldCheck className="size-4 text-[var(--color-accent)]" />
              ) : (
                <AlertTriangle className="size-4 text-[var(--color-warn)]" />
              )}
              <MicroLabel>
                Compliance {warnings.length > 0 ? `(${warnings.length})` : "clear"}
              </MicroLabel>
            </div>

            {warnings.length === 0 ? (
              <p className="text-xs leading-relaxed text-muted">
                All selected sources are cleared for use via official or licensed
                access.
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {warnings.map((w) => {
                  const color = postureColor(w.posture);
                  return (
                    <li
                      key={`${w.source}-${w.posture}`}
                      className="flex gap-2.5 rounded-[8px] border border-border bg-[var(--color-surface-1)] p-2.5"
                    >
                      <span
                        className="mt-1 inline-block size-1.5 shrink-0 rounded-full"
                        style={{
                          backgroundColor: color,
                          boxShadow: `0 0 6px ${color}`,
                        }}
                        aria-hidden
                      />
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <span
                          className="font-mono text-[11px] font-medium uppercase tracking-wider"
                          style={{ color }}
                        >
                          {w.source} · {w.posture}
                        </span>
                        <span className="text-xs leading-relaxed text-muted">
                          {w.message}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel.Section>
        </>
      )}
    </Panel>
  );
}
