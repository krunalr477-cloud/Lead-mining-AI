import { ShieldCheck } from "lucide-react";
import { StatusChip, MicroLabel } from "@/components/ui";
import { formatNumber } from "@/lib/format";
import type { EligibilitySummary as EligibilityData } from "@/lib/api/schema";

interface EligibilitySummaryProps {
  data: EligibilityData;
  /** Compact read-only variant for the detail Settings tab. */
  compact?: boolean;
}

/** Excluded reasons in display order, each with its StatusChip variant. */
const EXCLUSION_ROWS: {
  key: keyof EligibilityData["excluded"];
  label: string;
  variant: "danger" | "review" | "warn";
}[] = [
  { key: "not_verified", label: "Not verified", variant: "review" },
  { key: "suppressed", label: "Suppressed", variant: "danger" },
  { key: "bounced", label: "Bounced", variant: "danger" },
  { key: "unsubscribed", label: "Unsubscribed", variant: "danger" },
  { key: "role_based", label: "Role-based", variant: "warn" },
];

/**
 * Recipient eligibility summary. Enforces the hard rule (§13): only VERIFIED
 * contacts can be targeted. Every non-verified contact is counted under an
 * excluded reason so the eligible number is provably VERIFIED-only, and the
 * rule is restated inline.
 */
export function EligibilitySummary({ data, compact }: EligibilitySummaryProps) {
  const excludedTotal = Object.values(data.excluded).reduce((a, b) => a + b, 0);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <MicroLabel>Eligible recipients</MicroLabel>
          <span className="font-mono text-2xl font-semibold tabular-nums text-accent">
            {formatNumber(data.eligible)}
          </span>
        </div>
        <div className="flex flex-col items-end gap-1">
          <MicroLabel>Excluded</MicroLabel>
          <span className="font-mono text-lg font-semibold tabular-nums text-muted">
            {formatNumber(excludedTotal)}
          </span>
        </div>
      </div>

      <div className="flex flex-col divide-y divide-border rounded-[8px] border border-border">
        {EXCLUSION_ROWS.map((row) => (
          <div
            key={row.key}
            className="flex items-center justify-between gap-2 px-3 py-2"
          >
            <StatusChip variant={row.variant} label={row.label} />
            <span className="font-mono text-sm tabular-nums text-muted">
              {formatNumber(data.excluded[row.key])}
            </span>
          </div>
        ))}
      </div>

      {!compact && (
        <div className="flex items-start gap-2 rounded-[8px] border border-accent/25 bg-accent/5 px-3 py-2">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" />
          <p className="text-xs leading-relaxed text-muted">
            <span className="font-medium text-ink">Only VERIFIED contacts can be targeted.</span>{" "}
            Invalid, review, suppressed, bounced, and unsubscribed contacts are
            hard-excluded before send and cannot be overridden.
          </p>
        </div>
      )}
    </div>
  );
}
