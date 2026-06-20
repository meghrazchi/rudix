import { apiRequest } from "@/lib/api/request";

export type OnboardingConfig = {
  sample_docs_enabled: boolean;
  reset_at: string | null;
};

export type LoadSampleDatasetResponse = {
  created: number;
  skipped: number;
  document_ids: string[];
};

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
