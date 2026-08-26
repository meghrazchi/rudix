import { apiRequest } from "@/lib/api/request";
import {
  onboardingReminderResultSchema,
  usageAdoptionChartsSchema,
  usageAdoptionSummarySchema,
  usageAdoptionUserListSchema,
  type OnboardingReminderResult,
  type UsageAdoptionCharts,
  type UsageAdoptionQuery,
  type UsageAdoptionSummary,
  type UsageAdoptionUserList,
} from "@/lib/schemas/usage-adoption";

const USAGE_ADOPTION_BASE_PATH = "/admin/usage-adoption";

function toQueryRecord(query: UsageAdoptionQuery) {
  return {
    from: query.from,
    to: query.to,
    role: query.role,
    page: query.page,
    page_size: query.page_size,
  };
}

export async function getUsageAdoptionSummary(
  query: UsageAdoptionQuery = {},
): Promise<UsageAdoptionSummary> {
  const payload = await apiRequest<unknown>(
    `${USAGE_ADOPTION_BASE_PATH}/summary`,
    {
      method: "GET",
      query: toQueryRecord(query),
      retry: false,
    },
  );
  return usageAdoptionSummarySchema.parse(payload);
}

export async function getUsageAdoptionCharts(
  query: UsageAdoptionQuery = {},
): Promise<UsageAdoptionCharts> {
  const payload = await apiRequest<unknown>(
    `${USAGE_ADOPTION_BASE_PATH}/charts`,
    {
      method: "GET",
      query: toQueryRecord(query),
      retry: false,
    },
  );
  return usageAdoptionChartsSchema.parse(payload);
}

export async function listUsageAdoptionUsers(
  query: UsageAdoptionQuery = {},
): Promise<UsageAdoptionUserList> {
  const payload = await apiRequest<unknown>(
    `${USAGE_ADOPTION_BASE_PATH}/users`,
    {
      method: "GET",
      query: toQueryRecord(query),
      retry: false,
    },
  );
  return usageAdoptionUserListSchema.parse(payload);
}

export async function exportUsageAdoption(
  query: UsageAdoptionQuery = {},
): Promise<Blob> {
  return apiRequest<Blob>(`${USAGE_ADOPTION_BASE_PATH}/export`, {
    method: "GET",
    query: toQueryRecord(query),
    responseType: "blob",
    retry: false,
  });
}

export async function sendOnboardingReminder(
  userId: string,
): Promise<OnboardingReminderResult> {
  const payload = await apiRequest<unknown>(
    `${USAGE_ADOPTION_BASE_PATH}/users/${encodeURIComponent(userId)}/onboarding-reminder`,
    {
      method: "POST",
      retry: false,
    },
  );
  return onboardingReminderResultSchema.parse(payload);
}
