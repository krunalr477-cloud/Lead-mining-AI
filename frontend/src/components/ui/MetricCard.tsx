import type { ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/cn";
import { MicroLabel } from "./MicroLabel";

interface MetricCardProps {
  /** Mono caption above the value. */
  label: string;
  /** Large tabular value (pre-formatted string or number). */
  value: ReactNode;
  /** Optional delta — positive is accent, negative is danger, unless inverted. */
  delta?: {
    value: string;
    direction: "up" | "down" | "flat";
    /** When true, "down" is good (e.g. bounce rate) so colors flip. */
    invert?: boolean;
  };
  /** Small trailing hint under the value. */
  hint?: string;
  icon?: ReactNode;
  className?: string;
}

/**
 * MetricCard — mono caption + large tabular value + optional delta. NOT a
 * nested Panel: it's a bare block meant to sit inside a Panel/grid, honoring
 * the "no nested cards" rule.
 */
export function MetricCard({ label, value, delta, hint, icon, className }: MetricCardProps) {
  const deltaGood =
    delta?.direction === "flat"
      ? null
      : delta
        ? (delta.direction === "up") !== Boolean(delta.invert)
        : null;

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-center justify-between gap-2">
        <MicroLabel>{label}</MicroLabel>
        {icon && <span className="text-muted/70">{icon}</span>}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-2xl font-semibold tabular-nums text-ink sm:text-[28px] sm:leading-none">
          {value}
        </span>
        {delta && (
          <span
            className="inline-flex items-center gap-0.5 font-mono text-xs font-medium"
            style={{
              color:
                deltaGood == null
                  ? "var(--color-muted)"
                  : deltaGood
                    ? "var(--color-accent)"
                    : "var(--color-danger)",
            }}
          >
            {delta.direction === "up" && <ArrowUpRight className="size-3" />}
            {delta.direction === "down" && <ArrowDownRight className="size-3" />}
            {delta.value}
          </span>
        )}
      </div>
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </div>
  );
}
