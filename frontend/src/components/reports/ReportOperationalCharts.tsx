"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const tooltipStyle = {
  border: "1px solid #dfdced",
  borderRadius: "8px",
  boxShadow: "0 4px 14px rgb(42 38 64 / 0.12)",
  color: "#2a2640",
  fontSize: "12px",
};

const axisTick = { fill: "#777287", fontSize: 11 };

export function UsageTrendChart({
  data,
}: {
  data: Array<{ period: string; questions: number; users: number }>;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart
        data={data}
        margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
      >
        <CartesianGrid
          vertical={false}
          stroke="#ebe8f4"
          strokeDasharray="3 3"
        />
        <XAxis
          dataKey="period"
          tick={axisTick}
          axisLine={false}
          tickLine={false}
        />
        <YAxis tick={axisTick} axisLine={false} tickLine={false} />
        <Tooltip contentStyle={tooltipStyle} />
        <Line
          type="monotone"
          dataKey="questions"
          stroke="#4434c7"
          strokeWidth={3}
          dot={{ fill: "#4434c7", r: 4 }}
        />
        <Line
          type="monotone"
          dataKey="users"
          stroke="#10b981"
          strokeWidth={2}
          dot={{ fill: "#10b981", r: 3 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function FeatureAdoptionChart({
  data,
  adoptionLabel,
}: {
  data: Array<{ feature: string; adoption: number }>;
  adoptionLabel: string;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 24, left: 8, bottom: 0 }}
      >
        <XAxis type="number" hide domain={[0, 100]} />
        <YAxis
          type="category"
          dataKey="feature"
          width={82}
          tick={axisTick}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={(value) => [`${value}%`, adoptionLabel]}
        />
        <Bar
          dataKey="adoption"
          fill="#6254d9"
          radius={[0, 5, 5, 0]}
          background={{ fill: "#ece9f7", radius: 5 }}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function AccessPostureChart({
  data,
  resourcesLabel,
}: {
  data: Array<{ name: string; value: number; color: string }>;
  resourcesLabel: string;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          innerRadius={66}
          outerRadius={98}
          paddingAngle={3}
        >
          {data.map((item) => (
            <Cell key={item.name} fill={item.color} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={(value) => [`${value}%`, resourcesLabel]}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function GapTopicsChart({
  data,
}: {
  data: Array<{ topic: string; occurrences: number }>;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid
          vertical={false}
          stroke="#ebe8f4"
          strokeDasharray="3 3"
        />
        <XAxis
          dataKey="topic"
          tick={axisTick}
          axisLine={false}
          tickLine={false}
        />
        <YAxis tick={axisTick} axisLine={false} tickLine={false} />
        <Tooltip contentStyle={tooltipStyle} />
        <Bar
          dataKey="occurrences"
          fill="#6254d9"
          radius={[5, 5, 0, 0]}
          maxBarSize={64}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
