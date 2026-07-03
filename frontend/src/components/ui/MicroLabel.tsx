import type { ElementType, ComponentPropsWithoutRef } from "react";
import { cn } from "@/lib/cn";

/**
 * MicroLabel — the identity element of LeadMine AI.
 *
 * Mono, 11px, uppercase, wide tracking, muted. ALL small system/status/ID/
 * counter-caption text funnels through this component so the monospace
 * micro-label voice stays consistent everywhere. Never apply negative
 * letter-spacing (spec prohibition) — tracking is always positive.
 */
type MicroLabelProps<T extends ElementType> = {
  as?: T;
  className?: string;
} & Omit<ComponentPropsWithoutRef<T>, "as" | "className">;

export function MicroLabel<T extends ElementType = "span">({
  as,
  className,
  ...props
}: MicroLabelProps<T>) {
  const Component = (as ?? "span") as ElementType;
  return (
    <Component
      className={cn(
        "font-mono text-[11px] font-medium uppercase tracking-wider text-muted",
        className,
      )}
      {...props}
    />
  );
}
