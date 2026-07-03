"use client";

import type { ReactNode } from "react";

/**
 * Shared chart theme + a dark-themed tooltip used by every recharts wrapper in
 * this folder. Colors resolve to the same CSS variables as the rest of the app
 * (globals.css @theme) so charts stay on-palette with no hardcoded hex drift.
 *
 * NOTE: recharts reads stroke/fill as literal strings, so we resolve the spec
 * palette to concrete hex here (matching globals.css) — CSS var() strings do
 * not paint inside SVG <path fill> reliably across recharts primitives.
 */
export const CHART = {
  accent: "#00F0A8",
  accent2: "#00E69A",
  info: "#61D7FF",
  warn: "#F8C64E",
  danger: "#FF4D5E",
  review: "#9D7CFF",
  muted: "#7B8494",
  ink: "#F5F7FA",
  grid: "rgba(255,255,255,0.08)",
  axis: "#7B8494",
  surface: "#0E131A",
  border: "rgba(255,255,255,0.16)",
} as const;

/** Ordered categorical palette for multi-series / slices. */
export const SERIES_COLORS = [
  CHART.accent,
  CHART.info,
  CHART.review,
  CHART.warn,
  CHART.danger,
  CHART.accent2,
] as const;

/** Shared axis props (mono-ish small muted labels). */
export const axisProps = {
  stroke: CHART.axis,
  tick: { fill: CHART.axis, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: CHART.grid },
} as const;

interface TooltipRow {
  label: string;
  value: ReactNode;
  color?: string;
}

/**
 * ChartTooltip — dark glass tooltip. Pass a resolved title + rows; the recharts
 * wrappers adapt their raw payload into this shape so styling stays in one place.
 */
export function ChartTooltip({
  title,
  rows,
}: {
  title?: ReactNode;
  rows: TooltipRow[];
}) {
  return (
    <div
      className="min-w-[140px] rounded-[10px] border border-[var(--color-border-strong)] bg-[var(--color-surface-2)] px-3 py-2 shadow-[0_10px_30px_-12px_rgba(0,0,0,0.9)]"
      style={{ backdropFilter: "blur(4px)" }}
    >
      {title != null && (
        <div className="mb-1.5 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
          {title}
        </div>
      )}
      <div className="flex flex-col gap-1">
        {rows.map((r, i) => (
          <div
            key={i}
            className="flex items-center justify-between gap-4 text-xs text-ink"
          >
            <span className="flex items-center gap-1.5 text-muted">
              {r.color && (
                <span
                  className="inline-block size-2 rounded-[3px]"
                  style={{ backgroundColor: r.color }}
                />
              )}
              {r.label}
            </span>
            <span className="font-mono tabular-nums text-ink">{r.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
