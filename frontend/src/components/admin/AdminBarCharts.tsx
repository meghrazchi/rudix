"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type BarChartDatum = { label: string; value: number };

/** Horizontal bar chart shared by the admin report pages (recharts, R07-03). */
export function HorizontalBarChart({
  data,
  labelWidth,
  formatValue,
}: {
  data: BarChartDatum[];
  labelWidth: number;
  formatValue?: (value: number) => string;
}) {
  return (
    <div className="h-52 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 4, right: 16 }}>
          <CartesianGrid horizontal={false} stroke="#ece9f7" />
          <XAxis type="number" hide domain={[0, "dataMax"]} />
          <YAxis
            type="category"
            dataKey="label"
            width={labelWidth}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#5f5b72", fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{ borderRadius: 8, borderColor: "#dfdced" }}
            formatter={(value) =>
              formatValue ? formatValue(Number(value)) : value
            }
          />
          <Bar
            dataKey="value"
            radius={[0, 6, 6, 0]}
            barSize={12}
            fill="#3525cd"
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
