import { cn } from "@/lib/cn";
import { statusColor, type StatusVariant } from "@/lib/status";

interface ProgressBarProps {
  /** 0–100. */
  value: number;
  variant?: StatusVariant;
  /** Show a faint indeterminate pulse instead of a fixed width. */
  indeterminate?: boolean;
  className?: string;
}

/** Thin 2px progress track, accent fill by default. */
export function ProgressBar({
  value,
  variant = "accent",
  indeterminate = false,
  className,
}: ProgressBarProps) {
  const pct = Math.max(0, Math.min(100, value));
  const color = statusColor(variant);
  return (
    <div
      className={cn("h-0.5 w-full overflow-hidden rounded-full bg-[var(--color-border)]", className)}
      role="progressbar"
      aria-valuenow={indeterminate ? undefined : Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-500", indeterminate && "w-1/3 animate-pulse")}
        style={{
          width: indeterminate ? undefined : `${pct}%`,
          backgroundColor: color,
          boxShadow: `0 0 8px ${color}`,
        }}
      />
    </div>
  );
}
