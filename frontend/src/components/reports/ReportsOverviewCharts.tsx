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

export const BAR_COLORS = {
  default: "#6254d9",
  healthy: "#10b981",
  warning: "#f59e0b",
  critical: "#f43f5e",
} as const;

export type BarTone = Exclude<keyof typeof BAR_COLORS, "default">;

export type OverviewBarItem = {
  label: string;
  value: number;
  tone?: BarTone;
};

/** Chart block of the reports overview (loaded on demand, R07-03). */
export function OverviewBarChart({
  items,
  locale,
}: {
  items: OverviewBarItem[];
  locale: string;
}) {
  const format = new Intl.NumberFormat(locale, {
    notation: "compact",
    maximumFractionDigits: 1,
  });
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={items} layout="vertical" margin={{ left: 4, right: 16 }}>
        <CartesianGrid horizontal={false} stroke="#ece9f7" />
        <XAxis type="number" hide domain={[0, "dataMax"]} />
        <YAxis
          type="category"
          dataKey="label"
          width={92}
          axisLine={false}
          tickLine={false}
          tick={{ fill: "#5f5b72", fontSize: 11 }}
        />
        <Tooltip
          formatter={(value) => format.format(Number(value))}
          contentStyle={{ borderRadius: 8, borderColor: "#dfdced" }}
        />
        <Bar dataKey="value" radius={[0, 6, 6, 0]} barSize={10}>
          {items.map((item) => (
            <Cell
              key={item.label}
              fill={item.tone ? BAR_COLORS[item.tone] : BAR_COLORS.default}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
