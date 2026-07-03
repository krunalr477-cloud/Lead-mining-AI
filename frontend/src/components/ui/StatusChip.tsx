import { cn } from "@/lib/cn";
import { resolveStatus, statusColor, type StatusVariant } from "@/lib/status";

interface StatusChipProps {
  /** Raw backend status string OR a pre-resolved variant via `variant`. */
  status?: string | null;
  /** Override the resolved variant. */
  variant?: StatusVariant;
  /** Override the label (defaults to humanized status). */
  label?: string;
  /** Hide the LED dot. */
  hideDot?: boolean;
  className?: string;
}

/**
 * StatusChip — mono uppercase micro-label + LED dot, tinted per the SINGLE
 * status source of truth (lib/status.ts). Text uses currentColor tint at
 * reduced opacity; the dot is full-strength.
 */
export function StatusChip({
  status,
  variant,
  label,
  hideDot = false,
  className,
}: StatusChipProps) {
  const meta = resolveStatus(status);
  const color = variant ? statusColor(variant) : meta.color;
  const text = label ?? meta.label;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5",
        "font-mono text-[11px] font-medium uppercase tracking-wider",
        className,
      )}
      style={{
        color,
        borderColor: "color-mix(in srgb, currentColor 28%, transparent)",
        backgroundColor: "color-mix(in srgb, currentColor 10%, transparent)",
      }}
    >
      {!hideDot && (
        <span
          className="inline-block size-1.5 rounded-full"
          style={{ backgroundColor: "currentColor", boxShadow: "0 0 6px currentColor" }}
          aria-hidden
        />
      )}
      {text}
    </span>
  );
}
