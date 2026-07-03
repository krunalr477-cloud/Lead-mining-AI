"use client";

import { Tooltip } from "radix-ui";
import { Check, Lock } from "lucide-react";
import { cn } from "@/lib/cn";
import { ComplianceBadge } from "@/components/ui";
import type { CompliancePosture } from "@/components/ui/ComplianceBadge";

/** Compliance tier -> selectability policy. */
export type SourceTier = "green" | "amber" | "red";

export interface SourceDef {
  /** Backend source key (what /jobs/estimate + /jobs expect). */
  key: string;
  label: string;
  tier: SourceTier;
  /** Legal / posture note shown in the badge tooltip. */
  note: string;
  /** Extra sublabel under the source name (e.g. Facebook access caveat). */
  caveat?: string;
}

const TIER_TO_POSTURE: Record<SourceTier, CompliancePosture> = {
  green: "official",
  amber: "gated",
  red: "disabled",
};

interface SourceChipsProps {
  sources: SourceDef[];
  selected: string[];
  onChange: (next: string[]) => void;
  /**
   * Whether an amber source is enabled for this tenant. Amber chips are only
   * selectable when this returns true; otherwise they render disabled with the
   * "Compliance-gated — enable in Data Source settings" tooltip. Red chips are
   * always disabled regardless.
   */
  isAmberEnabled: (key: string) => boolean;
}

export function SourceChips({
  sources,
  selected,
  onChange,
  isAmberEnabled,
}: SourceChipsProps) {
  const toggle = (key: string) =>
    onChange(
      selected.includes(key)
        ? selected.filter((k) => k !== key)
        : [...selected, key],
    );

  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {sources.map((s) => {
        const amberBlocked = s.tier === "amber" && !isAmberEnabled(s.key);
        const disabled = s.tier === "red" || amberBlocked;
        const active = selected.includes(s.key);

        const disabledTip =
          s.tier === "red"
            ? s.note
            : "Compliance-gated — enable in Data Source settings.";

        const chip = (
          <button
            type="button"
            role="checkbox"
            aria-checked={active}
            aria-disabled={disabled}
            disabled={disabled}
            onClick={() => !disabled && toggle(s.key)}
            className={cn(
              "flex w-full flex-col gap-2 rounded-[10px] border p-3 text-left transition-colors lm-focus",
              disabled
                ? "cursor-not-allowed border-border bg-[var(--color-surface-1)]/50 opacity-60"
                : active
                  ? "border-[var(--color-accent)]/50 bg-[var(--color-accent)]/8"
                  : "border-border bg-panel hover:border-[var(--color-border-strong)]",
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <span
                  className={cn(
                    "flex size-4 shrink-0 items-center justify-center rounded-[5px] border",
                    active
                      ? "border-[var(--color-accent)] bg-[var(--color-accent)] text-[#04120C]"
                      : "border-[var(--color-border-strong)]",
                  )}
                  aria-hidden
                >
                  {active && <Check className="size-3" strokeWidth={3} />}
                  {disabled && !active && <Lock className="size-2.5 text-muted" />}
                </span>
                <span className="min-w-0 truncate text-sm font-medium text-ink">
                  {s.label}
                </span>
              </div>
            </div>
            <div className="flex items-center justify-between gap-2">
              {s.caveat ? (
                <span className="truncate text-[11px] text-muted">{s.caveat}</span>
              ) : (
                <span />
              )}
              {/* Badge is decorative here; wrap in span so button click still toggles. */}
              <span className="shrink-0" onClick={(e) => e.stopPropagation()}>
                <ComplianceBadge
                  posture={TIER_TO_POSTURE[s.tier]}
                  note={s.note}
                />
              </span>
            </div>
          </button>
        );

        if (!disabled) return <div key={s.key}>{chip}</div>;

        return (
          <Tooltip.Root key={s.key}>
            <Tooltip.Trigger asChild>
              <div>{chip}</div>
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content
                side="top"
                sideOffset={6}
                className="z-[60] max-w-xs rounded-[8px] border border-border bg-[var(--color-surface-2)] px-3 py-2 text-xs leading-relaxed text-muted shadow-[0_20px_50px_-20px_rgba(0,0,0,0.9)]"
              >
                {disabledTip}
                <Tooltip.Arrow className="fill-[var(--color-surface-2)]" />
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
        );
      })}
    </div>
  );
}
