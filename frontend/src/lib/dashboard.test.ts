import { describe, expect, it } from "vitest";

import type { UsageSummaryResponse } from "@/lib/api/admin-usage";
import {
  canViewAdminUsage,
  computeIndexingSuccess,
  estimateQuestionsAsked,
  extractAverageConfidence,
  extractAverageLatencyMs,
  formatInteger,
  formatLatencyMs,
  formatPercentage,
  formatUsd,
  resolveUsageDateRange,
} from "@/lib/dashboard";

function usageFixture(
  overrides?: Partial<UsageSummaryResponse>,
): UsageSummaryResponse {
  return {
    organization_id: "org-1",
    range: { from: "2026-05-01", to: "2026-05-31" },
    totals: {
      input_tokens: 100,
      output_tokens: 25,
      cost_usd: 1.2,
      event_count: 10,
    },
    series: [],
    ...overrides,
  };
}

describe("dashboard helpers", () => {
  it("resolves UTC usage range for a preset", () => {
    const now = new Date("2026-05-14T10:30:00.000Z");
    expect(resolveUsageDateRange("7d", now)).toEqual({
      from: "2026-05-08",
      to: "2026-05-14",
    });
  });

  it("formats KPI values consistently", () => {
    expect(formatInteger(12345)).toBe("12,345");
    expect(formatPercentage(0.8123)).toBe("81.2%");
    expect(formatLatencyMs(432.7)).toBe("433 ms");
    expect(formatUsd(4.5)).toBe("$4.50");
  });

  it("computes indexing success ratio", () => {
    expect(computeIndexingSuccess(10, 8)).toBe(0.8);
    expect(computeIndexingSuccess(0, 0)).toBeNull();
  });

  it("estimates questions asked from chat session message counts", () => {
    expect(
      estimateQuestionsAsked([
        {
          session_id: "s-1",
          title: "A",
          message_count: 2,
          created_at: "2026-05-14T00:00:00Z",
          updated_at: "2026-05-14T00:00:00Z",
        },
        {
          session_id: "s-2",
          title: "B",
          message_count: 5,
          created_at: "2026-05-14T00:00:00Z",
          updated_at: "2026-05-14T00:00:00Z",
        },
      ]),
    ).toBe(4);
  });

  it("gates admin usage visibility by role", () => {
    expect(canViewAdminUsage("owner")).toBe(true);
    expect(canViewAdminUsage("admin")).toBe(true);
    expect(canViewAdminUsage("member")).toBe(false);
    expect(canViewAdminUsage("viewer")).toBe(false);
  });

  it("extracts confidence and latency from totals or series when available", () => {
    const totalsUsage = usageFixture({
      totals: {
        input_tokens: 100,
        output_tokens: 25,
        cost_usd: 1.2,
        event_count: 10,
        avg_confidence: 0.73,
        avg_latency_ms: 480,
      } as UsageSummaryResponse["totals"],
    });

    expect(extractAverageConfidence(totalsUsage)).toBe(0.73);
    expect(extractAverageLatencyMs(totalsUsage)).toBe(480);

    const seriesUsage = usageFixture({
      totals: {
        input_tokens: 100,
        output_tokens: 25,
        cost_usd: 1.2,
        event_count: 10,
      },
      series: [
        {
          period_start: "2026-05-01",
          period_end: "2026-05-02",
          input_tokens: 10,
          output_tokens: 2,
          cost_usd: 0.1,
          event_count: 1,
          average_confidence: 0.6,
          average_latency_ms: 400,
        } as UsageSummaryResponse["series"][number],
        {
          period_start: "2026-05-02",
          period_end: "2026-05-03",
          input_tokens: 10,
          output_tokens: 2,
          cost_usd: 0.1,
          event_count: 1,
          average_confidence: 0.8,
          average_latency_ms: 500,
        } as UsageSummaryResponse["series"][number],
      ],
    });

    expect(extractAverageConfidence(seriesUsage)).toBe(0.7);
    expect(extractAverageLatencyMs(seriesUsage)).toBe(450);
  });
});
