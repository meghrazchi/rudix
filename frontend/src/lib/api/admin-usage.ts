import { apiRequest } from "@/lib/api/request";

export type UsageSummaryPoint = {
  period_start: string;
  period_end: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  event_count: number;
};

export type UsageSummaryResponse = {
  organization_id: string;
  range: {
    from: string;
    to: string;
  };
  totals: {
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
    event_count: number;
  };
  series: UsageSummaryPoint[];
};

export type UsageSummaryQuery = {
  from?: string;
  to?: string;
  granularity?: "day" | "week" | "month";
};

export async function getUsageSummary(query: UsageSummaryQuery = {}): Promise<UsageSummaryResponse> {
  return apiRequest<UsageSummaryResponse>("/admin/usage", {
    query,
  });
}
