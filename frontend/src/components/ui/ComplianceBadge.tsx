"use client";

import { Tooltip } from "radix-ui";
import { cn } from "@/lib/cn";

export type CompliancePosture = "official" | "gated" | "disabled";

interface ComplianceBadgeProps {
  posture: CompliancePosture;
  /** Legal note shown in the tooltip. */
  note?: string;
  className?: string;
}

const POSTURE_META: Record<
  CompliancePosture,
  { label: string; color: string; defaultNote: string }
> = {
  official: {
    label: "OFFICIAL API",
    color: "var(--color-accent)",
    defaultNote: "Accessed via an official or licensed API. Cleared for use.",
  },
  gated: {
    label: "GATED",
    color: "var(--color-warn)",
    defaultNote:
      "Compliance-gated source. Requires admin/legal sign-off before enabling. Availability depends on approved access.",
  },
  disabled: {
    label: "DISABLED",
    color: "var(--color-danger)",
    defaultNote:
      "Disabled by policy. No scraping of authenticated or private content is permitted.",
  },
};

/**
 * ComplianceBadge — LED dot + mono posture label, with a Radix Tooltip carrying
 * the legal note. Green = official/licensed, amber = compliance-gated, red =
 * disabled. Enforces the spec's per-source compliance labeling.
 */
export function ComplianceBadge({ posture, note, className }: ComplianceBadgeProps) {
  const meta = POSTURE_META[posture];
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <span
          className={cn(
            "inline-flex cursor-help items-center gap-1.5 rounded-full border px-2 py-0.5",
            "font-mono text-[11px] font-medium uppercase tracking-wider",
            className,
          )}
          style={{
            color: meta.color,
            borderColor: "color-mix(in srgb, currentColor 30%, transparent)",
            backgroundColor: "color-mix(in srgb, currentColor 10%, transparent)",
          }}
        >
          <span
            className="inline-block size-1.5 rounded-full"
            style={{ backgroundColor: "currentColor", boxShadow: "0 0 6px currentColor" }}
            aria-hidden
          />
          {meta.label}
        </span>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="top"
          sideOffset={6}
          className="z-[60] max-w-xs rounded-[8px] border border-border bg-[var(--color-surface-2)] px-3 py-2 text-xs leading-relaxed text-muted shadow-[0_20px_50px_-20px_rgba(0,0,0,0.9)]"
        >
          {note ?? meta.defaultNote}
          <Tooltip.Arrow className="fill-[var(--color-surface-2)]" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
