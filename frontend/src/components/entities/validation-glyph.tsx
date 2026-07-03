"use client";

import { Tooltip } from "radix-ui";
import { Check, Minus, X } from "lucide-react";
import { cn } from "@/lib/cn";
import type { ValidationStageStatus } from "@/lib/api/schema";

/**
 * ValidationGlyph — the single per-stage pass/fail/review/pending mark used in
 * the Validation Pipeline stage columns AND the contact-drawer mini-timeline.
 *   pass    -> accent check
 *   fail    -> danger x
 *   review  -> review ~ (tilde)
 *   skip / unknown / pending -> muted dot
 */
const GLYPH: Record<
  "pass" | "fail" | "review" | "pending",
  { color: string; node: React.ReactNode; label: string }
> = {
  pass: {
    color: "var(--color-accent)",
    node: <Check className="size-3.5" strokeWidth={2.5} />,
    label: "Pass",
  },
  fail: {
    color: "var(--color-danger)",
    node: <X className="size-3.5" strokeWidth={2.5} />,
    label: "Fail",
  },
  review: {
    color: "var(--color-review)",
    node: <span className="font-mono text-[13px] leading-none">~</span>,
    label: "Review",
  },
  pending: {
    color: "var(--color-muted)",
    node: <Minus className="size-3 opacity-70" strokeWidth={2.5} />,
    label: "Pending",
  },
};

/** Normalize a stage status onto one of the four glyph kinds. */
export function glyphKind(
  status: ValidationStageStatus | string | null | undefined,
): "pass" | "fail" | "review" | "pending" {
  const s = (status ?? "").toLowerCase();
  if (s === "pass") return "pass";
  if (s === "fail") return "fail";
  if (s === "review" || s === "catch_all" || s === "risk") return "review";
  return "pending"; // skip / unknown / null
}

interface ValidationGlyphProps {
  status: ValidationStageStatus | string | null | undefined;
  /** Tooltip label (defaults to the glyph kind). */
  tip?: string;
  className?: string;
}

export function ValidationGlyph({ status, tip, className }: ValidationGlyphProps) {
  const kind = glyphKind(status);
  const meta = GLYPH[kind];
  const label = tip ?? meta.label;
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <span
          className={cn(
            "inline-flex size-5 items-center justify-center rounded-full",
            className,
          )}
          style={{
            color: meta.color,
            backgroundColor: "color-mix(in srgb, currentColor 12%, transparent)",
          }}
          aria-label={label}
        >
          {meta.node}
        </span>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="top"
          sideOffset={5}
          className="z-[70] max-w-xs rounded-[8px] border border-border bg-[var(--color-surface-2)] px-2.5 py-1.5 text-xs text-ink shadow-[0_20px_50px_-20px_rgba(0,0,0,0.9)]"
        >
          {label}
          <Tooltip.Arrow className="fill-[var(--color-surface-2)]" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

/** Legend row of the four glyph meanings, for the pipeline header. */
export function ValidationLegend({ className }: { className?: string }) {
  const items: { kind: keyof typeof GLYPH; label: string }[] = [
    { kind: "pass", label: "Pass" },
    { kind: "fail", label: "Fail" },
    { kind: "review", label: "Review" },
    { kind: "pending", label: "Pending / Skipped" },
  ];
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-2", className)}>
      {items.map(({ kind, label }) => {
        const meta = GLYPH[kind];
        return (
          <span key={kind} className="inline-flex items-center gap-1.5">
            <span
              className="inline-flex size-4 items-center justify-center rounded-full"
              style={{
                color: meta.color,
                backgroundColor:
                  "color-mix(in srgb, currentColor 12%, transparent)",
              }}
            >
              {meta.node}
            </span>
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted">
              {label}
            </span>
          </span>
        );
      })}
    </div>
  );
}
