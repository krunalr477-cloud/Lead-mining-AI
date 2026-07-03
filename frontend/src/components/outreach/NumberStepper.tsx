"use client";

import { Minus, Plus } from "lucide-react";
import { cn } from "@/lib/cn";

interface NumberStepperProps {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  disabled?: boolean;
  className?: string;
}

/** Compact +/- numeric stepper for rate-limit controls. */
export function NumberStepper({
  value,
  onChange,
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
  step = 1,
  suffix,
  disabled,
  className,
}: NumberStepperProps) {
  const clamp = (n: number) => Math.max(min, Math.min(max, n));
  return (
    <div
      className={cn(
        "flex h-9 items-center rounded-[8px] border border-border bg-[var(--color-surface-1)]",
        disabled && "opacity-50",
        className,
      )}
    >
      <button
        type="button"
        aria-label="Decrease"
        disabled={disabled || value <= min}
        onClick={() => onChange(clamp(value - step))}
        className="flex h-full w-8 items-center justify-center text-muted transition-colors hover:text-ink disabled:opacity-40 lm-focus"
      >
        <Minus className="size-3.5" />
      </button>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        disabled={disabled}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n)) onChange(clamp(n));
        }}
        className="h-full w-full min-w-0 border-x border-border bg-transparent px-2 text-center font-mono text-sm tabular-nums text-ink outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
      />
      <div className="flex h-full items-center">
        {suffix && (
          <span className="px-2 font-mono text-[10px] uppercase tracking-wider text-muted">
            {suffix}
          </span>
        )}
        <button
          type="button"
          aria-label="Increase"
          disabled={disabled || value >= max}
          onClick={() => onChange(clamp(value + step))}
          className="flex h-full w-8 items-center justify-center text-muted transition-colors hover:text-ink disabled:opacity-40 lm-focus"
        >
          <Plus className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
