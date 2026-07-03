"use client";

import { useMemo } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { SERIES_COLORS, ChartTooltip } from "./theme";

export interface DonutDatum {
  label: string;
  value: number;
  color?: string;
}

interface DonutChartProps {
  data: DonutDatum[];
  height?: number;
  /** Center overline (mono micro-label). */
  centerLabel?: string;
  /** Center big value (defaults to sum). */
  centerValue?: string | number;
}

/**
 * DonutChart — dark-themed recharts donut with a center total and an inline
 * legend. Used for the source breakdown and validation-rejection breakdown.
 * Zero-total resolves to an empty ring so callers can render an EmptyState.
 */
export function DonutChart({
  data,
  height = 240,
  centerLabel,
  centerValue,
}: DonutChartProps) {
  const rows = useMemo(
    () =>
      data.map((d, i) => ({
        ...d,
        color: d.color ?? SERIES_COLORS[i % SERIES_COLORS.length],
      })),
    [data],
  );

  const total = useMemo(() => rows.reduce((a, r) => a + r.value, 0), [rows]);
  const displayValue =
    centerValue != null
      ? centerValue
      : Number.isFinite(total)
        ? total.toLocaleString()
        : "—";

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
      <div className="relative shrink-0" style={{ width: height, height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Tooltip
              cursor={false}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof rows)[number];
                const pct = total > 0 ? (p.value / total) * 100 : 0;
                return (
                  <ChartTooltip
                    rows={[
                      {
                        label: p.label,
                        value: `${p.value.toLocaleString()} (${pct.toFixed(1)}%)`,
                        color: p.color,
                      },
                    ]}
                  />
                );
              }}
            />
            <Pie
              data={rows}
              dataKey="value"
              nameKey="label"
              innerRadius="62%"
              outerRadius="100%"
              paddingAngle={total > 0 ? 2 : 0}
              stroke="rgba(0,0,0,0.4)"
              strokeWidth={1}
              isAnimationActive={false}
            >
              {rows.map((r, i) => (
                <Cell key={i} fill={r.color} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          {centerLabel && (
            <span className="font-mono text-[10px] font-medium uppercase tracking-wider text-muted">
              {centerLabel}
            </span>
          )}
          <span className="font-mono text-xl font-semibold tabular-nums text-ink">
            {displayValue}
          </span>
        </div>
      </div>
      <ul className="flex min-w-0 flex-1 flex-col gap-1.5">
        {rows.map((r, i) => {
          const pct = total > 0 ? (r.value / total) * 100 : 0;
          return (
            <li key={i} className="flex items-center justify-between gap-3 text-xs">
              <span className="flex min-w-0 items-center gap-2 text-muted">
                <span
                  className="inline-block size-2.5 shrink-0 rounded-[3px]"
                  style={{ backgroundColor: r.color }}
                />
                <span className="truncate text-ink">{r.label}</span>
              </span>
              <span className="shrink-0 font-mono tabular-nums text-muted">
                {r.value.toLocaleString()}
                <span className="ml-1.5 text-muted/60">{pct.toFixed(0)}%</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
