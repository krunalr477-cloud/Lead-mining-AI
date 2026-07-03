"use client";

import { useMemo } from "react";
import {
  Funnel,
  FunnelChart,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  Cell,
} from "recharts";
import { SERIES_COLORS, ChartTooltip } from "./theme";

export interface FunnelDatum {
  stage: string;
  count: number;
}

interface FunnelChartWrapperProps {
  data: FunnelDatum[];
  /** Fixed pixel height; ResponsiveContainer fills width. */
  height?: number;
}

/**
 * FunnelChartWrapper — dark-themed recharts <FunnelChart> for the live
 * Mine -> Verify -> Send pipeline. Each stage tinted from the categorical
 * palette; the tooltip shows count + conversion vs the first (widest) stage.
 */
export function FunnelChartWrapper({
  data,
  height = 260,
}: FunnelChartWrapperProps) {
  const chartData = useMemo(
    () =>
      data.map((d, i) => ({
        ...d,
        fill: SERIES_COLORS[i % SERIES_COLORS.length],
      })),
    [data],
  );

  const top = data.length ? data[0].count : 0;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <FunnelChart margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
        <Tooltip
          cursor={false}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const p = payload[0].payload as FunnelDatum & { fill: string };
            const pct = top > 0 ? (p.count / top) * 100 : 0;
            return (
              <ChartTooltip
                title={p.stage}
                rows={[
                  { label: "Count", value: p.count.toLocaleString(), color: p.fill },
                  { label: "of top", value: `${pct.toFixed(1)}%` },
                ]}
              />
            );
          }}
        />
        <Funnel
          dataKey="count"
          data={chartData}
          isAnimationActive={false}
          stroke="rgba(0,0,0,0.35)"
        >
          <LabelList
            position="right"
            dataKey="stage"
            fill="#F5F7FA"
            stroke="none"
            fontSize={11}
          />
          <LabelList
            position="left"
            dataKey="count"
            fill="#7B8494"
            stroke="none"
            fontSize={11}
            formatter={(v: unknown) =>
              typeof v === "number" ? v.toLocaleString() : String(v ?? "")
            }
          />
          {chartData.map((d, i) => (
            <Cell key={i} fill={d.fill} />
          ))}
        </Funnel>
      </FunnelChart>
    </ResponsiveContainer>
  );
}
