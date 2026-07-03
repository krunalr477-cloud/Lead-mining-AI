import type { ComponentType, ReactNode } from "react";
import { Inbox } from "lucide-react";
import type { LucideProps } from "lucide-react";
import { cn } from "@/lib/cn";
import { MicroLabel } from "./MicroLabel";

interface EmptyStateProps {
  icon?: ComponentType<LucideProps>;
  /** Mono kicker above the title. */
  kicker?: string;
  title: string;
  description?: ReactNode;
  /** Primary action(s). */
  action?: ReactNode;
  className?: string;
  /** Compact variant for inline table empties. */
  compact?: boolean;
}

/** Calm, centered empty/placeholder state used across every stub screen. */
export function EmptyState({
  icon: Icon = Inbox,
  kicker,
  title,
  description,
  action,
  className,
  compact = false,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "gap-3 py-10" : "gap-4 py-16",
        className,
      )}
    >
      <div className="flex size-12 items-center justify-center rounded-full border border-border bg-panel">
        <Icon className="size-5 text-muted" aria-hidden />
      </div>
      <div className="flex max-w-md flex-col items-center gap-2">
        {kicker && <MicroLabel className="text-accent/80">{kicker}</MicroLabel>}
        <h3 className="text-base font-semibold text-ink">{title}</h3>
        {description && <p className="text-sm leading-relaxed text-muted">{description}</p>}
      </div>
      {action && <div className="mt-1 flex items-center gap-2">{action}</div>}
    </div>
  );
}
