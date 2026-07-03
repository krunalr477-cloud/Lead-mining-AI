"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CHART, SERIES_COLORS, axisProps, ChartTooltip } from "./theme";

export interface TimeseriesSeries {
  key: string;
  label: string;
  color?: string;
}

interface TimeseriesChartProps<Row extends Record<string, unknown>> {
  data: Row[];
  xKey: string;
  series: TimeseriesSeries[];
  height?: number;
  /** Optional x-axis tick formatter (e.g. date -> "Jul 3"). */
  formatX?: (value: unknown) => string;
}

/**
 * TimeseriesChart — dark-themed recharts <AreaChart> with soft gradient fills.
 * Kept generic for any time-indexed series (mining throughput, sends over time).
 */
export function TimeseriesChart<Row extends Record<string, unknown>>({
  data,
  xKey,
  series,
  height = 240,
  formatX,
}: TimeseriesChartProps<Row>) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <defs>
          {series.map((s, i) => {
            const color = s.color ?? SERIES_COLORS[i % SERIES_COLORS.length];
            return (
              <linearGradient
                key={s.key}
                id={`ts-grad-${s.key}`}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop offset="0%" stopColor={color} stopOpacity={0.28} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            );
          })}
        </defs>
        <CartesianGrid stroke={CHART.grid} vertical={false} />
        <XAxis
          dataKey={xKey}
          {...axisProps}
          tickFormatter={formatX ? (v) => formatX(v) : undefined}
          minTickGap={24}
        />
        <YAxis {...axisProps} width={36} />
        <Tooltip
          cursor={{ stroke: CHART.grid }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            return (
              <ChartTooltip
                title={formatX ? formatX(label) : String(label)}
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
            <Area
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={color}
              strokeWidth={2}
              fill={`url(#ts-grad-${s.key})`}
              isAnimationActive={false}
              dot={false}
            />
          );
        })}
      </AreaChart>
    </ResponsiveContainer>
  );
}
