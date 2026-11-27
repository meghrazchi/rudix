import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type OnboardingConfig = Served<Schemas["OnboardingConfigResponse"]>;

export type LoadSampleDatasetResponse = Served<
  Schemas["LoadSampleDatasetResponse"]
>;

export async function getOnboardingConfig(): Promise<OnboardingConfig> {
  return apiRequest<OnboardingConfig>("/admin/onboarding/config", {
    method: "GET",
  });
}

export async function patchOnboardingConfig(
  data: Partial<Pick<OnboardingConfig, "sample_docs_enabled">>,
): Promise<OnboardingConfig> {
  return apiRequest<OnboardingConfig>("/admin/onboarding/config", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function resetOnboarding(): Promise<OnboardingConfig> {
  return apiRequest<OnboardingConfig>("/admin/onboarding/reset", {
    method: "POST",
  });
}

export async function loadSampleDataset(): Promise<LoadSampleDatasetResponse> {
  return apiRequest<LoadSampleDatasetResponse>("/documents/sample", {
    method: "POST",
  });
}
