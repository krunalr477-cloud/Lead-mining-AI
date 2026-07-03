"use client";

import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

const baseControl = cn(
  "h-9 w-full rounded-[8px] border border-border bg-[var(--color-surface-1)] px-3 text-sm text-ink",
  "placeholder:text-muted/70 transition-colors lm-focus",
  "hover:border-[var(--color-border-strong)]",
  "focus:border-[var(--color-accent)]/60 focus:bg-[var(--color-surface-2)]",
  "disabled:opacity-50 disabled:cursor-not-allowed",
);

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Leading adornment (icon). */
  leading?: ReactNode;
  invalid?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, leading, invalid, ...props },
  ref,
) {
  if (leading) {
    return (
      <div className="relative flex items-center">
        <span className="pointer-events-none absolute left-3 text-muted">{leading}</span>
        <input
          ref={ref}
          className={cn(baseControl, "pl-9", invalid && "border-danger/60", className)}
          {...props}
        />
      </div>
    );
  }
  return (
    <input
      ref={ref}
      className={cn(baseControl, invalid && "border-danger/60", className)}
      {...props}
    />
  );
});

export { baseControl };
