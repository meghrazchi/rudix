"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type AnswerQualityTrendPoint = {
  date: string;
  average_confidence: number | null;
  average_citation_support: number | null;
};

export function AnswerQualityTrendChart({
  data,
}: {
  data: AnswerQualityTrendPoint[];
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#ebe8f4" />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} />
        <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
        <Tooltip />
        <Legend />
        <Line
          type="monotone"
          dataKey="average_confidence"
          name="Confidence"
          stroke="#6254d9"
          strokeWidth={2}
        />
        <Line
          type="monotone"
          dataKey="average_citation_support"
          name="Citation support"
          stroke="#059669"
          strokeWidth={2}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
