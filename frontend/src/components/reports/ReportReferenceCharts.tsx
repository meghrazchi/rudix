"use client";

import { useTranslations } from "next-intl";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const chartTooltipStyle = {
  border: "1px solid #dfdced",
  borderRadius: "8px",
  boxShadow: "0 4px 14px rgb(42 38 64 / 0.12)",
  color: "#2a2640",
  fontSize: "12px",
};

export function ReportBarChart({
  values,
  labels,
}: {
  values: number[];
  labels: string[];
}) {
  const t = useTranslations("reports.pages.chart");
  const data = labels.map((label, index) => ({
    label,
    value: values[index] ?? 0,
  }));
  const summary = data
    .map((item) => `${item.label}: ${item.value}%`)
    .join(", ");

  return (
    <div
      className="h-64 w-full"
      role="img"
      aria-label={summary}
      data-chart-library="recharts"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 16, right: 8, left: 8, bottom: 0 }}
        >
          <CartesianGrid
            vertical={false}
            stroke="#ebe8f4"
            strokeDasharray="3 3"
          />
          <XAxis
            dataKey="label"
            axisLine={{ stroke: "#dfdced" }}
            tickLine={false}
            tick={{ fill: "#777287", fontSize: 10 }}
          />
          <YAxis hide domain={[0, 100]} />
          <Tooltip
            cursor={{ fill: "#f7f5ff" }}
            contentStyle={chartTooltipStyle}
            formatter={(value) => [`${value}%`, t("score")]}
          />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={64}>
            {data.map((item, index) => (
              <Cell
                key={item.label}
                fill="#6254d9"
                fillOpacity={Math.min(1, 0.35 + index * 0.08)}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function FeedbackCategoryChart({
  data,
}: {
  data: ReadonlyArray<readonly [string, number]>;
}) {
  const t = useTranslations("reports.pages.chart");
  const chartData = data.map(([label, value]) => ({ label, value }));
  const summary = chartData
    .map((item) => `${item.label}: ${item.value}%`)
    .join(", ");

  return (
    <div
      className="h-72 w-full"
      role="img"
      aria-label={summary}
      data-chart-library="recharts"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 0, right: 38, bottom: 0, left: 0 }}
          barCategoryGap="34%"
        >
          <XAxis type="number" hide domain={[0, 50]} />
          <YAxis
            type="category"
            dataKey="label"
            width={104}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#403c52", fontSize: 12 }}
          />
          <Tooltip
            cursor={{ fill: "#f7f5ff" }}
            contentStyle={chartTooltipStyle}
            formatter={(value) => [`${value}%`, t("feedback")]}
          />
          <Bar
            dataKey="value"
            fill="#6254d9"
            radius={[0, 5, 5, 0]}
            background={{ fill: "#ece9f7", radius: 5 }}
          >
            {chartData.map((item) => (
              <Cell
                key={item.label}
                fill={item.label === "Hallucination" ? "#f43f5e" : "#6254d9"}
              />
            ))}
            <LabelList
              dataKey="value"
              position="right"
              fill="#403c52"
              fontSize={12}
              fontWeight={700}
              formatter={(value) => `${value}%`}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
