"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CHART, SERIES_COLORS, axisProps, ChartTooltip } from "./theme";

export interface BarSeries {
  /** Key into each row object. */
  key: string;
  /** Legend / tooltip label. */
  label: string;
  /** Bar color (defaults to categorical palette by index). */
  color?: string;
}

interface BarsChartProps<Row extends Record<string, unknown>> {
  data: Row[];
  /** Category axis key (x for vertical bars, y for horizontal). */
  categoryKey: string;
  series: BarSeries[];
  height?: number;
  /** Stack all series into one bar. */
  stacked?: boolean;
  /** Horizontal (categories down the y-axis) — good for named rows. */
  layout?: "vertical" | "horizontal";
  /** Per-bar color override keyed by category value (single-series only). */
  colorByCategory?: (row: Row) => string;
}

/**
 * BarsChart — dark-themed grouped/stacked recharts <BarChart>. Handles both
 * vertical (time/campaign columns) and horizontal (named source rows) layouts.
 * Used for campaign performance (grouped/stacked) and source breakdown (bars).
 */
export function BarsChart<Row extends Record<string, unknown>>({
  data,
  categoryKey,
  series,
  height = 260,
  stacked = false,
  layout = "vertical",
  colorByCategory,
}: BarsChartProps<Row>) {
  const isHorizontal = layout === "horizontal";

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout={isHorizontal ? "vertical" : "horizontal"}
        margin={{ top: 8, right: 12, bottom: 4, left: isHorizontal ? 12 : 0 }}
        barCategoryGap={stacked ? "24%" : "18%"}
      >
        <CartesianGrid stroke={CHART.grid} vertical={isHorizontal} horizontal={!isHorizontal} />
        {isHorizontal ? (
          <>
            <XAxis type="number" {...axisProps} />
            <YAxis
              type="category"
              dataKey={categoryKey}
              width={116}
              {...axisProps}
            />
          </>
        ) : (
          <>
            <XAxis type="category" dataKey={categoryKey} {...axisProps} interval={0} />
            <YAxis type="number" {...axisProps} width={36} />
          </>
        )}
        <Tooltip
          cursor={{ fill: "rgba(255,255,255,0.04)" }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            return (
              <ChartTooltip
                title={String(label)}
                rows={payload.map((p) => ({
                  label: String(p.name),
                  value: Number(p.value ?? 0).toLocaleString(),
                  color: p.color as string,
                }))}
              />
            );
          }}
        />
        {series.map((s, i) => {
          const color = s.color ?? SERIES_COLORS[i % SERIES_COLORS.length];
          return (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              stackId={stacked ? "s" : undefined}
              fill={color}
              radius={stacked ? 0 : isHorizontal ? [0, 3, 3, 0] : [3, 3, 0, 0]}
              isAnimationActive={false}
            >
              {colorByCategory &&
                data.map((row, ri) => (
                  <Cell key={ri} fill={colorByCategory(row)} />
                ))}
            </Bar>
          );
        })}
      </BarChart>
    </ResponsiveContainer>
  );
}
