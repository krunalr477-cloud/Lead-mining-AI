"use client";

import { Popover } from "radix-ui";
import { TriangleAlert } from "lucide-react";
import { cn } from "@/lib/cn";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { StatusChip } from "@/components/ui/StatusChip";
import { useDemoMode } from "@/lib/demo";
import type { ProviderKey } from "@/lib/api/schema";

const PROVIDER_LABELS: Record<ProviderKey, string> = {
  google_maps: "Google Maps",
  rocketreach: "RocketReach",
  millionverifier: "MillionVerifier",
  groq: "Groq LLM",
  serp: "SERP / Jobs",
  gmail: "Gmail",
  sheets: "Google Sheets",
};

/**
 * Amber dashed "DEMO MODE — MOCK ADAPTERS ACTIVE" chip. Clicking opens a
 * popover listing each provider's live/mock status. Hidden entirely when the
 * backend reports demo_mode=false and no provider is mocked.
 */
export function DemoRibbon() {
  const { demoMode, providers, mockProviders, isLoading } = useDemoMode();

  if (isLoading) return null;
  if (!demoMode && mockProviders.length === 0) return null;

  const keys = Object.keys(providers) as ProviderKey[];

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1",
            "font-mono text-[11px] font-medium uppercase tracking-wider",
            "border-[var(--color-warn)]/50 text-[var(--color-warn)] hover:bg-[var(--color-warn)]/10 lm-focus",
          )}
        >
          <TriangleAlert className="size-3" />
          <span className="hidden sm:inline">Demo Mode — Mock Adapters Active</span>
          <span className="sm:hidden">Demo Mode</span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          className="z-[70] w-72 rounded-[10px] border border-border bg-[var(--color-surface-2)] p-3 shadow-[0_20px_50px_-20px_rgba(0,0,0,0.9)]"
        >
          <div className="mb-2 flex flex-col gap-1">
            <MicroLabel className="text-[var(--color-warn)]">Adapter Status</MicroLabel>
            <p className="text-xs leading-relaxed text-muted">
              Providers marked <span className="text-[var(--color-warn)]">mock</span> return demo
              data. Connect real keys in Settings → Integrations to go live.
            </p>
          </div>
          <ul className="flex flex-col divide-y divide-border">
            {keys.map((k) => (
              <li key={k} className="flex items-center justify-between gap-2 py-2">
                <span className="text-sm text-ink">{PROVIDER_LABELS[k]}</span>
                <StatusChip status={providers[k]} />
              </li>
            ))}
          </ul>
          <Popover.Arrow className="fill-[var(--color-surface-2)]" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
