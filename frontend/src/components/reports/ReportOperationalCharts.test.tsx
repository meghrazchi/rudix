import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnswerQualityTrendChart } from "@/components/reports/AnswerQualityCharts";
import {
  AccessPostureChart,
  FeatureAdoptionChart,
  GapTopicsChart,
  UsageTrendChart,
} from "@/components/reports/ReportOperationalCharts";

// The chart blocks load through next/dynamic on their dashboards (R07-03), so the
// dashboard tests finish before they mount; render them directly here.
describe("lazy-loaded report chart blocks", () => {
  it.each([
    [
      "usage trend",
      <UsageTrendChart
        key="usage"
        data={[{ period: "2026-11-01", questions: 12, users: 3 }]}
      />,
    ],
    [
      "feature adoption",
      <FeatureAdoptionChart
        key="adoption"
        data={[{ feature: "Chat", adoption: 64 }]}
        adoptionLabel="Adoption"
      />,
    ],
    [
      "access posture",
      <AccessPostureChart
        key="posture"
        data={[{ name: "Restricted", value: 40, color: "#6254d9" }]}
        resourcesLabel="Resources"
      />,
    ],
    [
      "gap topics",
      <GapTopicsChart
        key="gaps"
        data={[{ topic: "Billing", occurrences: 5 }]}
      />,
    ],
    [
      "answer quality trend",
      <AnswerQualityTrendChart
        key="quality"
        data={[
          {
            date: "2026-11-01",
            average_confidence: 0.8,
            average_citation_support: 0.7,
          },
        ]}
      />,
    ],
  ])("renders the %s chart in a responsive container", (_name, chart) => {
    const { container } = render(
      <div style={{ width: 400, height: 240 }}>{chart}</div>,
    );
    expect(
      container.querySelector(".recharts-responsive-container"),
    ).toBeInTheDocument();
  });
});
