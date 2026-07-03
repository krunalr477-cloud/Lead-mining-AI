import type { ReactNode, HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface ToolbarProps extends HTMLAttributes<HTMLDivElement> {
  /** Left cluster (filters, search). */
  children: ReactNode;
  /** Right cluster (actions). */
  actions?: ReactNode;
}

/** Horizontal control bar with a left content cluster and right actions. */
export function Toolbar({ className, children, actions, ...props }: ToolbarProps) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-3",
        className,
      )}
      {...props}
    >
      <div className="flex flex-1 flex-wrap items-center gap-2">{children}</div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
